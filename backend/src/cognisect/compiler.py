"""Deterministic counterexample compiler for bounded signed subtraction."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from cognisect.interpreter import (
    COMPILER_VERSION,
    DOMAIN_VALUES,
    REGISTRY_VERSION,
    AcceptedHypothesis,
    accept_hypotheses,
    correct_result,
)

if TYPE_CHECKING:
    from cognisect.models import RuleMappingV1, TemplateId

MIN_ACCEPTED_HYPOTHESES = 2


@dataclass(frozen=True, slots=True)
class SignedProblem:
    """One ordered operand pair in the compiler domain."""

    a: int
    b: int


@dataclass(frozen=True, slots=True)
class ProbeHypothesis:
    """One ordered accepted hypothesis and its persisted probe prediction."""

    template_id: TemplateId
    evidence_refs: tuple[str, ...]
    description: str
    rank: int
    truth_table_hash: str
    prediction: int


@dataclass(frozen=True, slots=True)
class CompiledProbe:
    """A complete, versioned, reproducibly hashed probe specification."""

    registry_version: str
    compiler_version: str
    original_problem: SignedProblem
    chosen_problem: SignedProblem
    correct_prediction: int
    hypotheses: tuple[ProbeHypothesis, ...]
    specification_hash: str


@dataclass(frozen=True, slots=True)
class CompilerAbstention:
    """A non-release result when the represented rules cannot produce a probe."""

    status: Literal["abstained"]
    reason: Literal["insufficient_hypotheses", "no_separating_probe"]


CompileResult = CompiledProbe | CompilerAbstention


def _table_index(a: int, b: int) -> int:
    return (a - DOMAIN_VALUES[0]) * len(DOMAIN_VALUES) + (b - DOMAIN_VALUES[0])


def _prediction(hypothesis: AcceptedHypothesis, a: int, b: int) -> int:
    if len(hypothesis.truth_table) != len(DOMAIN_VALUES) ** 2:
        msg = "accepted hypotheses require a complete truth table"
        raise ValueError(msg)
    return hypothesis.truth_table[_table_index(a, b)]


def _rank_key(
    hypotheses: tuple[AcceptedHypothesis, ...],
    a: int,
    b: int,
) -> tuple[int, int, int, int, int, int, int]:
    predictions = tuple(_prediction(hypothesis, a, b) for hypothesis in hypotheses)
    distinguished_pairs = sum(
        left != right for left, right in itertools.combinations(predictions, 2)
    )
    return (
        -len(set(predictions)),
        -int(predictions[0] != predictions[1]),
        -distinguished_pairs,
        abs(a) + abs(b),
        abs(correct_result(a, b)),
        a,
        b,
    )


def _specification_payload(
    *,
    versions: tuple[str, str],
    original_problem: SignedProblem,
    chosen_problem: SignedProblem,
    correct_prediction: int,
    hypotheses: tuple[ProbeHypothesis, ...],
) -> dict[str, Any]:
    registry_version, compiler_version = versions
    return {
        "registry_version": registry_version,
        "compiler_version": compiler_version,
        "original_problem": {"a": original_problem.a, "b": original_problem.b},
        "chosen_problem": {"a": chosen_problem.a, "b": chosen_problem.b},
        "correct_prediction": correct_prediction,
        "hypotheses": [
            {
                "template_id": hypothesis.template_id,
                "evidence_refs": list(hypothesis.evidence_refs),
                "description": hypothesis.description,
                "rank": hypothesis.rank,
                "truth_table_hash": hypothesis.truth_table_hash,
                "prediction": hypothesis.prediction,
            }
            for hypothesis in hypotheses
        ],
    }


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def reproduce_probe_hash(probe: CompiledProbe) -> str:
    """Recompute a probe hash from every persisted specification field."""
    return _hash_payload(
        _specification_payload(
            versions=(probe.registry_version, probe.compiler_version),
            original_problem=probe.original_problem,
            chosen_problem=probe.chosen_problem,
            correct_prediction=probe.correct_prediction,
            hypotheses=probe.hypotheses,
        )
    )


def compile_accepted_probe(
    accepted_hypotheses: tuple[AcceptedHypothesis, ...],
    original_a: int,
    original_b: int,
) -> CompileResult:
    """Compile a probe from already canonicalized alternatives."""
    correct_result(original_a, original_b)
    hypotheses = tuple(
        sorted(accepted_hypotheses, key=lambda item: (item.rank, item.template_id))
    )
    if len(hypotheses) < MIN_ACCEPTED_HYPOTHESES:
        return CompilerAbstention(status="abstained", reason="insufficient_hypotheses")

    candidates: list[tuple[tuple[int, int, int, int, int, int, int], int, int]] = []
    for a in DOMAIN_VALUES:
        for b in DOMAIN_VALUES:
            if (a, b) == (original_a, original_b):
                continue
            predictions = {_prediction(hypothesis, a, b) for hypothesis in hypotheses}
            if len(predictions) >= MIN_ACCEPTED_HYPOTHESES:
                candidates.append((_rank_key(hypotheses, a, b), a, b))

    if not candidates:
        return CompilerAbstention(status="abstained", reason="no_separating_probe")

    _, chosen_a, chosen_b = min(candidates)
    original_problem = SignedProblem(a=original_a, b=original_b)
    chosen_problem = SignedProblem(a=chosen_a, b=chosen_b)
    correct_prediction = correct_result(chosen_a, chosen_b)
    probe_hypotheses = tuple(
        ProbeHypothesis(
            template_id=hypothesis.template_id,
            evidence_refs=hypothesis.evidence_refs,
            description=hypothesis.description,
            rank=hypothesis.rank,
            truth_table_hash=hypothesis.truth_table_hash,
            prediction=_prediction(hypothesis, chosen_a, chosen_b),
        )
        for hypothesis in hypotheses
    )
    payload = _specification_payload(
        versions=(REGISTRY_VERSION, COMPILER_VERSION),
        original_problem=original_problem,
        chosen_problem=chosen_problem,
        correct_prediction=correct_prediction,
        hypotheses=probe_hypotheses,
    )
    return CompiledProbe(
        registry_version=REGISTRY_VERSION,
        compiler_version=COMPILER_VERSION,
        original_problem=original_problem,
        chosen_problem=chosen_problem,
        correct_prediction=correct_prediction,
        hypotheses=probe_hypotheses,
        specification_hash=_hash_payload(payload),
    )


def compile_probe(mapping: RuleMappingV1, original_a: int, original_b: int) -> CompileResult:
    """Canonicalize a strict mapping and deterministically select its best probe."""
    return compile_accepted_probe(accept_hypotheses(mapping), original_a, original_b)
