"""Full durable workflow service contracts against real Postgres."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from cognisect.api_models import (
    CreateCaseRequest,
    LearnerSubmitRequest,
    ProbeApprovalRequest,
    ReviewRequest,
)
from cognisect.config import Settings
from cognisect.database import create_session_factory
from cognisect.db_models import (
    AuditEventRecord,
    CaseRecord,
    CompiledProbeRecord,
    DeletionAuditTombstoneRecord,
    GeneratedProposalRecord,
    InvalidLearnerCommandRecord,
    LearnerResponseRecord,
    LearnerTokenRecord,
    OwnerRecord,
    ProbePredictionRecord,
    TeacherReviewRecord,
    WorkflowRecord,
)
from cognisect.models import RuleInstanceV1, RuleMappingV1
from cognisect.services import (
    AnalysisInput,
    AnalyzerExecutionError,
    AnalyzerResult,
    ExpiredLearnerTokenError,
    ReplayConflictError,
    RetentionService,
    WorkflowService,
)
from cognisect.workflow import WorkflowState


@dataclass
class Clock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


class FakeAnalyzer:
    def __init__(self, mapping: RuleMappingV1, *, proposal_draft: str | None = None) -> None:
        self.mapping = mapping
        self.proposal_draft = proposal_draft
        self.inputs: list[AnalysisInput] = []

    async def analyze(self, case: AnalysisInput) -> AnalyzerResult:
        self.inputs.append(case)
        return AnalyzerResult(
            mapping=self.mapping,
            model_id="test-model",
            model_snapshot="test-model-2026-07-16",
            request_id="req_test_public_metadata",
            proposal_draft=self.proposal_draft,
        )


class ExplodingAnalyzer:
    async def analyze(self, case: AnalysisInput) -> AnalyzerResult:
        msg = f"private analyzer failure: {case.observed_work}"
        raise RuntimeError(msg)


def mapping(*template_ids: str) -> RuleMappingV1:
    return RuleMappingV1(
        schema_version="rule_mapping.v1",
        hypotheses=[
            RuleInstanceV1(
                template_id=template_id,
                evidence_refs=[f"segment-{rank}"],
                description=f"Bounded alternative {rank}",
                rank=rank,
            )
            for rank, template_id in enumerate(template_ids, start=1)
        ],
    )


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect",
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        public_app_url="http://localhost:3000",
        openai_api_key="",
    )


@pytest.fixture
def case_request() -> CreateCaseRequest:
    return CreateCaseRequest(
        source_tier="custom",
        problem={"a": -3, "b": 5},
        observed_work="-3 - 5 = 2",
        deidentified_attestation=True,
    )


@pytest.fixture
def service(db_engine, db_session, test_settings):
    del db_session  # Its setup provides per-test truncation.
    return WorkflowService(
        create_session_factory(db_engine),
        test_settings,
        analyzer=FakeAnalyzer(mapping("add_subtrahend", "absolute_difference")),
    )


async def prepare_probe(service: WorkflowService, request: CreateCaseRequest):
    created = await service.create_case(request, idempotency_key="create-case-key")
    workflow = await service.analyze_case(
        owner_secret=created.owner_secret,
        case_id=created.case_id,
        expected_version=0,
        idempotency_key="analysis-key",
    )
    return created, workflow


@pytest.mark.postgres
async def test_owner_creation_hashes_secret_and_binds_case_and_workflow(
    service, db_engine, case_request
):
    created = await service.create_case(case_request, idempotency_key="create-case-key")
    factory = create_session_factory(db_engine)
    async with factory() as session:
        owner = await session.get(OwnerRecord, created.owner_id)
        case = await session.get(CaseRecord, created.case_id)
        workflow = await session.get(WorkflowRecord, created.workflow_id)
    assert owner is not None
    assert created.owner_secret not in owner.secret_hash
    assert case is not None
    assert case.owner_id == created.owner_id
    assert workflow is not None
    assert workflow.owner_id == created.owner_id


@pytest.mark.postgres
async def test_case_provenance_is_persisted_and_returned_only_on_owner_workflow_dto(
    service, db_engine
):
    request = CreateCaseRequest(
        source_tier="educator_authored",
        provenance_record_id="cognisect-ea-001",
        problem={"a": -3, "b": 5},
        observed_work="-3 - 5 = 2",
    )
    created = await service.create_case(request, idempotency_key="provenance-case-key")

    factory = create_session_factory(db_engine)
    async with factory() as session:
        case = await session.get(CaseRecord, created.case_id)
    assert case is not None
    assert case.provenance_record_id == "cognisect-ea-001"

    dto = await service.get_workflow_dto(created.owner_secret, created.workflow_id)
    assert dto.provenance_record_id == "cognisect-ea-001"


@pytest.mark.postgres
async def test_free_educator_entry_preserves_null_provenance(service, db_engine) -> None:
    request = CreateCaseRequest(
        source_tier="educator_authored",
        problem={"a": -3, "b": 5},
        observed_work="teacher-authored free entry",
    )
    created = await service.create_case(request, idempotency_key="free-entry-case-key")

    factory = create_session_factory(db_engine)
    async with factory() as session:
        case = await session.get(CaseRecord, created.case_id)
    assert case is not None
    assert case.provenance_record_id is None

    dto = await service.get_workflow_dto(created.owner_secret, created.workflow_id)
    assert dto.provenance_record_id is None


@pytest.mark.postgres
async def test_analysis_persists_probe_and_predictions_before_any_token(
    service, db_engine, case_request
):
    created, workflow = await prepare_probe(service, case_request)
    assert (workflow.state, workflow.version) == (WorkflowState.PROBE_READY, 2)
    factory = create_session_factory(db_engine)
    async with factory() as session:
        probe = await session.scalar(
            select(CompiledProbeRecord).where(
                CompiledProbeRecord.workflow_id == created.workflow_id
            )
        )
        prediction_count = await session.scalar(select(func.count(ProbePredictionRecord.id)))
        token_count = await session.scalar(select(func.count(LearnerTokenRecord.id)))
    assert probe is not None
    assert len(probe.specification_hash) == 64
    assert prediction_count == 2
    assert token_count == 0

    dto = await service.get_workflow_dto(created.owner_secret, created.workflow_id)
    assert dto.compiled_probe is not None
    assert dto.compiled_probe.proof.domain_problem_count == 625
    assert dto.compiled_probe.proof.eligible_candidate_count == 624
    assert dto.compiled_probe.proof.chosen_candidate_rank == 1
    assert dto.compiled_probe.proof.top_candidates[0].problem == dto.compiled_probe.problem
    assert dto.compiled_probe.proof.top_candidates[0].predictions == [
        prediction.prediction for prediction in dto.compiled_probe.predictions
    ]


@pytest.mark.postgres
async def test_teacher_dto_fails_closed_when_persisted_probe_predictions_do_not_reproduce(
    service, db_engine, case_request
):
    created, _workflow = await prepare_probe(service, case_request)
    factory = create_session_factory(db_engine)
    async with factory() as session, session.begin():
        prediction = await session.scalar(select(ProbePredictionRecord))
        assert prediction is not None
        prediction.prediction += 1

    with pytest.raises(ReplayConflictError, match="persisted compiler proof"):
        await service.get_workflow_dto(created.owner_secret, created.workflow_id)


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("correct_prediction", 9_999),
        ("registry_version", "rule_registry.tampered"),
        ("compiler_version", "counterexample_compiler.tampered"),
        ("specification_hash", "f" * 64),
        ("original_a", -2),
        ("chosen_a", 9),
    ],
)
async def test_teacher_dto_fails_closed_when_persisted_probe_header_does_not_reproduce(
    service, db_engine, case_request, field, tampered_value
):
    created, _workflow = await prepare_probe(service, case_request)
    factory = create_session_factory(db_engine)
    async with factory() as session, session.begin():
        probe = await session.scalar(select(CompiledProbeRecord))
        assert probe is not None
        setattr(probe, field, tampered_value)

    with pytest.raises(ReplayConflictError, match="persisted compiler proof"):
        await service.get_workflow_dto(created.owner_secret, created.workflow_id)


@pytest.mark.postgres
async def test_terra_note_is_persisted_before_response_then_only_evidence_is_attached(
    db_engine, db_session, test_settings, case_request
):
    del db_session
    draft = "Two ranked hypotheses remain plausible; teacher review is required."
    service = WorkflowService(
        create_session_factory(db_engine),
        test_settings,
        analyzer=FakeAnalyzer(
            mapping("add_subtrahend", "absolute_difference"),
            proposal_draft=draft,
        ),
    )
    created, workflow = await prepare_probe(service, case_request)
    factory = create_session_factory(db_engine)
    async with factory() as session:
        before = await session.scalar(
            select(GeneratedProposalRecord).where(
                GeneratedProposalRecord.workflow_id == created.workflow_id
            )
        )
        assert before is not None
        assert before.generated_text == draft
        assert before.evidence == []

    approved = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=ProbeApprovalRequest(expected_version=workflow.version, approved=True),
        idempotency_key="draft-approval",
    )
    assert approved.token is not None
    await service.submit_learner_response(
        token=approved.token,
        request=LearnerSubmitRequest(answer=3),
        idempotency_key="draft-response",
    )

    async with factory() as session:
        after = await session.scalar(
            select(GeneratedProposalRecord).where(
                GeneratedProposalRecord.workflow_id == created.workflow_id
            )
        )
        assert after is not None
        assert after.generated_text == draft
        assert after.evidence


@pytest.mark.postgres
async def test_approval_uses_fresh_nonce_and_exact_replay_returns_same_capability(
    service, db_engine, case_request
):
    created, workflow = await prepare_probe(service, case_request)
    request = ProbeApprovalRequest(
        expected_version=workflow.version,
        approved=True,
        expires_in_seconds=3600,
    )
    approved = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=request,
        idempotency_key="nonce-approval-key",
    )
    replayed = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=request,
        idempotency_key="nonce-approval-key",
    )

    assert approved.token is not None
    assert replayed.token == approved.token
    factory = create_session_factory(db_engine)
    async with factory() as session:
        token_record = await session.scalar(
            select(LearnerTokenRecord).where(LearnerTokenRecord.workflow_id == created.workflow_id)
        )
    assert token_record is not None
    assert len(token_record.derivation_nonce) == 32
    assert token_record.token_hash != approved.token
    assert approved.token not in repr(token_record)


@pytest.mark.postgres
async def test_approval_fails_closed_until_probe_interrupt_is_reconstructed(
    service, db_engine, case_request
):
    created, workflow = await prepare_probe(service, case_request)

    class MissingGateGraph:
        async def start_probe_interrupt(self, workflow_id, thread_id):
            assert workflow_id == created.workflow_id
            assert thread_id == workflow.thread_id
            return {}

        async def resume_probe(self, _thread_id, *, approved):
            msg = f"missing gate cannot be resumed: {approved}"
            raise AssertionError(msg)

    service.attach_graph_runtime(MissingGateGraph())
    with pytest.raises(ReplayConflictError, match="probe approval gate is not ready"):
        await service.approve_probe(
            owner_secret=created.owner_secret,
            workflow_id=created.workflow_id,
            request=ProbeApprovalRequest(expected_version=workflow.version, approved=True),
            idempotency_key="missing-probe-gate",
        )

    persisted = await service.get_workflow(created.owner_secret, created.workflow_id)
    assert persisted.state == WorkflowState.PROBE_READY
    factory = create_session_factory(db_engine)
    async with factory() as session:
        assert await session.scalar(select(func.count(LearnerTokenRecord.id))) == 0


@pytest.mark.postgres
async def test_no_separating_probe_transitions_to_abstained(
    db_engine, db_session, test_settings, case_request
):
    del db_session
    duplicate_analyzer = FakeAnalyzer(mapping("absolute_difference", "absolute_difference"))
    service = WorkflowService(
        create_session_factory(db_engine), test_settings, analyzer=duplicate_analyzer
    )
    created = await service.create_case(case_request, idempotency_key="create")
    workflow = await service.analyze_case(
        owner_secret=created.owner_secret,
        case_id=created.case_id,
        expected_version=0,
        idempotency_key="analyze",
    )
    assert workflow.state == WorkflowState.ABSTAINED


@pytest.mark.postgres
async def test_analyzer_failure_transitions_to_failed_without_leaking_content(
    db_engine, db_session, test_settings, case_request
):
    del db_session
    service = WorkflowService(
        create_session_factory(db_engine), test_settings, analyzer=ExplodingAnalyzer()
    )
    created = await service.create_case(case_request, idempotency_key="create")
    with pytest.raises(AnalyzerExecutionError) as caught:
        await service.analyze_case(
            owner_secret=created.owner_secret,
            case_id=created.case_id,
            expected_version=0,
            idempotency_key="analyze",
        )
    assert case_request.observed_work not in str(caught.value)
    workflow = await service.get_workflow(created.owner_secret, created.workflow_id)
    assert (workflow.state, workflow.version) == (WorkflowState.FAILED, 2)


@pytest.mark.postgres
async def test_review_before_awaiting_review_rolls_back_review_record(
    service, db_engine, case_request
):
    created, workflow = await prepare_probe(service, case_request)
    with pytest.raises(ValueError, match="workflow transition is not allowed"):
        await service.review_workflow(
            owner_secret=created.owner_secret,
            workflow_id=created.workflow_id,
            request=ReviewRequest(
                expected_version=workflow.version,
                decision="approved",
                note="Cannot approve before a learner response.",
            ),
            idempotency_key="early-review",
        )
    factory = create_session_factory(db_engine)
    async with factory() as session:
        assert await session.scalar(select(func.count(TeacherReviewRecord.id))) == 0


@pytest.mark.postgres
async def test_get_does_not_consume_and_post_replay_rules_are_atomic(
    service, db_engine, case_request
):
    created, workflow = await prepare_probe(service, case_request)
    approved = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=ProbeApprovalRequest(
            expected_version=workflow.version,
            approved=True,
            expires_in_seconds=3600,
        ),
        idempotency_key="approve-key",
    )
    first = await service.get_learner_probe(approved.token)
    second = await service.get_learner_probe(approved.token)
    assert first == second

    factory = create_session_factory(db_engine)
    async with factory() as session:
        assert await session.scalar(select(func.count(LearnerResponseRecord.id))) == 0

    receipt = await service.submit_learner_response(
        token=approved.token,
        request=LearnerSubmitRequest(answer=first.problem.a - first.problem.b),
        idempotency_key="submit-key",
    )
    replayed = await service.submit_learner_response(
        token=approved.token,
        request=LearnerSubmitRequest(answer=first.problem.a - first.problem.b),
        idempotency_key="submit-key",
    )
    assert replayed == receipt
    with pytest.raises(ReplayConflictError):
        await service.submit_learner_response(
            token=approved.token,
            request=LearnerSubmitRequest(answer=17),
            idempotency_key="submit-key",
        )
    with pytest.raises(ReplayConflictError):
        await service.submit_learner_response(
            token=approved.token,
            request=LearnerSubmitRequest(
                answer=first.problem.a - first.problem.b,
                rationale="A different canonical request payload.",
            ),
            idempotency_key="submit-key",
        )
    with pytest.raises(ReplayConflictError):
        await service.submit_learner_response(
            token=approved.token,
            request=LearnerSubmitRequest(answer=17),
            idempotency_key="different-key",
        )


@pytest.mark.postgres
async def test_expired_token_returns_gone_without_response(
    db_engine, db_session, test_settings, case_request
):
    del db_session
    clock = Clock(datetime(2026, 7, 16, tzinfo=UTC))
    service = WorkflowService(
        create_session_factory(db_engine),
        test_settings,
        analyzer=FakeAnalyzer(mapping("add_subtrahend", "absolute_difference")),
        clock=clock,
    )
    created, workflow = await prepare_probe(service, case_request)
    approved = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=ProbeApprovalRequest(
            expected_version=workflow.version,
            approved=True,
            expires_in_seconds=60,
        ),
        idempotency_key="approve",
    )
    clock.now += timedelta(seconds=61)
    with pytest.raises(ExpiredLearnerTokenError):
        await service.get_learner_probe(approved.token)
    with pytest.raises(ExpiredLearnerTokenError):
        await service.submit_learner_response(
            token=approved.token,
            request=LearnerSubmitRequest(answer=1),
            idempotency_key="expired",
        )
    with pytest.raises(ExpiredLearnerTokenError):
        await service.submit_invalid_learner_answer(
            token=approved.token,
            idempotency_key="expired-invalid",
        )


@pytest.mark.postgres
async def test_concurrent_invalid_answers_abstain_once_and_replay_one_receipt(
    service, db_engine, case_request
):
    created, workflow = await prepare_probe(service, case_request)
    approved = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=ProbeApprovalRequest(expected_version=workflow.version, approved=True),
        idempotency_key="invalid-concurrent-approval",
    )
    receipts = await asyncio.gather(
        *(
            service.submit_invalid_learner_answer(
                token=approved.token,
                idempotency_key="invalid-concurrent-key",
            )
            for _ in range(5)
        )
    )

    assert len({receipt.receipt_id for receipt in receipts}) == 1
    persisted = await service.get_workflow(created.owner_secret, created.workflow_id)
    assert persisted.state == WorkflowState.ABSTAINED
    factory = create_session_factory(db_engine)
    async with factory() as session:
        assert await session.scalar(select(func.count(InvalidLearnerCommandRecord.id))) == 1
        assert await session.scalar(select(func.count(LearnerResponseRecord.id))) == 0


@pytest.mark.postgres
async def test_fifty_concurrent_submissions_store_exactly_one_response(
    service, db_engine, case_request
):
    created, workflow = await prepare_probe(service, case_request)
    approved = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=ProbeApprovalRequest(
            expected_version=workflow.version,
            approved=True,
            expires_in_seconds=3600,
        ),
        idempotency_key="approve",
    )

    async def submit(index: int):
        try:
            return await service.submit_learner_response(
                token=approved.token,
                request=LearnerSubmitRequest(answer=index),
                idempotency_key=f"concurrent-{index}",
            )
        except ReplayConflictError:
            return None

    results = await asyncio.gather(*(submit(index) for index in range(50)))
    assert sum(result is not None for result in results) == 1
    factory = create_session_factory(db_engine)
    async with factory() as session:
        assert await session.scalar(select(func.count(LearnerResponseRecord.id))) == 1


@pytest.mark.postgres
async def test_full_loop_review_and_audit_readback(service, case_request):
    created, workflow = await prepare_probe(service, case_request)
    approved = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=ProbeApprovalRequest(expected_version=workflow.version, approved=True),
        idempotency_key="approve",
    )
    learner = await service.get_learner_probe(approved.token)
    await service.submit_learner_response(
        token=approved.token,
        request=LearnerSubmitRequest(answer=learner.problem.a - learner.problem.b),
        idempotency_key="submit",
    )
    pending = await service.get_workflow(created.owner_secret, created.workflow_id)
    reviewed = await service.review_workflow(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=ReviewRequest(
            expected_version=pending.version,
            decision="approved",
            note="Reviewed against the supplied de-identified work.",
        ),
        idempotency_key="review",
    )
    assert reviewed.state == WorkflowState.APPROVED
    events = await service.get_audit(created.owner_secret, created.workflow_id)
    assert [event.to_state for event in events] == [
        WorkflowState.ANALYZING,
        WorkflowState.PROBE_READY,
        WorkflowState.AWAITING_RESPONSE,
        WorkflowState.RESPONSE_RECORDED,
        WorkflowState.RESUME_PENDING,
        WorkflowState.UPDATING,
        WorkflowState.AWAITING_REVIEW,
        WorkflowState.APPROVED,
    ]
    assert [event.version for event in events] == list(range(1, 9))


@pytest.mark.postgres
async def test_owner_workflow_dto_returns_review_only_learner_rationale(service, case_request):
    created, workflow = await prepare_probe(service, case_request)
    approved = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=ProbeApprovalRequest(expected_version=workflow.version, approved=True),
        idempotency_key="rationale-approve",
    )
    learner = await service.get_learner_probe(approved.token)
    await service.submit_learner_response(
        token=approved.token,
        request=LearnerSubmitRequest(
            answer=learner.problem.a - learner.problem.b,
            rationale="I kept the second sign and counted left.",
        ),
        idempotency_key="rationale-submit",
    )

    dto = await service.get_workflow_dto(created.owner_secret, created.workflow_id)
    assert dto.learner_rationale == "I kept the second sign and counted left."


@pytest.mark.postgres
async def test_final_teacher_abstention_persists_before_graph_resume_and_replays(
    service, db_engine, case_request
):
    created, workflow = await prepare_probe(service, case_request)
    approved = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=ProbeApprovalRequest(expected_version=workflow.version, approved=True),
        idempotency_key="abstain-approve",
    )
    await service.submit_learner_response(
        token=approved.token,
        request=LearnerSubmitRequest(answer=3),
        idempotency_key="abstain-submit",
    )
    pending = await service.get_workflow(created.owner_secret, created.workflow_id)

    class ReviewGraph:
        def __init__(self) -> None:
            self.resumes = 0

        async def resume_review(self, thread_id, *, decision):
            persisted = await service.get_workflow(created.owner_secret, created.workflow_id)
            assert persisted.state == WorkflowState.ABSTAINED
            assert persisted.thread_id == thread_id
            assert decision == "abstained"
            self.resumes += 1

    graph = ReviewGraph()
    service.attach_graph_runtime(graph)
    request = ReviewRequest(
        expected_version=pending.version,
        decision="abstained",
        note="Evidence remains insufficient.",
    )
    first = await service.review_workflow(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=request,
        idempotency_key="abstain-review",
    )
    replay = await service.review_workflow(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=request,
        idempotency_key="abstain-review",
    )

    assert first.state == replay.state == WorkflowState.ABSTAINED
    assert graph.resumes == 2
    dto = await service.get_workflow_dto(created.owner_secret, created.workflow_id)
    assert dto.state == "ABSTAINED"
    assert dto.edited_text is None
    events = await service.get_audit(created.owner_secret, created.workflow_id)
    assert events[-1].to_state == WorkflowState.ABSTAINED
    assert events[-1].version == 8
    factory = create_session_factory(db_engine)
    async with factory() as session:
        review = await session.scalar(select(TeacherReviewRecord))
    assert review is not None
    assert review.decision == "abstained"
    assert review.edited_text is None


@pytest.mark.postgres
async def test_exact_learner_replay_recovers_crash_after_resume_pending(service, case_request):
    created, workflow = await prepare_probe(service, case_request)
    approved = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=ProbeApprovalRequest(expected_version=workflow.version, approved=True),
        idempotency_key="approve-before-crash",
    )

    class CrashOnceGraph:
        def __init__(self) -> None:
            self.response_resumes = 0

        async def resume_after_response(self, workflow_id, thread_id):
            assert workflow_id == created.workflow_id
            assert thread_id == workflow.thread_id
            self.response_resumes += 1
            if self.response_resumes == 1:
                return {}
            await service.advance_response_update(workflow_id)
            return {"__interrupt__": ("teacher_review",)}

    graph = CrashOnceGraph()
    service.attach_graph_runtime(graph)
    request = LearnerSubmitRequest(answer=3, rationale="deidentified")

    first = await service.submit_learner_response(
        token=approved.token,
        request=request,
        idempotency_key="recoverable-submit",
    )
    interrupted = await service.get_workflow(created.owner_secret, created.workflow_id)
    assert interrupted.state == WorkflowState.RESUME_PENDING

    replay = await service.submit_learner_response(
        token=approved.token,
        request=request,
        idempotency_key="recoverable-submit",
    )

    recovered = await service.get_workflow(created.owner_secret, created.workflow_id)
    assert replay == first
    assert recovered.state == WorkflowState.AWAITING_REVIEW
    assert graph.response_resumes == 2


@pytest.mark.postgres
async def test_graph_commands_observe_db_state_first_and_replays_recover(service, case_request):
    created = await service.create_case(case_request, idempotency_key="graph-create")

    class OrderingGraph:
        def __init__(self) -> None:
            self.probe_starts = 0
            self.probe_resumes = 0
            self.response_resumes = 0
            self.review_resumes = 0

        async def start_probe_interrupt(self, workflow_id, thread_id):
            persisted = await service.get_workflow(created.owner_secret, workflow_id)
            assert persisted.state == WorkflowState.PROBE_READY
            assert persisted.thread_id == thread_id
            self.probe_starts += 1
            return {"__interrupt__": ("probe_approval",)}

        async def resume_probe(self, thread_id, *, approved):
            persisted = await service.get_workflow(created.owner_secret, created.workflow_id)
            expected = WorkflowState.AWAITING_RESPONSE if approved else WorkflowState.ABSTAINED
            assert persisted.state == expected
            assert persisted.thread_id == thread_id
            self.probe_resumes += 1

        async def resume_after_response(self, workflow_id, thread_id):
            persisted = await service.get_workflow(created.owner_secret, workflow_id)
            assert persisted.state in {
                WorkflowState.RESUME_PENDING,
                WorkflowState.AWAITING_REVIEW,
            }
            assert persisted.thread_id == thread_id
            self.response_resumes += 1
            await service.advance_response_update(workflow_id)

        async def resume_review(self, thread_id, *, decision):
            persisted = await service.get_workflow(created.owner_secret, created.workflow_id)
            assert persisted.state == WorkflowState.APPROVED
            assert persisted.thread_id == thread_id
            assert decision == "approved"
            self.review_resumes += 1

    graph = OrderingGraph()
    service.attach_graph_runtime(graph)
    workflow = await service.analyze_case(
        owner_secret=created.owner_secret,
        case_id=created.case_id,
        expected_version=0,
        idempotency_key="graph-analysis",
    )
    replayed_workflow = await service.analyze_case(
        owner_secret=created.owner_secret,
        case_id=created.case_id,
        expected_version=0,
        idempotency_key="graph-analysis",
    )
    assert replayed_workflow.id == workflow.id
    approval_request = ProbeApprovalRequest(expected_version=workflow.version, approved=True)
    approved = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=approval_request,
        idempotency_key="graph-approval",
    )
    replayed_approval = await service.approve_probe(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=approval_request,
        idempotency_key="graph-approval",
    )
    assert replayed_approval.token == approved.token

    submit_request = LearnerSubmitRequest(answer=3)
    await service.submit_learner_response(
        token=approved.token,
        request=submit_request,
        idempotency_key="graph-response",
    )
    await service.submit_learner_response(
        token=approved.token,
        request=submit_request,
        idempotency_key="graph-response",
    )
    pending = await service.get_workflow(created.owner_secret, created.workflow_id)
    review_request = ReviewRequest(
        expected_version=pending.version,
        decision="approved",
        note="reviewed",
    )
    await service.review_workflow(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=review_request,
        idempotency_key="graph-review",
    )
    await service.review_workflow(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        request=review_request,
        idempotency_key="graph-review",
    )

    assert graph.probe_starts == 3
    assert graph.probe_resumes == 2
    assert graph.response_resumes == 2
    assert graph.review_resumes == 2


@pytest.mark.postgres
async def test_delete_removes_content_and_leaves_only_tombstone(service, db_engine, case_request):
    created, _workflow = await prepare_probe(service, case_request)
    await service.delete_workflow(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        idempotency_key="delete",
    )
    factory = create_session_factory(db_engine)
    async with factory() as session:
        assert await session.get(WorkflowRecord, created.workflow_id) is None
        assert await session.get(CaseRecord, created.case_id) is None
        tombstone = await session.scalar(
            select(DeletionAuditTombstoneRecord).where(
                DeletionAuditTombstoneRecord.workflow_id == created.workflow_id
            )
        )
        remaining_events = await session.scalar(select(func.count(AuditEventRecord.id)))
    assert tombstone is not None
    assert remaining_events == 0
    async with factory() as session:
        assert await session.scalar(select(func.count(OwnerRecord.id))) == 0
        assert await session.scalar(select(func.count(LearnerTokenRecord.id))) == 0


@pytest.mark.postgres
async def test_retention_selects_and_purges_cases_older_than_configured_days(
    service, db_engine, case_request, test_settings
):
    created, _workflow = await prepare_probe(service, case_request)
    factory = create_session_factory(db_engine)
    now = datetime.now(UTC)
    async with factory() as session:
        case = await session.get(CaseRecord, created.case_id)
        assert case is not None
        case.created_at = now - timedelta(days=31)
        await session.commit()

    retention = RetentionService(factory, retention_days=test_settings.retention_days)
    assert await retention.select_expired(now=now) == [created.workflow_id]
    assert await retention.purge_expired(now=now) == 1


@pytest.mark.postgres
async def test_retention_purges_abandoned_empty_owner_sessions(
    service, db_engine, test_settings
):
    await service.bootstrap_owner()
    factory = create_session_factory(db_engine)
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        owner = await session.scalar(select(OwnerRecord))
        assert owner is not None
        owner.created_at = now - timedelta(days=test_settings.retention_days + 1)

    retention = RetentionService(factory, retention_days=test_settings.retention_days)
    assert await retention.purge_expired(now=now) == 0
    async with factory() as session:
        assert await session.scalar(select(func.count(OwnerRecord.id))) == 0


@pytest.mark.postgres
async def test_retention_skips_empty_owner_locked_for_first_case_registration(
    service, db_engine, case_request, test_settings
):
    owner_secret = await service.bootstrap_owner()
    factory = create_session_factory(db_engine)
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        owner = await session.scalar(select(OwnerRecord))
        assert owner is not None
        owner.created_at = now - timedelta(days=test_settings.retention_days + 1)

    async with factory() as session, session.begin():
        owner = await session.scalar(select(OwnerRecord).with_for_update())
        assert owner is not None

        retention = RetentionService(
            factory,
            retention_days=test_settings.retention_days,
        )
        purge_task = asyncio.create_task(retention.purge_expired(now=now))
        assert await asyncio.wait_for(purge_task, timeout=1) == 0

    created = await service.create_case(
        case_request,
        idempotency_key="retention-lock-registration",
        owner_secret=owner_secret,
    )
    async with factory() as session:
        assert await session.scalar(select(func.count(OwnerRecord.id))) == 1
        assert await session.get(CaseRecord, created.case_id) is not None
        assert await session.get(WorkflowRecord, created.workflow_id) is not None
