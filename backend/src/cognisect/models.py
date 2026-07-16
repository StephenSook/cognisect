"""Strict data contracts for the closed rule registry."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

TemplateId = Literal[
    "add_subtrahend",
    "ignore_subtrahend_sign",
    "absolute_difference",
    "subtract_magnitudes",
    "keep_minuend_sign",
    "negative_magnitude_sum",
]

EvidenceReference = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=80)]
Description = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=280)]
Rank = Annotated[int, Field(strict=True, ge=1, le=4)]

class StrictContractModel(BaseModel):
    """Base configuration shared by public JSON contracts."""

    model_config = ConfigDict(extra="forbid", strict=True)


class RuleInstanceV1(StrictContractModel):
    """One parameter-free hypothesis from the closed v1 registry."""

    template_id: TemplateId
    evidence_refs: Annotated[
        list[EvidenceReference],
        Field(min_length=1, max_length=8, json_schema_extra={"uniqueItems": True}),
    ]
    description: Description
    rank: Rank

    @field_validator("evidence_refs")
    @classmethod
    def evidence_references_are_unique(cls, value: list[str]) -> list[str]:
        """Reject repeated references rather than silently coalescing them."""
        if len(value) != len(set(value)):
            msg = "evidence_refs must contain unique values"
            raise ValueError(msg)
        return value

class RuleMappingV1(StrictContractModel):
    """A bounded, rank-unique collection of registry hypotheses."""

    schema_version: Literal["rule_mapping.v1"]
    hypotheses: Annotated[list[RuleInstanceV1], Field(min_length=2, max_length=4)]

    @model_validator(mode="after")
    def ranks_are_unique(self) -> Self:
        """Reject mappings whose ordering signal is ambiguous."""
        ranks = [hypothesis.rank for hypothesis in self.hypotheses]
        if len(ranks) != len(set(ranks)):
            msg = "hypothesis ranks must be unique"
            raise ValueError(msg)
        return self
