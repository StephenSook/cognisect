"""Frozen Task 3 routing identifiers and checked pricing provenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated, Final, Literal, Self

from pydantic import Field, StringConstraints, ValidationError, model_validator

from cognisect.api_models import CreateCaseRequest
from cognisect.models import StrictContractModel

MODEL_IDS: Final = {
    "luna": "gpt-5.6-luna",
    "terra": "gpt-5.6-terra",
    "sol": "gpt-5.6-sol",
}


@dataclass(frozen=True, slots=True)
class PriceTable:
    """Versioned public token prices with explicit source and retrieval date."""

    version: str
    retrieved_on: date
    provenance_urls: tuple[str, ...]
    usd_per_million: dict[str, dict[str, str]]


PRICE_TABLE: Final = PriceTable(
    version="openai-pricing-2026-07-16.v1",
    retrieved_on=date(2026, 7, 16),
    provenance_urls=(
        "https://developers.openai.com/api/docs/models/gpt-5.6-luna",
        "https://developers.openai.com/api/docs/models/gpt-5.6-terra",
        "https://developers.openai.com/api/docs/models/gpt-5.6-sol",
    ),
    usd_per_million={
        "gpt-5.6-luna": {
            "input": "1.00",
            "cached_input": "0.10",
            "output": "6.00",
        },
        "gpt-5.6-terra": {
            "input": "2.50",
            "cached_input": "0.25",
            "output": "15.00",
        },
        "gpt-5.6-sol": {
            "input": "5.00",
            "cached_input": "0.50",
            "output": "30.00",
        },
    },
)

ROUTE_VERSION: Final = "model_route.v1"
LONG_CONTEXT_THRESHOLD_TOKENS: Final = 272_000
MIN_SEPARATING_ALTERNATIVES: Final = 2
_NORMALIZATION_TIERS = frozenset({"authentic", "mixed", "published_exemplar", "custom"})
AMBIGUITY_REVIEW_MARKERS: Final = (
    "ambiguous",
    "multiple possible interpretations",
    "cannot determine which rule",
)
ADVERSARIAL_REVIEW_MARKERS: Final = (
    "ignore previous instructions",
    "skip teacher approval",
    "execute_source",
    "tool_call",
    "<system",
)

EvidenceRef = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=80)]
EvidenceText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=10_000)]


class NormalizedEvidenceSegment(StrictContractModel):
    """One bounded, addressable segment produced by Luna or supplied directly."""

    ref: EvidenceRef
    text: EvidenceText


class NormalizedEvidenceV1(StrictContractModel):
    """Strict intermediate representation used only when extraction is necessary."""

    schema_version: Literal["normalized_evidence.v1"]
    segments: Annotated[list[NormalizedEvidenceSegment], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def refs_are_unique(self) -> Self:
        """Reject ambiguous grounding identifiers before Terra can reference them."""
        refs = [segment.ref for segment in self.segments]
        if len(refs) != len(set(refs)):
            msg = "normalized evidence refs must be unique"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Provider-reported usage; reasoning is a detail of total output tokens."""

    input_tokens: int
    output_tokens: int
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class RouteReviewFlags:
    """Frozen, explainable post-Terra escalation flags."""

    ambiguity: bool
    adversarial: bool


def route_review_flags(case: CreateCaseRequest) -> RouteReviewFlags:
    """Detect only checked-in ambiguity and adversarial-review markers."""
    evidence = case.observed_work.casefold()
    return RouteReviewFlags(
        ambiguity=any(marker in evidence for marker in AMBIGUITY_REVIEW_MARKERS),
        adversarial=any(marker in evidence for marker in ADVERSARIAL_REVIEW_MARKERS),
    )


def calculate_cost_usd(model_id: str, usage: TokenUsage) -> Decimal:
    """Calculate actual token cost without double-billing reasoning tokens."""
    rates = PRICE_TABLE.usd_per_million.get(model_id)
    if rates is None:
        msg = "unknown priced model"
        raise ValueError(msg)
    values = (
        usage.input_tokens,
        usage.output_tokens,
        usage.reasoning_tokens,
        usage.cached_input_tokens,
        usage.cache_write_input_tokens,
    )
    if any(value < 0 for value in values):
        msg = "token counts must be non-negative"
        raise ValueError(msg)
    if usage.reasoning_tokens > usage.output_tokens:
        msg = "reasoning tokens must be included in output tokens"
        raise ValueError(msg)
    detailed_input = usage.cached_input_tokens + usage.cache_write_input_tokens
    if detailed_input > usage.input_tokens:
        msg = "input token details exceed total input tokens"
        raise ValueError(msg)
    uncached_input = usage.input_tokens - detailed_input
    million = Decimal(1_000_000)
    cost = (
        Decimal(uncached_input) * Decimal(rates["input"])
        + Decimal(usage.cached_input_tokens) * Decimal(rates["cached_input"])
        + Decimal(usage.cache_write_input_tokens) * Decimal(rates["input"]) * Decimal("1.25")
        + Decimal(usage.output_tokens) * Decimal(rates["output"])
    ) / million
    return cost.quantize(Decimal("0.000001"))


def initial_route(case: CreateCaseRequest) -> tuple[str, ...]:
    """Choose Luna only when approved source tiers genuinely require extraction."""
    already_structured = False
    try:
        NormalizedEvidenceV1.model_validate_json(case.observed_work)
        already_structured = True
    except (ValidationError, ValueError):
        pass
    if case.source_tier in _NORMALIZATION_TIERS and not already_structured:
        return ("luna", "terra")
    return ("terra",)


def should_use_sol(
    *,
    terra_completed: bool,
    distinct_accepted_alternatives: int,
    ambiguity_flag: bool,
    adversarial_review_flag: bool,
) -> bool:
    """Allow Sol only after Terra and only for one frozen escalation condition."""
    if not terra_completed:
        return False
    return (
        distinct_accepted_alternatives < MIN_SEPARATING_ALTERNATIVES
        or ambiguity_flag
        or adversarial_review_flag
    )
