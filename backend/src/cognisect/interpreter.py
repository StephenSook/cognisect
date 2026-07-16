"""Explicit interpreter and semantic canonicalization for rule_registry.v1."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from cognisect.models import RuleInstanceV1, RuleMappingV1, TemplateId

REGISTRY_VERSION = "rule_registry.v1"
COMPILER_VERSION = "counterexample_compiler.v1"
DOMAIN_VALUES = tuple(range(-12, 13))
REGISTRY_TEMPLATE_IDS: tuple[TemplateId, ...] = (
    "add_subtrahend",
    "ignore_subtrahend_sign",
    "absolute_difference",
    "subtract_magnitudes",
    "keep_minuend_sign",
    "negative_magnitude_sum",
)
TruthTable = tuple[int, ...]


@dataclass(frozen=True, slots=True)
class EvaluatedHypothesis:
    """An internal rule instance paired with its complete behavior."""

    instance: RuleInstanceV1
    truth_table: TruthTable


@dataclass(frozen=True, slots=True)
class AcceptedHypothesis:
    """A semantically unique alternative ready for probe compilation."""

    template_id: TemplateId
    evidence_refs: tuple[str, ...]
    description: str
    rank: int
    truth_table_hash: str
    truth_table: TruthTable


def _validate_operand(value: int) -> None:
    if type(value) is not int:  # bool is intentionally not an integer in this contract.
        msg = "operands must be strict integers"
        raise TypeError(msg)
    if value not in DOMAIN_VALUES:
        msg = "operands must be in [-12, 12]"
        raise ValueError(msg)


def _validate_operands(a: int, b: int) -> None:
    _validate_operand(a)
    _validate_operand(b)


def correct_result(a: int, b: int) -> int:
    """Return the signed-integer subtraction reference result."""
    _validate_operands(a, b)
    return a - b


def evaluate_template(template_id: TemplateId, a: int, b: int) -> int:
    """Evaluate one closed template using explicit, parameter-free branches."""
    _validate_operands(a, b)
    if template_id == "add_subtrahend":
        return a + b
    if template_id == "ignore_subtrahend_sign":
        return a - abs(b)
    if template_id == "absolute_difference":
        return abs(abs(a) - abs(b))
    if template_id == "subtract_magnitudes":
        return abs(a) - abs(b)
    if template_id == "keep_minuend_sign":
        sign = -1 if a < 0 else 1
        return sign * abs(abs(a) - abs(b))
    if template_id == "negative_magnitude_sum":
        return -(abs(a) + abs(b))
    msg = "unknown registry template"
    raise ValueError(msg)


def truth_table_for_correct() -> TruthTable:
    """Return the reference behavior in canonical `(a, b)` order."""
    return tuple(a - b for a in DOMAIN_VALUES for b in DOMAIN_VALUES)


def truth_table_for_template(template_id: TemplateId) -> TruthTable:
    """Return all 625 outputs in canonical `(a, b)` order."""
    return tuple(
        evaluate_template(template_id, a, b) for a in DOMAIN_VALUES for b in DOMAIN_VALUES
    )


def canonical_truth_table_hash(truth_table: TruthTable) -> str:
    """Hash a truth table's canonical, whitespace-free JSON encoding."""
    canonical = json.dumps(list(truth_table), separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def evaluate_hypotheses(mapping: RuleMappingV1) -> tuple[EvaluatedHypothesis, ...]:
    """Resolve all model instances through the closed interpreter."""
    return tuple(
        EvaluatedHypothesis(
            instance=hypothesis,
            truth_table=truth_table_for_template(hypothesis.template_id),
        )
        for hypothesis in mapping.hypotheses
    )


def deduplicate_evaluated_hypotheses(
    candidates: Iterable[EvaluatedHypothesis],
) -> tuple[AcceptedHypothesis, ...]:
    """Remove correct-equivalent rules and merge semantic duplicates deterministically."""
    correct_table = truth_table_for_correct()
    semantic_groups: dict[TruthTable, list[RuleInstanceV1]] = defaultdict(list)
    for candidate in candidates:
        if candidate.truth_table != correct_table:
            semantic_groups[candidate.truth_table].append(candidate.instance)

    accepted: list[AcceptedHypothesis] = []
    for truth_table, instances in semantic_groups.items():
        best = min(
            instances,
            key=lambda item: (
                item.rank,
                item.template_id,
                item.description,
                tuple(sorted(item.evidence_refs)),
            ),
        )
        evidence_refs = tuple(
            sorted({reference for instance in instances for reference in instance.evidence_refs})
        )
        accepted.append(
            AcceptedHypothesis(
                template_id=best.template_id,
                evidence_refs=evidence_refs,
                description=best.description,
                rank=best.rank,
                truth_table_hash=canonical_truth_table_hash(truth_table),
                truth_table=truth_table,
            )
        )

    return tuple(sorted(accepted, key=lambda item: (item.rank, item.template_id)))


def accept_hypotheses(mapping: RuleMappingV1) -> tuple[AcceptedHypothesis, ...]:
    """Evaluate, reject, merge, and order a strict rule mapping."""
    return deduplicate_evaluated_hypotheses(evaluate_hypotheses(mapping))
