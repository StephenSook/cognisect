"""Transaction-bounded workflow, token, review, deletion, and retention services."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognisect.api_models import (
    AcceptedHypothesisResponse,
    AnswerConstraints,
    CompiledProbeResponse,
    CompilerCandidateProof,
    CompilerSearchProof,
    CreateCaseRequest,
    EvidenceStatusResponse,
    LearnerProbeResponse,
    LearnerSubmitRequest,
    ProbeApprovalRequest,
    ProbePredictionResponse,
    ReviewDecision,
    ReviewRequest,
    ReviewResultResponse,
    SignedProblemDTO,
    SourceTier,
    WorkflowResponse,
)
from cognisect.compiler import (
    CompiledProbe,
    CompilerAbstention,
    ProbeHypothesis,
    SignedProblem,
    compile_accepted_probe,
)
from cognisect.compiler import (
    CompilerSearchProof as CompilerSearchProofData,
)
from cognisect.config import Settings
from cognisect.db_models import (
    AcceptedHypothesisRecord,
    AuditEventRecord,
    CaseRecord,
    CompiledProbeRecord,
    DeletionAuditTombstoneRecord,
    GeneratedProposalRecord,
    IdempotencyRecord,
    InvalidLearnerCommandRecord,
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
from cognisect.interpreter import (
    AcceptedHypothesis,
    accept_hypotheses,
    canonical_truth_table_hash,
    truth_table_for_template,
)
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

if TYPE_CHECKING:
    from cognisect.models import TemplateId

Clock = Callable[[], datetime]


class ServiceError(RuntimeError):
    """Content-free base service error."""


class ReplayConflictError(ServiceError):
    """A consumed capability or idempotency-key conflict."""


class AnalysisInProgressError(ReplayConflictError):
    """A matching analysis attempt is still inside its bounded provider window."""


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
    source_tier: SourceTier
    original_a: int
    original_b: int
    observed_work: str


AnalyzerAbstentionCause = Literal[
    "refusal",
    "malformed_output",
    "timeout",
    "policy_failure",
    "cost_limit",
    "no_separating_alternatives",
]


@dataclass(frozen=True, slots=True)
class ModelCallTelemetry:
    """Content-free metadata for one bounded official Responses API call."""

    requested_model_id: str
    returned_model_id: str | None
    request_id: str | None
    status: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    cost_usd: Decimal
    prompt_hash: str
    route_version: str
    prompt_cache_key: str


@dataclass(frozen=True, slots=True)
class AnalyzerResult:
    """Bounded structured analyzer output and public model metadata."""

    mapping: RuleMappingV1 | None
    model_id: str
    model_snapshot: str | None = None
    request_id: str | None = None
    model_calls: tuple[ModelCallTelemetry, ...] = ()
    abstention_cause: AnalyzerAbstentionCause | None = None
    proposal_draft: str | None = None
    calls_persisted: bool = False


class Analyzer(Protocol):
    """Injected model analyzer; no implicit fake is permitted."""

    async def analyze(self, case: AnalysisInput) -> AnalyzerResult:
        """Analyze de-identified work and return a strict mapping."""
        ...


class GraphRuntime(Protocol):
    """Durable graph commands used after their corresponding DB command commits."""

    async def start_probe_interrupt(self, workflow_id: UUID, thread_id: UUID) -> object:
        """Start or recover the probe approval interrupt."""
        ...

    async def resume_probe(self, thread_id: UUID, *, approved: bool) -> object:
        """Resume the pending probe interrupt if present."""
        ...

    async def resume_after_response(self, workflow_id: UUID, thread_id: UUID) -> object:
        """Advance or recover a persisted learner response."""
        ...

    async def resume_review(self, thread_id: UUID, *, decision: str) -> object:
        """Resume the pending final review interrupt if present."""
        ...

    async def purge_thread(
        self,
        thread_id: UUID,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        """Purge all durable checkpoints for one thread."""
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


def _reconstruct_accepted_hypotheses(
    records: list[AcceptedHypothesisRecord],
) -> tuple[AcceptedHypothesis, ...]:
    """Rebuild canonical interpreter inputs from the persisted accepted records."""
    reconstructed = []
    try:
        for record in records:
            template_id = cast("TemplateId", record.template_id)
            truth_table = truth_table_for_template(template_id)
            if canonical_truth_table_hash(truth_table) != record.truth_table_hash:
                msg = "persisted compiler proof does not reproduce accepted hypotheses"
                raise ReplayConflictError(msg)
            reconstructed.append(
                AcceptedHypothesis(
                    template_id=template_id,
                    evidence_refs=tuple(record.evidence_refs),
                    description=record.description,
                    rank=record.rank,
                    truth_table_hash=record.truth_table_hash,
                    truth_table=truth_table,
                )
            )
    except ValueError as error:
        msg = "persisted compiler proof does not reproduce accepted hypotheses"
        raise ReplayConflictError(msg) from error
    return tuple(reconstructed)


def _derive_persisted_proof(
    probe: CompiledProbeRecord,
    hypotheses: list[AcceptedHypothesisRecord],
    predictions: list[ProbePredictionRecord],
) -> CompilerSearchProofData:
    """Re-run the compiler and reject any persisted selection/prediction drift."""
    result = compile_accepted_probe(
        _reconstruct_accepted_hypotheses(hypotheses),
        probe.original_a,
        probe.original_b,
    )
    persisted_predictions = tuple(prediction.prediction for prediction in predictions)
    persisted_prediction_specs = tuple(
        (prediction.template_id, prediction.rank, prediction.prediction)
        for prediction in predictions
    )
    reproduced_prediction_specs = (
        tuple((item.template_id, item.rank, item.prediction) for item in result.hypotheses)
        if isinstance(result, CompiledProbe)
        else ()
    )
    if (
        not isinstance(result, CompiledProbe)
        or result.registry_version != probe.registry_version
        or result.compiler_version != probe.compiler_version
        or result.original_problem
        != SignedProblem(a=probe.original_a, b=probe.original_b)
        or result.chosen_problem != SignedProblem(a=probe.chosen_a, b=probe.chosen_b)
        or result.correct_prediction != probe.correct_prediction
        or result.specification_hash != probe.specification_hash
        or reproduced_prediction_specs != persisted_prediction_specs
        or result.proof.top_candidates[0].predictions != persisted_predictions
    ):
        msg = "persisted compiler proof does not reproduce probe selection and predictions"
        raise ReplayConflictError(msg)
    return result.proof


def _proof_response(proof: CompilerSearchProofData) -> CompilerSearchProof:
    """Translate immutable compiler proof values into the strict public DTO."""
    return CompilerSearchProof(
        domain_problem_count=cast("Literal[625]", proof.domain_problem_count),
        eligible_candidate_count=cast("Literal[624]", proof.eligible_candidate_count),
        separating_candidate_count=proof.separating_candidate_count,
        chosen_candidate_rank=cast("Literal[1]", proof.chosen_candidate_rank),
        top_candidates=[
            CompilerCandidateProof(
                problem=SignedProblemDTO(a=candidate.problem.a, b=candidate.problem.b),
                predictions=list(candidate.predictions),
                distinct_output_count=candidate.distinct_output_count,
                top_two_separated=candidate.top_two_separated,
                distinguished_pair_count=candidate.distinguished_pair_count,
                operand_magnitude=candidate.operand_magnitude,
                correct_result_magnitude=candidate.correct_result_magnitude,
                rank=candidate.rank,
            )
            for candidate in proof.top_candidates
        ],
    )


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
        self._graph_runtime: GraphRuntime | None = None

    def attach_graph_runtime(self, runtime: GraphRuntime) -> None:
        """Attach the process-local runtime for durable checkpoint commands."""
        self._graph_runtime = runtime

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

    async def bootstrap_owner(self) -> str:
        """Persist an empty owner capability before any educational mutation."""
        owner_secret = generate_secret()
        async with self._sessions() as session, session.begin():
            session.add(
                OwnerRecord(
                    secret_hash=hash_secret(
                        owner_secret,
                        self._owner_pepper,
                        purpose="owner",
                    )
                )
            )
        return owner_secret

    async def _register_and_lock_owner(
        self,
        session: AsyncSession,
        owner_secret: str,
    ) -> OwnerRecord:
        """Register a pre-established owner once and serialize its first command."""
        secret_hash = hash_secret(owner_secret, self._owner_pepper, purpose="owner")
        for _attempt in range(2):
            await session.execute(
                pg_insert(OwnerRecord)
                .values(secret_hash=secret_hash)
                .on_conflict_do_nothing(index_elements=[OwnerRecord.secret_hash])
            )
            owner = await session.scalar(
                select(OwnerRecord)
                .where(OwnerRecord.secret_hash == secret_hash)
                .with_for_update()
            )
            if owner is not None:
                return owner
        msg = "resource not found"
        raise OwnedResourceNotFoundError(msg)

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
                owner = await self._register_and_lock_owner(session, owner_secret)
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

    async def analyze_case(  # noqa: C901, PLR0912, PLR0915
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
        replayed_workflow: WorkflowRecord | None = None
        analysis_input: AnalysisInput | None = None
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
                replayed_workflow = await get_owned_workflow(
                    session,
                    workflow_id=UUID(str(replay.response_body["workflow_id"])),
                    owner_id=owner.id,
                )
            else:
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
                if (
                    workflow.state == WorkflowState.ANALYZING
                    and workflow.version == expected_version + 1
                ):
                    started_event = await session.scalar(
                        select(AuditEventRecord).where(
                            AuditEventRecord.workflow_id == workflow.id,
                            AuditEventRecord.sequence == expected_version + 1,
                            AuditEventRecord.to_state == WorkflowState.ANALYZING,
                        )
                    )
                    expected_event_hash = hash_payload(
                        f"{idempotency_key}:analysis-started".encode()
                    )
                    if (
                        started_event is None
                        or started_event.event_key_hash != expected_event_hash
                    ):
                        msg = "analysis is already in progress"
                        raise ReplayConflictError(msg)
                else:
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
                    source_tier=cast("SourceTier", case.source_tier),
                    original_a=case.original_a,
                    original_b=case.original_b,
                    observed_work=case.observed_work,
                )

        if replayed_workflow is not None:
            if (
                self._graph_runtime is not None
                and replayed_workflow.state == WorkflowState.PROBE_READY
            ):
                await self._graph_runtime.start_probe_interrupt(
                    replayed_workflow.id,
                    replayed_workflow.thread_id,
                )
            return replayed_workflow
        if analysis_input is None:  # pragma: no cover - total branch invariant
            msg = "analysis input was not prepared"
            raise AnalyzerExecutionError(msg)

        # The analyzer and deterministic compiler run with no session, transaction, or lock held.
        try:
            analyzer_result = await self._analyzer.analyze(analysis_input)
            accepted = (
                accept_hypotheses(analyzer_result.mapping)
                if analyzer_result.mapping is not None
                else ()
            )
            if analyzer_result.abstention_cause is None:
                if analyzer_result.mapping is None:
                    msg = "analyzer returned neither a mapping nor an abstention"
                    raise ValueError(msg)  # noqa: TRY301
                compiler_result = compile_accepted_probe(
                    accepted, analysis_input.original_a, analysis_input.original_b
                )
            else:
                compiler_result = None
        except AnalysisInProgressError:
            raise
        except Exception:  # noqa: BLE001 - analyzer/provider boundary is intentionally generic.
            async with self._sessions() as session, session.begin():
                owner = await self._owner_for_secret(session, owner_secret)
                workflow = await session.scalar(
                    select(WorkflowRecord)
                    .where(
                        WorkflowRecord.id == analysis_input.workflow_id,
                        WorkflowRecord.owner_id == owner.id,
                    )
                    .with_for_update()
                )
                if workflow is None:
                    msg = "resource not found"
                    raise OwnedResourceNotFoundError(msg) from None
                replay = await self._idempotency_replay(
                    session,
                    owner_id=owner.id,
                    scope=scope,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if replay is not None:
                    return cast("WorkflowRecord", workflow)
                if not (
                    workflow.state == WorkflowState.ANALYZING
                    and workflow.version == expected_version + 1
                ):
                    msg = "analysis completion conflicts with persisted state"
                    raise ReplayConflictError(msg) from None
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
            workflow = await session.scalar(
                select(WorkflowRecord)
                .where(
                    WorkflowRecord.id == analysis_input.workflow_id,
                    WorkflowRecord.owner_id == owner.id,
                )
                .with_for_update()
            )
            if workflow is None:
                msg = "resource not found"
                raise OwnedResourceNotFoundError(msg)
            replay = await self._idempotency_replay(
                session,
                owner_id=owner.id,
                scope=scope,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if replay is not None:
                return cast("WorkflowRecord", workflow)
            if not (
                workflow.state == WorkflowState.ANALYZING
                and workflow.version == expected_version + 1
            ):
                msg = "analysis completion conflicts with persisted state"
                raise ReplayConflictError(msg)
            if analyzer_result.model_calls and not analyzer_result.calls_persisted:
                for attempt_ordinal, call in enumerate(analyzer_result.model_calls, start=1):
                    session.add(
                        ModelCallRecord(
                            case_id=case_id,
                            workflow_id=workflow.id,
                            model_id=call.requested_model_id,
                            model_snapshot=call.returned_model_id,
                            requested_model_id=call.requested_model_id,
                            returned_model_id=call.returned_model_id,
                            request_id=call.request_id,
                            attempt_ordinal=attempt_ordinal,
                            purpose="legacy",
                            repair=False,
                            client_request_id=str(
                                uuid5(
                                    NAMESPACE_URL,
                                    f"cognisect:{workflow.id}:{attempt_ordinal}:legacy",
                                )
                            ),
                            status=call.status,
                            latency_ms=call.latency_ms,
                            input_tokens=call.input_tokens,
                            output_tokens=call.output_tokens,
                            reasoning_tokens=call.reasoning_tokens,
                            cached_input_tokens=call.cached_input_tokens,
                            cache_write_input_tokens=call.cache_write_input_tokens,
                            cost_usd=call.cost_usd,
                            prompt_hash=call.prompt_hash,
                            route_version=call.route_version,
                            prompt_cache_key=call.prompt_cache_key,
                            finalized_at=utc_now(),
                        )
                    )
            elif not analyzer_result.calls_persisted:
                session.add(
                    ModelCallRecord(
                        case_id=case_id,
                        workflow_id=workflow.id,
                        model_id=analyzer_result.model_id,
                        model_snapshot=analyzer_result.model_snapshot,
                        requested_model_id=analyzer_result.model_id,
                        returned_model_id=analyzer_result.model_snapshot,
                        request_id=analyzer_result.request_id,
                        attempt_ordinal=1,
                        purpose="legacy",
                        repair=False,
                        client_request_id=str(
                            uuid5(
                                NAMESPACE_URL,
                                f"cognisect:{workflow.id}:1:legacy",
                            )
                        ),
                        status="completed",
                        latency_ms=0,
                        input_tokens=0,
                        output_tokens=0,
                        reasoning_tokens=0,
                        cached_input_tokens=0,
                        cache_write_input_tokens=0,
                        prompt_hash="0" * 64,
                        route_version="legacy.task2",
                        prompt_cache_key="legacy.task2",
                        finalized_at=utc_now(),
                    )
                )
            workflow.model_snapshot = analyzer_result.model_snapshot
            workflow.model_request_id = analyzer_result.request_id
            if analyzer_result.abstention_cause is not None:
                updated = await transition_workflow(
                    session,
                    workflow_id=workflow.id,
                    owner_id=owner.id,
                    expected_version=expected_version + 1,
                    requested_state=WorkflowState.ABSTAINED,
                    event_key=f"{idempotency_key}:analysis-abstained:{analyzer_result.abstention_cause}",
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

            compiled_probe = cast("CompiledProbe", compiler_result)
            if analyzer_result.proposal_draft is not None:
                session.add(
                    GeneratedProposalRecord(
                        workflow_id=workflow.id,
                        generated_text=analyzer_result.proposal_draft,
                        evidence=[],
                    )
                )
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
                original_a=compiled_probe.original_problem.a,
                original_b=compiled_probe.original_problem.b,
                chosen_a=compiled_probe.chosen_problem.a,
                chosen_b=compiled_probe.chosen_problem.b,
                correct_prediction=compiled_probe.correct_prediction,
                specification_hash=compiled_probe.specification_hash,
                registry_version=compiled_probe.registry_version,
                compiler_version=compiled_probe.compiler_version,
            )
            session.add(probe_record)
            await session.flush()
            for probe_hypothesis in compiled_probe.hypotheses:
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
        if self._graph_runtime is not None:
            await self._graph_runtime.start_probe_interrupt(updated.id, updated.thread_id)
        return updated

    async def approve_probe(  # noqa: C901, PLR0912, PLR0915
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
        if self._graph_runtime is not None and request.approved:
            gate_workflow: WorkflowRecord | None = None
            async with self._sessions() as session:
                owner = await self._owner_for_secret(session, owner_secret)
                replay = await self._idempotency_replay(
                    session,
                    owner_id=owner.id,
                    scope=scope,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if replay is None:
                    gate_workflow = await get_owned_workflow(
                        session,
                        workflow_id=workflow_id,
                        owner_id=owner.id,
                    )
            if gate_workflow is not None:
                gate = await self._graph_runtime.start_probe_interrupt(
                    gate_workflow.id,
                    gate_workflow.thread_id,
                )
                if not (
                    isinstance(gate, dict)
                    and isinstance(gate.get("__interrupt__"), tuple)
                    and gate["__interrupt__"]
                ):
                    msg = "probe approval gate is not ready"
                    raise ReplayConflictError(msg)
        result: ApprovedProbe
        thread_id: UUID
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
                thread_id = workflow.thread_id
                token_id = replay.response_body.get("token_id")
                if token_id is None:
                    result = ApprovedProbe(token=None, expires_at=None, workflow=workflow)
                else:
                    token_record = await session.get(LearnerTokenRecord, UUID(str(token_id)))
                    if token_record is None:
                        msg = "resource not found"
                        raise OwnedResourceNotFoundError(msg)
                    result = ApprovedProbe(
                        token=derive_learner_secret(
                            token_record.id,
                            token_record.derivation_nonce,
                            self._learner_pepper,
                        ),
                        expires_at=token_record.expires_at,
                        workflow=workflow,
                    )
            else:
                workflow = await get_owned_workflow(
                    session, workflow_id=workflow_id, owner_id=owner.id
                )
                thread_id = workflow.thread_id
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
                    result = ApprovedProbe(token=None, expires_at=None, workflow=updated)
                else:
                    probe = await session.scalar(
                        select(CompiledProbeRecord).where(
                            CompiledProbeRecord.workflow_id == workflow_id
                        )
                    )
                    if probe is None:
                        msg = "resource not found"
                        raise OwnedResourceNotFoundError(msg)
                    token_id = uuid4()
                    derivation_nonce = generate_derivation_nonce()
                    token = derive_learner_secret(token_id, derivation_nonce, self._learner_pepper)
                    expires_at = _now_utc(self._clock) + timedelta(
                        seconds=request.expires_in_seconds
                    )
                    session.add(
                        LearnerTokenRecord(
                            id=token_id,
                            workflow_id=workflow_id,
                            derivation_nonce=derivation_nonce,
                            token_hash=hash_secret(
                                token,
                                self._learner_pepper,
                                purpose="learner-token",
                            ),
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
                        response_body={
                            "workflow_id": str(workflow_id),
                            "token_id": str(token_id),
                        },
                    )
                    result = ApprovedProbe(token=token, expires_at=expires_at, workflow=updated)

        if self._graph_runtime is not None:
            await self._graph_runtime.resume_probe(thread_id, approved=request.approved)
        return result

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
        hypothesis_records = [hypothesis for hypothesis, _prediction in rows]
        prediction_records = [prediction for _hypothesis, prediction in rows]
        proof = _derive_persisted_proof(probe, hypothesis_records, prediction_records)
        return CompiledProbe(
            registry_version=probe.registry_version,
            compiler_version=probe.compiler_version,
            original_problem=SignedProblem(a=probe.original_a, b=probe.original_b),
            chosen_problem=SignedProblem(a=probe.chosen_a, b=probe.chosen_b),
            correct_prediction=probe.correct_prediction,
            hypotheses=hypotheses,
            specification_hash=probe.specification_hash,
            proof=proof,
        )

    async def advance_response_update(self, workflow_id: UUID) -> None:
        """Idempotently advance one persisted answer to teacher-review readiness."""
        async with self._sessions() as session, session.begin():
            workflow = await session.scalar(
                select(WorkflowRecord).where(WorkflowRecord.id == workflow_id).with_for_update()
            )
            if workflow is None:
                msg = "workflow not found"
                raise OwnedResourceNotFoundError(msg)
            if workflow.state == WorkflowState.AWAITING_REVIEW:
                return
            if workflow.state == WorkflowState.RESUME_PENDING:
                workflow = await transition_workflow(
                    session,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    expected_version=workflow.version,
                    requested_state=WorkflowState.UPDATING,
                    event_key=f"graph:{workflow.id}:updating",
                )
            elif workflow.state != WorkflowState.UPDATING:
                msg = "response update is not pending"
                raise ReplayConflictError(msg)

            proposal = await session.scalar(
                select(GeneratedProposalRecord).where(
                    GeneratedProposalRecord.workflow_id == workflow.id
                )
            )
            response = await session.scalar(
                select(LearnerResponseRecord).where(
                    LearnerResponseRecord.workflow_id == workflow.id
                )
            )
            if response is None:
                msg = "learner response not found"
                raise LearnerTokenNotFoundError(msg)
            probe = await self._compiled_probe(session, workflow.id)
            evidence = update_evidence(
                probe,
                LearnerResponseV1(
                    answer=response.answer,
                    rationale=response.rationale,
                ),
            )
            evidence_payload = [
                {
                    "template_id": item.template_id,
                    "rank": item.rank,
                    "status": item.status,
                }
                for item in evidence.evidence
            ]
            if proposal is None:
                session.add(
                    GeneratedProposalRecord(
                        workflow_id=workflow.id,
                        generated_text=(
                            "Deterministic evidence update is ready. "
                            "This is not a model-drafted note; teacher review is required."
                        ),
                        evidence=evidence_payload,
                    )
                )
                await session.flush()
            else:
                proposal.evidence = evidence_payload

            await transition_workflow(
                session,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                expected_version=workflow.version,
                requested_state=WorkflowState.AWAITING_REVIEW,
                event_key=f"graph:{workflow.id}:awaiting-review",
            )

    async def submit_learner_response(
        self,
        *,
        token: str,
        request: LearnerSubmitRequest,
        idempotency_key: str,
    ) -> LearnerReceipt:
        """Persist one answer before resuming its idempotent graph update."""
        key_hash = hash_payload(idempotency_key.encode())
        request_fingerprint = _fingerprint(request.model_dump(mode="json"))
        result: LearnerReceipt
        workflow_id: UUID
        thread_id: UUID
        async with self._sessions() as session, session.begin():
            token_record = await self._learner_token(session, token, for_update=True)
            invalid_command = await session.scalar(
                select(InvalidLearnerCommandRecord).where(
                    InvalidLearnerCommandRecord.learner_token_id == token_record.id
                )
            )
            if invalid_command is not None:
                msg = "learner response already recorded"
                raise ReplayConflictError(msg)
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
                    workflow = await session.get(WorkflowRecord, token_record.workflow_id)
                    if workflow is None:
                        msg = "learner link not found"
                        raise LearnerTokenNotFoundError(msg)
                    workflow_id = workflow.id
                    thread_id = workflow.thread_id
                    result = LearnerReceipt(receipt_id=receipt.id, accepted_at=receipt.accepted_at)
                else:
                    msg = "learner response already recorded"
                    raise ReplayConflictError(msg)
            else:
                workflow = await session.get(WorkflowRecord, token_record.workflow_id)
                if workflow is None:
                    msg = "learner link not found"
                    raise LearnerTokenNotFoundError(msg)
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
                version = workflow.version
                for state in (
                    WorkflowState.RESPONSE_RECORDED,
                    WorkflowState.RESUME_PENDING,
                ):
                    await transition_workflow(
                        session,
                        workflow_id=workflow.id,
                        owner_id=workflow.owner_id,
                        expected_version=version,
                        requested_state=state,
                        event_key=f"{idempotency_key}:learner:{state.value}",
                    )
                    version += 1
                workflow_id = workflow.id
                thread_id = workflow.thread_id
                result = LearnerReceipt(receipt_id=receipt.id, accepted_at=receipt.accepted_at)

        if self._graph_runtime is None:
            await self.advance_response_update(workflow_id)
        else:
            await self._graph_runtime.resume_after_response(workflow_id, thread_id)
        return result

    async def submit_invalid_learner_answer(
        self,
        *,
        token: str,
        idempotency_key: str,
    ) -> LearnerReceipt:
        """Abstain once for an invalid body without accepting or retaining its content."""
        key_hash = hash_payload(idempotency_key.encode())
        async with self._sessions() as session, session.begin():
            token_record = await self._learner_token(session, token, for_update=True)
            existing = await session.scalar(
                select(InvalidLearnerCommandRecord).where(
                    InvalidLearnerCommandRecord.learner_token_id == token_record.id
                )
            )
            if existing is not None:
                if existing.idempotency_key_hash != key_hash:
                    msg = "learner response already recorded"
                    raise ReplayConflictError(msg)
                return LearnerReceipt(
                    receipt_id=existing.id,
                    accepted_at=existing.accepted_at,
                )
            valid_response = await session.scalar(
                select(LearnerResponseRecord).where(
                    LearnerResponseRecord.learner_token_id == token_record.id
                )
            )
            if valid_response is not None:
                msg = "learner response already recorded"
                raise ReplayConflictError(msg)
            workflow = await session.get(WorkflowRecord, token_record.workflow_id)
            if workflow is None:
                msg = "learner link not found"
                raise LearnerTokenNotFoundError(msg)
            accepted_at = _now_utc(self._clock)
            record = InvalidLearnerCommandRecord(
                workflow_id=workflow.id,
                learner_token_id=token_record.id,
                idempotency_key_hash=key_hash,
                accepted_at=accepted_at,
            )
            session.add(record)
            await session.flush()
            await transition_workflow(
                session,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                expected_version=workflow.version,
                requested_state=WorkflowState.ABSTAINED,
                event_key=f"{idempotency_key}:learner:invalid-answer",
            )
            return LearnerReceipt(receipt_id=record.id, accepted_at=accepted_at)

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
            case = await session.get(CaseRecord, workflow.case_id)
            if case is None:
                msg = "resource not found"
                raise OwnedResourceNotFoundError(msg)
            hypotheses = list(
                (
                    await session.scalars(
                        select(AcceptedHypothesisRecord)
                        .where(AcceptedHypothesisRecord.workflow_id == workflow_id)
                        .order_by(AcceptedHypothesisRecord.rank)
                    )
                ).all()
            )
            probe = await session.scalar(
                select(CompiledProbeRecord).where(
                    CompiledProbeRecord.workflow_id == workflow_id
                )
            )
            predictions = (
                list(
                    (
                        await session.scalars(
                            select(ProbePredictionRecord)
                            .where(ProbePredictionRecord.compiled_probe_id == probe.id)
                            .order_by(ProbePredictionRecord.rank)
                        )
                    ).all()
                )
                if probe is not None
                else []
            )
            proof = (
                _derive_persisted_proof(probe, hypotheses, predictions)
                if probe is not None
                else None
            )
            proposal = await session.scalar(
                select(GeneratedProposalRecord).where(
                    GeneratedProposalRecord.workflow_id == workflow_id
                )
            )
            review = await session.scalar(
                select(TeacherReviewRecord).where(TeacherReviewRecord.workflow_id == workflow_id)
            )
            active_token = None
            if workflow.state == WorkflowState.AWAITING_RESPONSE:
                active_token = await session.scalar(
                    select(LearnerTokenRecord).where(
                        LearnerTokenRecord.workflow_id == workflow_id,
                        LearnerTokenRecord.expires_at > _now_utc(self._clock),
                        ~exists(
                            select(LearnerResponseRecord.id).where(
                                LearnerResponseRecord.learner_token_id
                                == LearnerTokenRecord.id
                            )
                        ),
                        ~exists(
                            select(InvalidLearnerCommandRecord.id).where(
                                InvalidLearnerCommandRecord.learner_token_id
                                == LearnerTokenRecord.id
                            )
                        ),
                    )
                )
            learner_response_url = None
            if active_token is not None:
                active_secret = derive_learner_secret(
                    active_token.id,
                    active_token.derivation_nonce,
                    self._learner_pepper,
                )
                learner_response_url = (
                    f"{self._settings.public_app_url}/respond/{active_secret}"
                )
            return WorkflowResponse(
                workflow_id=workflow.id,
                case_id=workflow.case_id,
                source_tier=cast("SourceTier", case.source_tier),
                state=workflow.state.value,
                schema_version=workflow.schema_version,
                registry_version=workflow.registry_version,
                prompt_version=workflow.prompt_version,
                compiler_version=workflow.compiler_version,
                model_snapshot=workflow.model_snapshot,
                model_request_id=workflow.model_request_id,
                learner_response_url=learner_response_url,
                created_at=workflow.created_at,
                updated_at=workflow.updated_at,
                version=workflow.version,
                accepted_hypotheses=[
                    AcceptedHypothesisResponse(
                        template_id=hypothesis.template_id,
                        evidence_refs=hypothesis.evidence_refs,
                        description=hypothesis.description,
                        rank=hypothesis.rank,
                        truth_table_hash=hypothesis.truth_table_hash,
                    )
                    for hypothesis in hypotheses
                ],
                compiled_probe=(
                    CompiledProbeResponse(
                        original_problem=SignedProblemDTO(
                            a=probe.original_a,
                            b=probe.original_b,
                        ),
                        problem=SignedProblemDTO(a=probe.chosen_a, b=probe.chosen_b),
                        correct_prediction=probe.correct_prediction,
                        specification_hash=probe.specification_hash,
                        registry_version=probe.registry_version,
                        compiler_version=probe.compiler_version,
                        predictions=[
                            ProbePredictionResponse(
                                template_id=prediction.template_id,
                                rank=prediction.rank,
                                prediction=prediction.prediction,
                            )
                            for prediction in predictions
                        ],
                        proof=_proof_response(proof),
                    )
                    if probe is not None and proof is not None
                    else None
                ),
                deterministic_evidence=[
                    EvidenceStatusResponse.model_validate(item)
                    for item in (proposal.evidence if proposal is not None else [])
                ],
                review_result=(
                    ReviewResultResponse(
                        decision=cast("ReviewDecision", review.decision),
                        note=review.note,
                        edited_text=review.edited_text,
                        created_at=review.created_at,
                    )
                    if review is not None
                    else None
                ),
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
            "abstained": WorkflowState.ABSTAINED,
        }
        updated: WorkflowRecord
        thread_id: UUID
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
                updated = await get_owned_workflow(
                    session, workflow_id=workflow_id, owner_id=owner.id
                )
                thread_id = updated.thread_id
            else:
                workflow = await get_owned_workflow(
                    session, workflow_id=workflow_id, owner_id=owner.id
                )
                thread_id = workflow.thread_id
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

        if self._graph_runtime is not None:
            await self._graph_runtime.resume_review(thread_id, decision=request.decision)
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
        replay_hash = _deletion_replay_hash(
            owner_secret=owner_secret,
            workflow_id=workflow_id,
            idempotency_key=idempotency_key,
            owner_pepper=self._owner_pepper,
        )

        async with self._sessions() as session, session.begin():
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
            if self._graph_runtime is not None:
                await self._graph_runtime.purge_thread(
                    workflow.thread_id,
                    session=session,
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
        graph_runtime: GraphRuntime | None = None,
    ) -> None:
        """Initialize a Postgres retention selector with a bounded day count."""
        if retention_days < 1:
            msg = "retention_days must be positive"
            raise ValueError(msg)
        self._sessions = session_factory
        self._retention_days = retention_days
        self._graph_runtime = graph_runtime

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
                    select(
                        WorkflowRecord.id,
                        WorkflowRecord.thread_id,
                        CaseRecord.id,
                        CaseRecord.owner_id,
                    )
                    .join(CaseRecord, CaseRecord.id == WorkflowRecord.case_id)
                    .where(CaseRecord.created_at < cutoff)
                    .order_by(WorkflowRecord.id)
                )
            ).all()
            for workflow_id, thread_id, _case_id, _owner_id in rows:
                if self._graph_runtime is not None:
                    await self._graph_runtime.purge_thread(
                        thread_id,
                        session=session,
                    )
                session.add(DeletionAuditTombstoneRecord(workflow_id=workflow_id))
            case_ids = {case_id for _workflow_id, _thread_id, case_id, _owner_id in rows}
            if case_ids:
                await session.execute(delete(CaseRecord).where(CaseRecord.id.in_(case_ids)))
            owner_ids = {owner_id for _workflow_id, _thread_id, _case_id, owner_id in rows}
            for owner_id in owner_ids:
                remaining = await session.scalar(
                    select(func.count(CaseRecord.id)).where(CaseRecord.owner_id == owner_id)
                )
                if remaining == 0:
                    await session.execute(delete(OwnerRecord).where(OwnerRecord.id == owner_id))
            stale_empty_owner_ids = list(
                (
                    await session.scalars(
                        select(OwnerRecord.id)
                        .where(
                            OwnerRecord.created_at < cutoff,
                            ~exists(
                                select(CaseRecord.id).where(
                                    CaseRecord.owner_id == OwnerRecord.id
                                )
                            ),
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            if stale_empty_owner_ids:
                await session.execute(
                    delete(OwnerRecord).where(
                        OwnerRecord.id.in_(stale_empty_owner_ids),
                        ~exists(
                            select(CaseRecord.id).where(
                                CaseRecord.owner_id == OwnerRecord.id
                            )
                        ),
                    )
                )
            return len(rows)
