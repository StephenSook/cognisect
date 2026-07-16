"""Durable, content-bounded analysis attempt planning and completion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognisect.db_models import (
    AnalysisStepResultRecord,
    ModelCallRecord,
    utc_now,
)
from cognisect.services import AnalysisInProgressError, ModelCallTelemetry

AttemptPurpose = Literal["luna", "terra", "sol"]
AttemptAction = Literal["dispatch", "recovered", "stale"]
ATTEMPT_GRACE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class ModelAttemptPlan:
    """Content-free stable identity and routing metadata for one logical attempt."""

    case_id: UUID
    workflow_id: UUID
    attempt_ordinal: int
    purpose: AttemptPurpose
    repair: bool
    requested_model_id: str
    prompt_hash: str
    route_version: str
    prompt_cache_key: str


@dataclass(frozen=True, slots=True)
class AttemptDecision:
    """Plan outcome, optionally carrying a previously validated route artifact."""

    action: AttemptAction
    client_request_id: str
    telemetry: ModelCallTelemetry | None = None
    artifact: dict[str, object] | BaseModel | None = None


class AttemptJournal(Protocol):
    """Short-transaction attempt journal used around every provider dispatch."""

    persists_attempts: bool

    async def plan(self, plan: ModelAttemptPlan) -> AttemptDecision:
        """Persist or recover one immutable attempt plan."""
        ...

    async def finalize(
        self,
        plan: ModelAttemptPlan,
        telemetry: ModelCallTelemetry,
        artifact: BaseModel | None,
    ) -> None:
        """Finalize one planned attempt and optionally stage its valid artifact."""
        ...


def stable_client_request_id(plan: ModelAttemptPlan) -> str:
    """Derive one correlation ID per workflow route attempt; it is not idempotency."""
    return str(
        uuid5(
            NAMESPACE_URL,
            f"cognisect:{plan.workflow_id}:{plan.attempt_ordinal}:{plan.route_version}",
        )
    )


class NullAttemptJournal:
    """Non-durable journal used only by explicitly injected analyzers/tests."""

    persists_attempts = False

    async def plan(self, plan: ModelAttemptPlan) -> AttemptDecision:
        """Allow a non-durable dispatch with a stable correlation ID."""
        return AttemptDecision(
            action="dispatch",
            client_request_id=stable_client_request_id(plan),
        )

    async def finalize(
        self,
        plan: ModelAttemptPlan,
        telemetry: ModelCallTelemetry,
        artifact: BaseModel | None,
    ) -> None:
        """Discard non-durable completion metadata."""
        del plan, telemetry, artifact


def _telemetry(record: ModelCallRecord) -> ModelCallTelemetry:
    return ModelCallTelemetry(
        requested_model_id=record.requested_model_id,
        returned_model_id=record.returned_model_id,
        request_id=record.request_id,
        status=record.status,
        latency_ms=record.latency_ms,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        reasoning_tokens=record.reasoning_tokens,
        cached_input_tokens=record.cached_input_tokens,
        cache_write_input_tokens=record.cache_write_input_tokens,
        cost_usd=Decimal(record.cost_usd or 0),
        prompt_hash=record.prompt_hash,
        route_version=record.route_version,
        prompt_cache_key=record.prompt_cache_key,
    )


def _plan_matches(
    record: ModelCallRecord,
    plan: ModelAttemptPlan,
    client_request_id: str,
) -> bool:
    """Fail closed if replay tries to reinterpret an immutable attempt ordinal."""
    return (
        record.case_id == plan.case_id
        and record.workflow_id == plan.workflow_id
        and record.attempt_ordinal == plan.attempt_ordinal
        and record.purpose == plan.purpose
        and record.repair == plan.repair
        and record.requested_model_id == plan.requested_model_id
        and record.prompt_hash == plan.prompt_hash
        and record.route_version == plan.route_version
        and record.prompt_cache_key == plan.prompt_cache_key
        and record.client_request_id == client_request_id
    )


class PostgresAttemptJournal:
    """Persist attempt intent and validated artifacts in isolated transactions."""

    persists_attempts = True

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        active_window_seconds: float = 35.0,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Bind the journal to short-lived Postgres sessions."""
        if active_window_seconds <= 0:
            msg = "active attempt window must be positive"
            raise ValueError(msg)
        self._sessions = sessions
        self._active_window = timedelta(seconds=active_window_seconds)
        self._clock = clock

    async def plan(self, plan: ModelAttemptPlan) -> AttemptDecision:
        """Insert intent or recover an exact immutable prior attempt."""
        client_request_id = stable_client_request_id(plan)
        async with self._sessions() as session, session.begin():
            statement = (
                pg_insert(ModelCallRecord)
                .values(
                    id=uuid4(),
                    case_id=plan.case_id,
                    workflow_id=plan.workflow_id,
                    model_id=plan.requested_model_id,
                    model_snapshot=None,
                    requested_model_id=plan.requested_model_id,
                    returned_model_id=None,
                    request_id=None,
                    attempt_ordinal=plan.attempt_ordinal,
                    purpose=plan.purpose,
                    repair=plan.repair,
                    client_request_id=client_request_id,
                    status="planned",
                    latency_ms=0,
                    input_tokens=0,
                    output_tokens=0,
                    reasoning_tokens=0,
                    cached_input_tokens=0,
                    cache_write_input_tokens=0,
                    cost_usd=Decimal(),
                    prompt_hash=plan.prompt_hash,
                    route_version=plan.route_version,
                    prompt_cache_key=plan.prompt_cache_key,
                    created_at=utc_now(),
                    finalized_at=None,
                )
                .on_conflict_do_nothing(
                    constraint="uq_model_calls_workflow_attempt_ordinal"
                )
                .returning(ModelCallRecord.id)
            )
            inserted = (await session.execute(statement)).scalar_one_or_none()
            record = await session.scalar(
                select(ModelCallRecord).where(
                    ModelCallRecord.workflow_id == plan.workflow_id,
                    ModelCallRecord.attempt_ordinal == plan.attempt_ordinal,
                )
            )
            if record is None:  # pragma: no cover - insert/select atomic invariant
                msg = "attempt plan was not persisted"
                raise RuntimeError(msg)
            if inserted is not None:
                return AttemptDecision(
                    action="dispatch",
                    client_request_id=record.client_request_id,
                )
            if not _plan_matches(record, plan, client_request_id):
                return AttemptDecision(
                    action="stale",
                    client_request_id=record.client_request_id,
                    telemetry=_telemetry(record),
                )
            if (
                record.status == "planned"
                and record.created_at >= self._clock() - self._active_window
            ):
                msg = "analysis provider attempt is still active"
                raise AnalysisInProgressError(msg)
            artifact = await session.scalar(
                select(AnalysisStepResultRecord).where(
                    AnalysisStepResultRecord.workflow_id == plan.workflow_id,
                    AnalysisStepResultRecord.attempt_ordinal == plan.attempt_ordinal,
                )
            )
            return AttemptDecision(
                action="stale" if record.status == "planned" else "recovered",
                client_request_id=record.client_request_id,
                telemetry=_telemetry(record),
                artifact=artifact.payload if artifact is not None else None,
            )

    async def finalize(
        self,
        plan: ModelAttemptPlan,
        telemetry: ModelCallTelemetry,
        artifact: BaseModel | None,
    ) -> None:
        """Finalize telemetry and artifact atomically in a short transaction."""
        async with self._sessions() as session, session.begin():
            record = await session.scalar(
                select(ModelCallRecord)
                .where(
                    ModelCallRecord.workflow_id == plan.workflow_id,
                    ModelCallRecord.attempt_ordinal == plan.attempt_ordinal,
                )
                .with_for_update()
            )
            if record is None:
                msg = "attempt plan is missing"
                raise RuntimeError(msg)
            if record.status != "planned":
                return
            record.model_snapshot = telemetry.returned_model_id
            record.returned_model_id = telemetry.returned_model_id
            record.request_id = telemetry.request_id
            record.status = telemetry.status
            record.latency_ms = telemetry.latency_ms
            record.input_tokens = telemetry.input_tokens
            record.output_tokens = telemetry.output_tokens
            record.reasoning_tokens = telemetry.reasoning_tokens
            record.cached_input_tokens = telemetry.cached_input_tokens
            record.cache_write_input_tokens = telemetry.cache_write_input_tokens
            record.cost_usd = telemetry.cost_usd
            record.finalized_at = utc_now()
            if artifact is not None:
                schema_version = getattr(artifact, "schema_version", artifact.__class__.__name__)
                session.add(
                    AnalysisStepResultRecord(
                        workflow_id=plan.workflow_id,
                        attempt_ordinal=plan.attempt_ordinal,
                        purpose=plan.purpose,
                        schema_version=str(schema_version),
                        payload=artifact.model_dump(mode="json"),
                    )
                )
