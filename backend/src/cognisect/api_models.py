"""Strict request and response DTOs for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from cognisect.models import StrictContractModel

SourceTier = Literal[
    "authentic",
    "synthetic",
    "mixed",
    "published_exemplar",
    "educator_authored",
    "custom",
]
NonEmptyText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=10_000)]


class SignedProblemDTO(StrictContractModel):
    """One signed-subtraction problem in the frozen compiler domain."""

    a: Annotated[int, Field(strict=True, ge=-12, le=12)]
    b: Annotated[int, Field(strict=True, ge=-12, le=12)]


class CreateCaseRequest(StrictContractModel):
    """A de-identified teacher case without learner identity fields."""

    source_tier: SourceTier
    problem: SignedProblemDTO
    observed_work: NonEmptyText
    deidentified_attestation: bool = False

    @model_validator(mode="after")
    def custom_content_is_attested(self) -> Self:
        """Require an affirmative de-identification attestation for custom content."""
        if self.source_tier == "custom" and self.deidentified_attestation is not True:
            msg = "custom cases require deidentified_attestation=true"
            raise ValueError(msg)
        return self


class CreateCaseResponse(StrictContractModel):
    """Opaque identifiers for the newly owned case and workflow."""

    case_id: UUID
    workflow_id: UUID


class AnalysisRequest(StrictContractModel):
    """CAS input for an analysis command."""

    expected_version: Annotated[int, Field(strict=True, ge=0)] = 0


class ProbeApprovalRequest(StrictContractModel):
    """Teacher decision at the first workflow interrupt."""

    expected_version: Annotated[int, Field(strict=True, ge=0)]
    approved: bool
    expires_in_seconds: Annotated[int, Field(strict=True, ge=60, le=604_800)] = 86_400


class LearnerTokenResponse(StrictContractModel):
    """Teacher decision result with a capability only when the probe is approved."""

    response_url: str | None
    expires_at: datetime | None
    workflow: WorkflowResponse


class AnswerConstraints(StrictContractModel):
    """Strict numeric bounds disclosed to a learner."""

    minimum: Literal[-10_000] = -10_000
    maximum: Literal[10_000] = 10_000


class LearnerProbeResponse(StrictContractModel):
    """Deliberately minimal learner-facing DTO."""

    problem: SignedProblemDTO
    answer_constraints: AnswerConstraints
    expires_at: datetime
    instructions: Literal["Submit one signed integer."] = "Submit one signed integer."


class LearnerSubmitRequest(StrictContractModel):
    """Strict one-answer learner submission."""

    answer: Annotated[int, Field(strict=True, ge=-10_000, le=10_000)]
    rationale: Annotated[str, StringConstraints(strict=True, max_length=1_000)] | None = None


class LearnerReceiptResponse(StrictContractModel):
    """Content-minimal receipt for the accepted response."""

    receipt_id: UUID
    accepted_at: datetime


class ReviewRequest(StrictContractModel):
    """Teacher decision at the final workflow interrupt."""

    expected_version: Annotated[int, Field(strict=True, ge=0)]
    decision: Literal["approved", "edited", "rejected", "abstained"]
    note: Annotated[str, StringConstraints(strict=True, max_length=4_000)] | None = None
    edited_text: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=8_000)
    ] | None = None

    @model_validator(mode="after")
    def decision_fields_are_consistent(self) -> Self:
        """Keep approved/edited content impossible on non-editing paths."""
        if self.decision in {"approved", "edited"} and not (self.note and self.note.strip()):
            msg = "approved and edited reviews require a non-empty note"
            raise ValueError(msg)
        if self.decision == "edited" and not (self.edited_text and self.edited_text.strip()):
            msg = "edited reviews require edited_text"
            raise ValueError(msg)
        if self.decision != "edited" and self.edited_text is not None:
            msg = "edited_text is allowed only for edited reviews"
            raise ValueError(msg)
        return self


EvidenceStatus = Literal["supported", "weakened", "unresolved", "abstained"]
ReviewDecision = Literal["approved", "edited", "rejected", "abstained"]


class AcceptedHypothesisResponse(StrictContractModel):
    """One persisted teacher-visible accepted hypothesis."""

    template_id: str
    evidence_refs: list[str]
    description: str
    rank: int
    truth_table_hash: str


class ProbePredictionResponse(StrictContractModel):
    """One persisted alternative prediction committed with the probe."""

    template_id: str
    rank: int
    prediction: int


class CompiledProbeResponse(StrictContractModel):
    """The persisted deterministic probe specification shown only to teachers."""

    original_problem: SignedProblemDTO
    problem: SignedProblemDTO
    correct_prediction: int
    specification_hash: str
    registry_version: str
    compiler_version: str
    predictions: list[ProbePredictionResponse]


class EvidenceStatusResponse(StrictContractModel):
    """One deterministic status from the closed evidence vocabulary."""

    template_id: str
    rank: int
    status: EvidenceStatus


class ReviewResultResponse(StrictContractModel):
    """The persisted final teacher decision and separately stored edit."""

    decision: ReviewDecision
    note: str | None
    edited_text: str | None
    created_at: datetime


class WorkflowResponse(StrictContractModel):
    """Teacher-facing workflow snapshot with reproducibility metadata."""

    workflow_id: UUID
    case_id: UUID
    source_tier: SourceTier
    state: str
    schema_version: str
    registry_version: str
    prompt_version: str
    compiler_version: str
    model_snapshot: str | None
    model_request_id: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    accepted_hypotheses: list[AcceptedHypothesisResponse]
    compiled_probe: CompiledProbeResponse | None
    deterministic_evidence: list[EvidenceStatusResponse]
    review_result: ReviewResultResponse | None
    generated_proposal: str | None = None
    edited_text: str | None = None


class AuditEventResponse(StrictContractModel):
    """One append-only transition event."""

    sequence: int
    from_state: str | None
    to_state: str
    version: int
    occurred_at: datetime


class AuditResponse(StrictContractModel):
    """Complete transition readback for one owned workflow."""

    workflow_id: UUID
    events: list[AuditEventResponse]


class VersionResponse(StrictContractModel):
    """Public build and deterministic-contract versions."""

    version: str
    schema_version: str
    registry_version: str
    compiler_version: str


LearnerTokenResponse.model_rebuild()
