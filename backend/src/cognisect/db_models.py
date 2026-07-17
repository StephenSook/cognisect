"""SQLAlchemy 2 async persistence records for the durable workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from cognisect.interpreter import COMPILER_VERSION, REGISTRY_VERSION
from cognisect.workflow import WorkflowState

SCHEMA_VERSION = "workflow.v1"
PROMPT_VERSION = "analysis_prompt.v2"


def utc_now() -> datetime:
    """Return an aware UTC timestamp for Python-side defaults."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative metadata root."""


class Timestamped:
    """UTC creation/update columns shared by mutable records."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class OwnerRecord(Base):
    """Opaque teacher owner capability hash."""

    __tablename__ = "owners"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    cases: Mapped[list[CaseRecord]] = relationship(back_populates="owner", cascade="all, delete")


class RateLimitWindowRecord(Base):
    """HMAC-keyed fixed-window counter without persisted client identifiers."""

    __tablename__ = "rate_limit_windows"
    __table_args__ = (
        PrimaryKeyConstraint(
            "scope",
            "bucket_hash",
            "window_started_at",
            name="pk_rate_limit_windows",
        ),
        CheckConstraint(
            "char_length(scope) BETWEEN 1 AND 64",
            name="ck_rate_limit_windows_scope",
        ),
        CheckConstraint(
            "bucket_hash ~ '^[0-9a-f]{64}$'",
            name="ck_rate_limit_windows_bucket_hash",
        ),
        CheckConstraint("consumed >= 1", name="ck_rate_limit_windows_consumed"),
        CheckConstraint(
            "expires_at > window_started_at",
            name="ck_rate_limit_windows_expiry",
        ),
        Index("ix_rate_limit_windows_expires_at", "expires_at"),
    )

    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CaseRecord(Timestamped, Base):
    """One de-identified educational case bound to an owner."""

    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint("original_a BETWEEN -12 AND 12", name="ck_cases_original_a"),
        CheckConstraint("original_b BETWEEN -12 AND 12", name="ck_cases_original_b"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("owners.id", ondelete="CASCADE"), index=True
    )
    source_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance_record_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    original_a: Mapped[int] = mapped_column(Integer, nullable=False)
    original_b: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_work: Mapped[str] = mapped_column(Text, nullable=False)
    deidentified_attestation: Mapped[bool] = mapped_column(Boolean, nullable=False)

    owner: Mapped[OwnerRecord] = relationship(back_populates="cases")
    workflows: Mapped[list[WorkflowRecord]] = relationship(
        back_populates="case", cascade="all, delete"
    )


class WorkflowRecord(Timestamped, Base):
    """Versioned workflow aggregate root."""

    __tablename__ = "workflows"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), unique=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("owners.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), unique=True, default=uuid4, nullable=False
    )
    state: Mapped[WorkflowState] = mapped_column(
        Enum(WorkflowState, native_enum=False, length=32),
        default=WorkflowState.CREATED,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), default=SCHEMA_VERSION, nullable=False)
    registry_version: Mapped[str] = mapped_column(
        String(40), default=REGISTRY_VERSION, nullable=False
    )
    prompt_version: Mapped[str] = mapped_column(String(40), default=PROMPT_VERSION, nullable=False)
    compiler_version: Mapped[str] = mapped_column(
        String(48), default=COMPILER_VERSION, nullable=False
    )
    model_snapshot: Mapped[str | None] = mapped_column(String(120))
    model_request_id: Mapped[str | None] = mapped_column(String(160))

    case: Mapped[CaseRecord] = relationship(back_populates="workflows")


class AcceptedHypothesisRecord(Base):
    """One canonical accepted alternative for a workflow."""

    __tablename__ = "accepted_hypotheses"
    __table_args__ = (
        UniqueConstraint("workflow_id", "rank", name="uq_hypothesis_workflow_rank"),
        UniqueConstraint(
            "workflow_id", "truth_table_hash", name="uq_hypothesis_workflow_semantics"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str] = mapped_column(String(280), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    truth_table_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class CompiledProbeRecord(Base):
    """Complete persisted probe specification header."""

    __tablename__ = "compiled_probes"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        unique=True,
    )
    original_a: Mapped[int] = mapped_column(Integer, nullable=False)
    original_b: Mapped[int] = mapped_column(Integer, nullable=False)
    chosen_a: Mapped[int] = mapped_column(Integer, nullable=False)
    chosen_b: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_prediction: Mapped[int] = mapped_column(Integer, nullable=False)
    specification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    registry_version: Mapped[str] = mapped_column(String(40), nullable=False)
    compiler_version: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ProbePredictionRecord(Base):
    """One persisted alternative prediction included in the probe hash."""

    __tablename__ = "probe_predictions"
    __table_args__ = (
        UniqueConstraint("compiled_probe_id", "rank", name="uq_prediction_probe_rank"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    compiled_probe_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("compiled_probes.id", ondelete="CASCADE"), index=True
    )
    accepted_hypothesis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accepted_hypotheses.id", ondelete="CASCADE"),
    )
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    prediction: Mapped[int] = mapped_column(Integer, nullable=False)


class LearnerTokenRecord(Base):
    """Hashed, expiring learner capability; raw tokens never enter persistence."""

    __tablename__ = "learner_tokens"
    __table_args__ = (
        CheckConstraint(
            "octet_length(derivation_nonce) = 32",
            name="ck_learner_token_derivation_nonce_length",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        unique=True,
    )
    derivation_nonce: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class LearnerResponseRecord(Base):
    """Exactly one strict learner answer for a workflow."""

    __tablename__ = "learner_responses"
    __table_args__ = (
        CheckConstraint("answer BETWEEN -10000 AND 10000", name="ck_response_answer"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        unique=True,
    )
    learner_token_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("learner_tokens.id", ondelete="CASCADE"),
        unique=True,
    )
    answer: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class LearnerReceiptRecord(Base):
    """Stable response receipt returned for exact idempotent replay."""

    __tablename__ = "learner_receipts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    learner_response_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("learner_responses.id", ondelete="CASCADE"),
        unique=True,
    )
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class InvalidLearnerCommandRecord(Base):
    """Content-free receipt for one token-authorized invalid-answer command."""

    __tablename__ = "invalid_learner_commands"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        unique=True,
    )
    learner_token_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("learner_tokens.id", ondelete="CASCADE"),
        unique=True,
    )
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class GeneratedProposalRecord(Base):
    """Generated teacher proposal kept separate from any teacher edit."""

    __tablename__ = "generated_proposals"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        unique=True,
    )
    generated_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class TeacherReviewRecord(Base):
    """Final teacher decision, note, and optional separately stored edit."""

    __tablename__ = "teacher_reviews"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        unique=True,
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    edited_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ModelCallRecord(Base):
    """Bounded model-call telemetry without raw prompts or responses."""

    __tablename__ = "model_calls"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "attempt_ordinal",
            name="uq_model_calls_workflow_attempt_ordinal",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    model_snapshot: Mapped[str | None] = mapped_column(String(120))
    requested_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    returned_model_id: Mapped[str | None] = mapped_column(String(120))
    request_id: Mapped[str | None] = mapped_column(String(160))
    attempt_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    repair: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    client_request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_write_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    route_version: Mapped[str] = mapped_column(String(48), nullable=False)
    prompt_cache_key: Mapped[str] = mapped_column(String(120), nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AnalysisStepResultRecord(Base):
    """Validated bounded route artifact staged separately from call telemetry."""

    __tablename__ = "analysis_step_results"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "attempt_ordinal",
            name="uq_analysis_step_results_workflow_attempt_ordinal",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        index=True,
    )
    attempt_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class IdempotencyRecord(Base):
    """Owner-scoped mutation replay record keyed only by hashes."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("owner_id", "scope", "key_hash", name="uq_idempotency_owner_scope_key"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("owners.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(160), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )


class AuditEventRecord(Base):
    """Append-only transition ledger."""

    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_audit_workflow_sequence"),
        UniqueConstraint("workflow_id", "event_key_hash", name="uq_audit_workflow_event_key"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    from_state: Mapped[WorkflowState | None] = mapped_column(
        Enum(WorkflowState, native_enum=False, length=32)
    )
    to_state: Mapped[WorkflowState] = mapped_column(
        Enum(WorkflowState, native_enum=False, length=32), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class DeletionAuditTombstoneRecord(Base):
    """Content-free proof that an opaque workflow identifier was deleted."""

    __tablename__ = "deletion_audit_tombstones"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True, nullable=False)
    replay_hash: Mapped[str | None] = mapped_column(String(64))
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
