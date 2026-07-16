"""Transaction-bounded workflow, token, review, deletion, and retention services."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognisect.api_models import (
    AnswerConstraints,
    CreateCaseRequest,
    LearnerProbeResponse,
    LearnerSubmitRequest,
    ProbeApprovalRequest,
    ReviewRequest,
    SignedProblemDTO,
    WorkflowResponse,
)
from cognisect.compiler import CompiledProbe, CompilerAbstention, ProbeHypothesis, SignedProblem
from cognisect.config import Settings
from cognisect.db_models import (
    AcceptedHypothesisRecord,
    AuditEventRecord,
    CaseRecord,
    CompiledProbeRecord,
    DeletionAuditTombstoneRecord,
    GeneratedProposalRecord,
    IdempotencyRecord,
    LearnerReceiptRecord,
    LearnerResponseRecord,
    LearnerTokenRecord,
    ModelCallRecord,
    OwnerRecord,
    ProbePredictionRecord,
    TeacherReviewRecord,
    WorkflowRecord,
    utc_now,
)
from cognisect.evidence import LearnerResponseV1, update_evidence
from cognisect.interpreter import accept_hypotheses
from cognisect.models import RuleMappingV1
from cognisect.repositories import (
    OwnedResourceNotFoundError,
    get_owned_workflow,
    transition_workflow,
)
from cognisect.security import (
    derive_learner_secret,
    generate_derivation_nonce,
    generate_secret,
    hash_payload,
    hash_secret,
    secrets_match,
)
from cognisect.workflow import WorkflowState

Clock = Callable[[], datetime]


class ServiceError(RuntimeError):
    """Content-free base service error."""


class ReplayConflictError(ServiceError):
    """A consumed capability or idempotency-key conflict."""


class ExpiredLearnerTokenError(ServiceError):
    """An otherwise valid learner capability has expired."""


class LearnerTokenNotFoundError(ServiceError):
    """Non-enumerating learner capability miss."""


class AnalyzerNotConfiguredError(ServiceError):
    """Production analysis was requested without an injected analyzer."""


class AnalyzerExecutionError(ServiceError):
    """Generic analyzer failure with no educational content or provider detail."""


@dataclass(frozen=True, slots=True)
class AnalysisInput:
    """De-identified, detached analysis input passed outside transactions."""

    case_id: UUID
    workflow_id: UUID
    original_a: int
    original_b: int
    observed_work: str


@dataclass(frozen=True, slots=True)
class AnalyzerResult:
    """Bounded structured analyzer output and public model metadata."""

    mapping: RuleMappingV1
    model_id: str
    model_snapshot: str | None = None
    request_id: str | None = None


class Analyzer(Protocol):
    """Injected model analyzer; no implicit fake is permitted."""

    async def analyze(self, case: AnalysisInput) -> AnalyzerResult:
        """Analyze de-identified work and return a strict mapping."""
        ...


@dataclass(frozen=True, slots=True)
class CreatedCase:
    """New owner capability and bound aggregate identifiers."""

    owner_id: UUID
    owner_secret: str
    case_id: UUID
    workflow_id: UUID


@dataclass(frozen=True, slots=True)
class ApprovedProbe:
    """Teacher approval result with a raw capability returned only in memory."""

    token: str | None
    expires_at: datetime | None
    workflow: WorkflowRecord


@dataclass(frozen=True, slots=True)
class LearnerReceipt:
    """Stable content-minimal learner receipt."""

    receipt_id: UUID
    accepted_at: datetime


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hash_payload(payload)


def _deletion_replay_hash(
    *, owner_secret: str, workflow_id: UUID, idempotency_key: str, owner_pepper: str
) -> str:
    """Bind a content-free deletion replay verifier to owner, workflow, and key."""
    owner_hash = hash_secret(owner_secret, owner_pepper, purpose="owner")
    replay_secret = f"{owner_hash}\x00{workflow_id}\x00{idempotency_key}"
    return hash_secret(replay_secret, owner_pepper, purpose="deletion-replay")


def _now_utc(clock: Clock) -> datetime:
    value = clock()
    if value.tzinfo is None:
        msg = "clock must return an aware datetime"
        raise ValueError(msg)
    return value.astimezone(UTC)


class WorkflowService:
    """Orchestrate explicit workflow commands with short Postgres transactions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        analyzer: Analyzer | None,
        clock: Clock = utc_now,
    ) -> None:
        """Initialize with an explicit session factory, settings, and analyzer choice."""
        self._sessions = session_factory
        self._settings = settings
        self._analyzer = analyzer
        self._clock = clock

    @property
    def _owner_pepper(self) -> str:
        return self._settings.owner_secret_pepper.get_secret_value()

    @property
    def _learner_pepper(self) -> str:
        return self._settings.learner_token_pepper.get_secret_value()

    async def _owner_for_secret(self, session: AsyncSession, secret: str) -> OwnerRecord:
        secret_hash = hash_secret(secret, self._owner_pepper, purpose="owner")
        owner = await session.scalar(
            select(OwnerRecord).where(OwnerRecord.secret_hash == secret_hash)
        )
        if owner is None:
            msg = "resource not found"
            raise OwnedResourceNotFoundError(msg)
        return owner

    async def _idempotency_replay(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        scope: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> IdempotencyRecord | None:
        record = await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.owner_id == owner_id,
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.key_hash == hash_payload(idempotency_key.encode()),
            )
        )
        if record is not None and record.request_hash != request_fingerprint:
            msg = "idempotency key conflicts with an earlier request"
            raise ReplayConflictError(msg)
        return record

    def _store_idempotency(  # noqa: PLR0913
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        scope: str,
        idempotency_key: str,
        request_fingerprint: str,
        response_body: dict[str, object],
        response_status: int = 200,
    ) -> None:
        session.add(
            IdempotencyRecord(
                owner_id=owner_id,
                scope=scope,
                key_hash=hash_payload(idempotency_key.encode()),
                request_hash=request_fingerprint,
                response_status=response_status,
                response_body=response_body,
                expires_at=_now_utc(self._clock) + timedelta(days=self._settings.retention_days),
            )
        )

    async def create_case(
        self,
        request: CreateCaseRequest,
        *,
        idempotency_key: str,
        owner_secret: str | None = None,
    ) -> CreatedCase:
        """Create or reuse an owner and bind a new case/workflow aggregate."""
        request_fingerprint = _fingerprint(request.model_dump(mode="json"))
        async with self._sessions() as session, session.begin():
            if owner_secret is None:
                owner_secret = generate_secret()
                owner = OwnerRecord(
                    secret_hash=hash_secret(owner_secret, self._owner_pepper, purpose="owner")
                )
                session.add(owner)
                await session.flush()
            else:
                owner = await self._owner_for_secret(session, owner_secret)
                replay = await self._idempotency_replay(
                    session,
                    owner_id=owner.id,
                    scope="cases:create",
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if replay is not None:
                    return CreatedCase(
                        owner_id=owner.id,
                        owner_secret=owner_secret,
                        case_id=UUID(str(replay.response_body["case_id"])),
                        workflow_id=UUID(str(replay.response_body["workflow_id"])),
                    )

            case = CaseRecord(
                owner_id=owner.id,
                source_tier=request.source_tier,
                original_a=request.problem.a,
                original_b=request.problem.b,
                observed_work=request.observed_work,
                deidentified_attestation=request.deidentified_attestation,
            )
            session.add(case)
            await session.flush()
            workflow = WorkflowRecord(case_id=case.id, owner_id=owner.id)
            session.add(workflow)
            await session.flush()
            self._store_idempotency(
                session,
                owner_id=owner.id,
                scope="cases:create",
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                response_body={"case_id": str(case.id), "workflow_id": str(workflow.id)},
                response_status=201,
            )
            return CreatedCase(
                owner_id=owner.id,
                owner_secret=owner_secret,
                case_id=case.id,
                workflow_id=workflow.id,
            )

    async def analyze_case(
        self,
        *,
        owner_secret: str,
        case_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> WorkflowRecord:
        """Analyze outside transactions, then atomically persist the complete probe."""
        if self._analyzer is None:
            msg = "analyzer is not configured"
            raise AnalyzerNotConfiguredError(msg)
        scope = f"cases:{case_id}:analysis"
        request_fingerprint = _fingerprint({"expected_version": expected_version})
        async with self._sessions() as session, session.begin():
            owner = await self._owner_for_secret(session, owner_secret)
            replay = await self._idempotency_replay(
                session,
                owner_id=owner.id,
                scope=scope,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if replay is not None:
                return await get_owned_workflow(
                    session,
                    workflow_id=UUID(str(replay.response_body["workflow_id"])),
                    owner_id=owner.id,
                )
            row = (
                await session.execute(
                    select(CaseRecord, WorkflowRecord)
                    .join(WorkflowRecord, WorkflowRecord.case_id == CaseRecord.id)
                    .where(CaseRecord.id == case_id, CaseRecord.owner_id == owner.id)
                )
            ).one_or_none()
            if row is None:
                msg = "resource not found"
                raise OwnedResourceNotFoundError(msg)
            case, workflow = row
            await transition_workflow(
                session,
                workflow_id=workflow.id,
                owner_id=owner.id,
                expected_version=expected_version,
                requested_state=WorkflowState.ANALYZING,
                event_key=f"{idempotency_key}:analysis-started",
            )
            analysis_input = AnalysisInput(
                case_id=case.id,
                workflow_id=workflow.id,
                original_a=case.original_a,
                original_b=case.original_b,
                observed_work=case.observed_work,
            )

        # The analyzer and deterministic compiler run with no session, transaction, or lock held.
        try:
            analyzer_result = await self._analyzer.analyze(analysis_input)
            accepted = accept_hypotheses(analyzer_result.mapping)
            from cognisect.compiler import compile_accepted_probe  # noqa: PLC0415

            compiler_result = compile_accepted_probe(
                accepted, analysis_input.original_a, analysis_input.original_b
            )
        except Exception:  # noqa: BLE001 - analyzer/provider boundary is intentionally generic.
            async with self._sessions() as session, session.begin():
                owner = await self._owner_for_secret(session, owner_secret)
                failed = await transition_workflow(
                    session,
                    workflow_id=analysis_input.workflow_id,
                    owner_id=owner.id,
                    expected_version=expected_version + 1,
                    requested_state=WorkflowState.FAILED,
                    event_key=f"{idempotency_key}:analysis-failed",
                )
                self._store_idempotency(
                    session,
                    owner_id=owner.id,
                    scope=scope,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    response_body={"workflow_id": str(failed.id)},
                )
            msg = "analysis failed"
            raise AnalyzerExecutionError(msg) from None
        async with self._sessions() as session, session.begin():
            owner = await self._owner_for_secret(session, owner_secret)
            workflow = await get_owned_workflow(
                session, workflow_id=analysis_input.workflow_id, owner_id=owner.id
            )
            session.add(
                ModelCallRecord(
                    case_id=case_id,
                    workflow_id=workflow.id,
                    model_id=analyzer_result.model_id,
                    model_snapshot=analyzer_result.model_snapshot,
                    request_id=analyzer_result.request_id,
                    status="completed",
                )
            )
            workflow.model_snapshot = analyzer_result.model_snapshot
            workflow.model_request_id = analyzer_result.request_id
            if isinstance(compiler_result, CompilerAbstention):
                updated = await transition_workflow(
                    session,
                    workflow_id=workflow.id,
                    owner_id=owner.id,
                    expected_version=expected_version + 1,
                    requested_state=WorkflowState.ABSTAINED,
                    event_key=f"{idempotency_key}:analysis-abstained",
                )
                self._store_idempotency(
                    session,
                    owner_id=owner.id,
                    scope=scope,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    response_body={"workflow_id": str(workflow.id)},
                )
                return updated

            hypothesis_records: dict[int, AcceptedHypothesisRecord] = {}
            for hypothesis in accepted:
                record = AcceptedHypothesisRecord(
                    workflow_id=workflow.id,
                    template_id=hypothesis.template_id,
                    evidence_refs=list(hypothesis.evidence_refs),
                    description=hypothesis.description,
                    rank=hypothesis.rank,
                    truth_table_hash=hypothesis.truth_table_hash,
                )
                session.add(record)
                hypothesis_records[hypothesis.rank] = record
            await session.flush()
            probe_record = CompiledProbeRecord(
                workflow_id=workflow.id,
                original_a=compiler_result.original_problem.a,
                original_b=compiler_result.original_problem.b,
                chosen_a=compiler_result.chosen_problem.a,
                chosen_b=compiler_result.chosen_problem.b,
                correct_prediction=compiler_result.correct_prediction,
                specification_hash=compiler_result.specification_hash,
                registry_version=compiler_result.registry_version,
                compiler_version=compiler_result.compiler_version,
            )
            session.add(probe_record)
            await session.flush()
            for probe_hypothesis in compiler_result.hypotheses:
                session.add(
                    ProbePredictionRecord(
                        compiled_probe_id=probe_record.id,
                        accepted_hypothesis_id=hypothesis_records[probe_hypothesis.rank].id,
                        template_id=probe_hypothesis.template_id,
                        rank=probe_hypothesis.rank,
                        prediction=probe_hypothesis.prediction,
                    )
                )
            updated = await transition_workflow(
                session,
                workflow_id=workflow.id,
                owner_id=owner.id,
                expected_version=expected_version + 1,
                requested_state=WorkflowState.PROBE_READY,
                event_key=f"{idempotency_key}:probe-ready",
            )
            self._store_idempotency(
                session,
                owner_id=owner.id,
                scope=scope,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                response_body={"workflow_id": str(workflow.id)},
            )
            return updated

    async def approve_probe(
        self,
        *,
        owner_secret: str,
        workflow_id: UUID,
        request: ProbeApprovalRequest,
        idempotency_key: str,
    ) -> ApprovedProbe:
        """Approve a committed probe and create its separately hashed learner token."""
        scope = f"workflows:{workflow_id}:probe-approval"
        request_fingerprint = _fingerprint(request.model_dump(mode="json"))
        async with self._sessions() as session, session.begin():
            owner = await self._owner_for_secret(session, owner_secret)
            replay = await self._idempotency_replay(
                session,
                owner_id=owner.id,
                scope=scope,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if replay is not None:
                workflow = await get_owned_workflow(
                    session, workflow_id=workflow_id, owner_id=owner.id
                )
                token_id = replay.response_body.get("token_id")
                if token_id is None:
                    return ApprovedProbe(token=None, expires_at=None, workflow=workflow)
                token_record = await session.get(LearnerTokenRecord, UUID(str(token_id)))
                if token_record is None:
                    msg = "resource not found"
                    raise OwnedResourceNotFoundError(msg)
                return ApprovedProbe(
                    token=derive_learner_secret(
                        token_record.id,
                        token_record.derivation_nonce,
                        self._learner_pepper,
                    ),
                    expires_at=token_record.expires_at,
                    workflow=workflow,
                )

            workflow = await get_owned_workflow(
                session, workflow_id=workflow_id, owner_id=owner.id
            )
            if not request.approved:
                updated = await transition_workflow(
                    session,
                    workflow_id=workflow_id,
                    owner_id=owner.id,
                    expected_version=request.expected_version,
                    requested_state=WorkflowState.ABSTAINED,
                    event_key=f"{idempotency_key}:probe-rejected",
                )
                self._store_idempotency(
                    session,
                    owner_id=owner.id,
                    scope=scope,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    response_body={"workflow_id": str(workflow_id)},
                )
                return ApprovedProbe(token=None, expires_at=None, workflow=updated)

            probe = await session.scalar(
                select(CompiledProbeRecord).where(CompiledProbeRecord.workflow_id == workflow_id)
            )
            if probe is None:
                msg = "resource not found"
                raise OwnedResourceNotFoundError(msg)
            token_id = uuid4()
            derivation_nonce = generate_derivation_nonce()
            token = derive_learner_secret(
                token_id, derivation_nonce, self._learner_pepper
            )
            expires_at = _now_utc(self._clock) + timedelta(seconds=request.expires_in_seconds)
            session.add(
                LearnerTokenRecord(
                    id=token_id,
                    workflow_id=workflow_id,
                    derivation_nonce=derivation_nonce,
                    token_hash=hash_secret(token, self._learner_pepper, purpose="learner-token"),
                    expires_at=expires_at,
                )
            )
            updated = await transition_workflow(
                session,
                workflow_id=workflow_id,
                owner_id=owner.id,
                expected_version=request.expected_version,
                requested_state=WorkflowState.AWAITING_RESPONSE,
                event_key=f"{idempotency_key}:probe-approved",
            )
            self._store_idempotency(
                session,
                owner_id=owner.id,
                scope=scope,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                response_body={"workflow_id": str(workflow_id), "token_id": str(token_id)},
            )
            return ApprovedProbe(token=token, expires_at=expires_at, workflow=updated)

    async def _learner_token(
        self,
        session: AsyncSession,
        token: str,
        *,
        for_update: bool,
    ) -> LearnerTokenRecord:
        statement = select(LearnerTokenRecord).where(
            LearnerTokenRecord.token_hash
            == hash_secret(token, self._learner_pepper, purpose="learner-token")
        )
        if for_update:
            statement = statement.with_for_update()
        record = await session.scalar(statement)
        if record is None:
            msg = "learner link not found"
            raise LearnerTokenNotFoundError(msg)
        if record.expires_at <= _now_utc(self._clock):
            msg = "learner link expired"
            raise ExpiredLearnerTokenError(msg)
        return record

    async def get_learner_probe(self, token: str) -> LearnerProbeResponse:
        """Read a minimal learner probe without consuming or mutating the token."""
        async with self._sessions() as session:
            token_record = await self._learner_token(session, token, for_update=False)
            probe = await session.scalar(
                select(CompiledProbeRecord).where(
                    CompiledProbeRecord.workflow_id == token_record.workflow_id
                )
            )
            if probe is None:
                msg = "learner link not found"
                raise LearnerTokenNotFoundError(msg)
            return LearnerProbeResponse(
                problem=SignedProblemDTO(a=probe.chosen_a, b=probe.chosen_b),
                answer_constraints=AnswerConstraints(),
                expires_at=token_record.expires_at,
            )

    async def _compiled_probe(
        self, session: AsyncSession, workflow_id: UUID
    ) -> CompiledProbe:
        probe = await session.scalar(
            select(CompiledProbeRecord).where(CompiledProbeRecord.workflow_id == workflow_id)
        )
        if probe is None:
            msg = "learner link not found"
            raise LearnerTokenNotFoundError(msg)
        rows = (
            await session.execute(
                select(AcceptedHypothesisRecord, ProbePredictionRecord)
                .join(
                    ProbePredictionRecord,
                    ProbePredictionRecord.accepted_hypothesis_id == AcceptedHypothesisRecord.id,
                )
                .where(AcceptedHypothesisRecord.workflow_id == workflow_id)
                .order_by(AcceptedHypothesisRecord.rank)
            )
        ).all()
        hypotheses = tuple(
            ProbeHypothesis(
                template_id=hypothesis.template_id,
                evidence_refs=tuple(hypothesis.evidence_refs),
                description=hypothesis.description,
                rank=hypothesis.rank,
                truth_table_hash=hypothesis.truth_table_hash,
                prediction=prediction.prediction,
            )
            for hypothesis, prediction in rows
        )
        return CompiledProbe(
            registry_version=probe.registry_version,
            compiler_version=probe.compiler_version,
            original_problem=SignedProblem(a=probe.original_a, b=probe.original_b),
            chosen_problem=SignedProblem(a=probe.chosen_a, b=probe.chosen_b),
            correct_prediction=probe.correct_prediction,
            hypotheses=hypotheses,
            specification_hash=probe.specification_hash,
        )

    async def submit_learner_response(
        self,
        *,
        token: str,
        request: LearnerSubmitRequest,
        idempotency_key: str,
    ) -> LearnerReceipt:
        """Atomically accept one answer, persist evidence, and reach teacher review."""
        key_hash = hash_payload(idempotency_key.encode())
        request_fingerprint = _fingerprint(request.model_dump(mode="json"))
        async with self._sessions() as session, session.begin():
            token_record = await self._learner_token(session, token, for_update=True)
            existing_response = await session.scalar(
                select(LearnerResponseRecord).where(
                    LearnerResponseRecord.learner_token_id == token_record.id
                )
            )
            if existing_response is not None:
                receipt = await session.scalar(
                    select(LearnerReceiptRecord).where(
                        LearnerReceiptRecord.learner_response_id == existing_response.id
                    )
                )
                if (
                    receipt is not None
                    and receipt.idempotency_key_hash == key_hash
                    and receipt.request_hash == request_fingerprint
                ):
                    return LearnerReceipt(receipt_id=receipt.id, accepted_at=receipt.accepted_at)
                msg = "learner response already recorded"
                raise ReplayConflictError(msg)

            workflow = await session.get(WorkflowRecord, token_record.workflow_id)
            if workflow is None:
                msg = "learner link not found"
                raise LearnerTokenNotFoundError(msg)
            probe = await self._compiled_probe(session, workflow.id)
            accepted_at = _now_utc(self._clock)
            response = LearnerResponseRecord(
                workflow_id=workflow.id,
                learner_token_id=token_record.id,
                answer=request.answer,
                rationale=request.rationale,
                accepted_at=accepted_at,
            )
            session.add(response)
            await session.flush()
            receipt = LearnerReceiptRecord(
                learner_response_id=response.id,
                idempotency_key_hash=key_hash,
                request_hash=request_fingerprint,
                accepted_at=accepted_at,
            )
            session.add(receipt)
            await session.flush()
            transitions = (
                WorkflowState.RESPONSE_RECORDED,
                WorkflowState.RESUME_PENDING,
                WorkflowState.UPDATING,
                WorkflowState.AWAITING_REVIEW,
            )
            version = workflow.version
            for state in transitions:
                await transition_workflow(
                    session,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    expected_version=version,
                    requested_state=state,
                    event_key=f"{idempotency_key}:learner:{state.value}",
                )
                version += 1

            evidence = update_evidence(
                probe, LearnerResponseV1(answer=request.answer, rationale=request.rationale)
            )
            evidence_payload = [
                {"template_id": item.template_id, "rank": item.rank, "status": item.status}
                for item in evidence.evidence
            ]
            session.add(
                GeneratedProposalRecord(
                    workflow_id=workflow.id,
                    generated_text=(
                        "The response is consistent with the persisted probe evidence. "
                        "Teacher review is required before use."
                    ),
                    evidence=evidence_payload,
                )
            )
            return LearnerReceipt(receipt_id=receipt.id, accepted_at=receipt.accepted_at)

    async def get_workflow(self, owner_secret: str, workflow_id: UUID) -> WorkflowRecord:
        """Read one owned teacher workflow or a non-enumerating miss."""
        async with self._sessions() as session:
            owner = await self._owner_for_secret(session, owner_secret)
            return await get_owned_workflow(
                session, workflow_id=workflow_id, owner_id=owner.id
            )

    async def get_workflow_dto(
        self, owner_secret: str, workflow_id: UUID
    ) -> WorkflowResponse:
        """Build the complete teacher DTO while keeping persistence records private."""
        async with self._sessions() as session:
            owner = await self._owner_for_secret(session, owner_secret)
            workflow = await get_owned_workflow(
                session, workflow_id=workflow_id, owner_id=owner.id
            )
            proposal = await session.scalar(
                select(GeneratedProposalRecord).where(
                    GeneratedProposalRecord.workflow_id == workflow_id
                )
            )
            review = await session.scalar(
                select(TeacherReviewRecord).where(TeacherReviewRecord.workflow_id == workflow_id)
            )
            return WorkflowResponse(
                workflow_id=workflow.id,
                case_id=workflow.case_id,
                state=workflow.state.value,
                schema_version=workflow.schema_version,
                registry_version=workflow.registry_version,
                prompt_version=workflow.prompt_version,
                compiler_version=workflow.compiler_version,
                model_snapshot=workflow.model_snapshot,
                model_request_id=workflow.model_request_id,
                created_at=workflow.created_at,
                updated_at=workflow.updated_at,
                version=workflow.version,
                generated_proposal=(proposal.generated_text if proposal is not None else None),
                edited_text=(review.edited_text if review is not None else None),
            )

    async def review_workflow(
        self,
        *,
        owner_secret: str,
        workflow_id: UUID,
        request: ReviewRequest,
        idempotency_key: str,
    ) -> WorkflowRecord:
        """Persist one final review on the only allowed review state."""
        scope = f"workflows:{workflow_id}:review"
        request_fingerprint = _fingerprint(request.model_dump(mode="json"))
        decision_states = {
            "approved": WorkflowState.APPROVED,
            "edited": WorkflowState.EDITED,
            "rejected": WorkflowState.REJECTED,
        }
        async with self._sessions() as session, session.begin():
            owner = await self._owner_for_secret(session, owner_secret)
            replay = await self._idempotency_replay(
                session,
                owner_id=owner.id,
                scope=scope,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if replay is not None:
                return await get_owned_workflow(
                    session, workflow_id=workflow_id, owner_id=owner.id
                )
            session.add(
                TeacherReviewRecord(
                    workflow_id=workflow_id,
                    decision=request.decision,
                    note=request.note,
                    edited_text=request.edited_text,
                )
            )
            updated = await transition_workflow(
                session,
                workflow_id=workflow_id,
                owner_id=owner.id,
                expected_version=request.expected_version,
                requested_state=decision_states[request.decision],
                event_key=f"{idempotency_key}:review:{request.decision}",
            )
            self._store_idempotency(
                session,
                owner_id=owner.id,
                scope=scope,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                response_body={"workflow_id": str(workflow_id)},
            )
            return updated

    async def get_audit(
        self, owner_secret: str, workflow_id: UUID
    ) -> list[AuditEventRecord]:
        """Read every persisted transition in sequence order."""
        async with self._sessions() as session:
            owner = await self._owner_for_secret(session, owner_secret)
            await get_owned_workflow(session, workflow_id=workflow_id, owner_id=owner.id)
            return list(
                (
                    await session.scalars(
                        select(AuditEventRecord)
                        .where(AuditEventRecord.workflow_id == workflow_id)
                        .order_by(AuditEventRecord.sequence)
                    )
                ).all()
            )

    async def delete_workflow(
        self,
        *,
        owner_secret: str,
        workflow_id: UUID,
        idempotency_key: str,
    ) -> None:
        """Hard-delete content and hashes, retaining only an opaque tombstone."""
        if not idempotency_key:
            msg = "idempotency key is required"
            raise ValueError(msg)
        async with self._sessions() as session, session.begin():
            replay_hash = _deletion_replay_hash(
                owner_secret=owner_secret,
                workflow_id=workflow_id,
                idempotency_key=idempotency_key,
                owner_pepper=self._owner_pepper,
            )
            tombstone = await session.scalar(
                select(DeletionAuditTombstoneRecord).where(
                    DeletionAuditTombstoneRecord.workflow_id == workflow_id
                )
            )
            if tombstone is not None:
                if tombstone.replay_hash is not None and secrets_match(
                    tombstone.replay_hash, replay_hash
                ):
                    return
                msg = "resource not found"
                raise OwnedResourceNotFoundError(msg)
            owner = await self._owner_for_secret(session, owner_secret)
            workflow = await get_owned_workflow(
                session, workflow_id=workflow_id, owner_id=owner.id
            )
            session.add(
                DeletionAuditTombstoneRecord(
                    workflow_id=workflow_id,
                    replay_hash=replay_hash,
                )
            )
            case_count = await session.scalar(
                select(func.count(CaseRecord.id)).where(CaseRecord.owner_id == owner.id)
            )
            if case_count == 1:
                await session.delete(owner)
            else:
                case = await session.get(CaseRecord, workflow.case_id)
                if case is not None:
                    await session.delete(case)


class RetentionService:
    """Select and purge cases older than the configured retention window."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        retention_days: int = 30,
    ) -> None:
        """Initialize a Postgres retention selector with a bounded day count."""
        if retention_days < 1:
            msg = "retention_days must be positive"
            raise ValueError(msg)
        self._sessions = session_factory
        self._retention_days = retention_days

    async def select_expired(self, *, now: datetime | None = None) -> list[UUID]:
        """Return stable workflow IDs whose cases exceed retention."""
        reference = (now or utc_now()).astimezone(UTC)
        cutoff = reference - timedelta(days=self._retention_days)
        async with self._sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(WorkflowRecord.id)
                        .join(CaseRecord, CaseRecord.id == WorkflowRecord.case_id)
                        .where(CaseRecord.created_at < cutoff)
                        .order_by(WorkflowRecord.id)
                    )
                ).all()
            )

    async def purge_expired(self, *, now: datetime | None = None) -> int:
        """Hard-delete expired content and preserve content-free tombstones."""
        reference = (now or utc_now()).astimezone(UTC)
        cutoff = reference - timedelta(days=self._retention_days)
        async with self._sessions() as session, session.begin():
            rows = (
                await session.execute(
                    select(WorkflowRecord.id, CaseRecord.id, CaseRecord.owner_id)
                    .join(CaseRecord, CaseRecord.id == WorkflowRecord.case_id)
                    .where(CaseRecord.created_at < cutoff)
                    .order_by(WorkflowRecord.id)
                )
            ).all()
            for workflow_id, _case_id, _owner_id in rows:
                session.add(DeletionAuditTombstoneRecord(workflow_id=workflow_id))
            case_ids = {case_id for _workflow_id, case_id, _owner_id in rows}
            if case_ids:
                await session.execute(delete(CaseRecord).where(CaseRecord.id.in_(case_ids)))
            owner_ids = {owner_id for _workflow_id, _case_id, owner_id in rows}
            for owner_id in owner_ids:
                remaining = await session.scalar(
                    select(func.count(CaseRecord.id)).where(CaseRecord.owner_id == owner_id)
                )
                if remaining == 0:
                    await session.execute(delete(OwnerRecord).where(OwnerRecord.id == owner_id))
            return len(rows)
