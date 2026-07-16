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
    def __init__(self, mapping: RuleMappingV1) -> None:
        self.mapping = mapping
        self.inputs: list[AnalysisInput] = []

    async def analyze(self, case: AnalysisInput) -> AnalyzerResult:
        self.inputs.append(case)
        return AnalyzerResult(
            mapping=self.mapping,
            model_id="test-model",
            model_snapshot="test-model-2026-07-16",
            request_id="req_test_public_metadata",
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
            select(LearnerTokenRecord).where(
                LearnerTokenRecord.workflow_id == created.workflow_id
            )
        )
    assert token_record is not None
    assert len(token_record.derivation_nonce) == 32
    assert token_record.token_hash != approved.token
    assert approved.token not in repr(token_record)


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
async def test_delete_removes_content_and_leaves_only_tombstone(
    service, db_engine, case_request
):
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
