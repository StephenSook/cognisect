"""Strict learner-response parsing and deterministic evidence updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, ValidationError

from cognisect.compiler import CompiledProbe, CompilerAbstention, ProbeHypothesis
from cognisect.models import StrictContractModel, TemplateId

EvidenceStatus = Literal["supported", "weakened", "unresolved"]
UpdateStatus = Literal["supported", "weakened", "unresolved", "abstained"]
AbstentionReason = Literal[
    "invalid_response",
    "insufficient_hypotheses",
    "no_separating_probe",
]


class LearnerResponseV1(StrictContractModel):
    """One strict signed integer plus optional review-only rationale."""

    answer: Annotated[int, Field(strict=True, ge=-10_000, le=10_000)]
    rationale: Annotated[
        str,
        StringConstraints(strict=True, max_length=1000),
    ] | None = None


@dataclass(frozen=True, slots=True)
class HypothesisEvidence:
    """The deterministic update for one ordered accepted alternative."""

    template_id: TemplateId
    rank: int
    status: EvidenceStatus


@dataclass(frozen=True, slots=True)
class EvidenceUpdate:
    """A bounded workflow result using only the approved evidence vocabulary."""

    status: UpdateStatus
    evidence: tuple[HypothesisEvidence, ...]
    reason: AbstentionReason | None = None


def parse_learner_response_json(payload: str | bytes | bytearray) -> LearnerResponseV1:
    """Parse strict JSON without bool, float, string, or extra-field coercion."""
    return LearnerResponseV1.model_validate_json(payload)


def _evidence_item(hypothesis: ProbeHypothesis, status: EvidenceStatus) -> HypothesisEvidence:
    return HypothesisEvidence(
        template_id=hypothesis.template_id,
        rank=hypothesis.rank,
        status=status,
    )


def update_evidence(probe: CompiledProbe, response: LearnerResponseV1) -> EvidenceUpdate:
    """Match only the stored predictions; rationale never enters this function."""
    matching_indexes = {
        index
        for index, hypothesis in enumerate(probe.hypotheses)
        if hypothesis.prediction == response.answer
    }

    if len(matching_indexes) == 1:
        evidence = tuple(
            _evidence_item(
                hypothesis,
                "supported" if index in matching_indexes else "weakened",
            )
            for index, hypothesis in enumerate(probe.hypotheses)
        )
        return EvidenceUpdate(status="supported", evidence=evidence)

    if len(matching_indexes) > 1:
        evidence = tuple(
            _evidence_item(
                hypothesis,
                "unresolved" if index in matching_indexes else "weakened",
            )
            for index, hypothesis in enumerate(probe.hypotheses)
        )
        return EvidenceUpdate(status="unresolved", evidence=evidence)

    if response.answer == probe.correct_prediction:
        return EvidenceUpdate(
            status="weakened",
            evidence=tuple(
                _evidence_item(hypothesis, "weakened") for hypothesis in probe.hypotheses
            ),
        )

    return EvidenceUpdate(
        status="unresolved",
        evidence=tuple(_evidence_item(hypothesis, "unresolved") for hypothesis in probe.hypotheses),
    )


def update_evidence_from_json(
    compiler_result: CompiledProbe | CompilerAbstention,
    payload: str | bytes | bytearray,
) -> EvidenceUpdate:
    """Expose abstention for invalid input or a compiler non-release result."""
    if isinstance(compiler_result, CompilerAbstention):
        return EvidenceUpdate(
            status="abstained",
            evidence=(),
            reason=compiler_result.reason,
        )
    try:
        response = parse_learner_response_json(payload)
    except ValidationError:
        return EvidenceUpdate(status="abstained", evidence=(), reason="invalid_response")
    return update_evidence(compiler_result, response)
