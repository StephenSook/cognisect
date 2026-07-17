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
class CompilerCandidateProof:
    """One separating candidate with every deterministic ranking component."""

    problem: SignedProblem
    predictions: tuple[int, ...]
    distinct_output_count: int
    top_two_separated: bool
    distinguished_pair_count: int
    operand_magnitude: int
    correct_result_magnitude: int
    rank: int


@dataclass(frozen=True, slots=True)
class CompilerSearchProof:
    """Bounded-domain search counts and the deterministic top-ranked candidates."""

    domain_problem_count: int
    eligible_candidate_count: int
    separating_candidate_count: int
    chosen_candidate_rank: int
    top_candidates: tuple[CompilerCandidateProof, ...]


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
    proof: CompilerSearchProof


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
    return _rank_components(predictions, a, b)


def _rank_components(
    predictions: tuple[int, ...], a: int, b: int
) -> tuple[int, int, int, int, int, int, int]:
    """Return the frozen lexicographic ranking tuple for computed predictions."""
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


def _rank_candidates(
    hypotheses: tuple[AcceptedHypothesis, ...],
    original_a: int,
    original_b: int,
) -> CompilerSearchProof | None:
    """Rank the entire eligible domain once and retain an inspectable proof."""
    ranked: list[
        tuple[
            tuple[int, int, int, int, int, int, int],
            SignedProblem,
            tuple[int, ...],
        ]
    ] = []
    for a in DOMAIN_VALUES:
        for b in DOMAIN_VALUES:
            if (a, b) == (original_a, original_b):
                continue
            predictions = tuple(_prediction(hypothesis, a, b) for hypothesis in hypotheses)
            if len(set(predictions)) < MIN_ACCEPTED_HYPOTHESES:
                continue
            ranked.append(
                (
                    _rank_components(predictions, a, b),
                    SignedProblem(a=a, b=b),
                    predictions,
                )
            )

    ranked.sort(key=lambda item: item[0])
    if not ranked:
        return None

    top_candidates = tuple(
        CompilerCandidateProof(
            problem=problem,
            predictions=predictions,
            distinct_output_count=-rank_key[0],
            top_two_separated=bool(-rank_key[1]),
            distinguished_pair_count=-rank_key[2],
            operand_magnitude=rank_key[3],
            correct_result_magnitude=rank_key[4],
            rank=rank,
        )
        for rank, (rank_key, problem, predictions) in enumerate(ranked[:5], start=1)
    )
    return CompilerSearchProof(
        domain_problem_count=len(DOMAIN_VALUES) ** 2,
        eligible_candidate_count=(len(DOMAIN_VALUES) ** 2) - 1,
        separating_candidate_count=len(ranked),
        chosen_candidate_rank=1,
        top_candidates=top_candidates,
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

    proof = _rank_candidates(hypotheses, original_a, original_b)
    if proof is None:
        return CompilerAbstention(status="abstained", reason="no_separating_probe")

    chosen_candidate = proof.top_candidates[0]
    chosen_a = chosen_candidate.problem.a
    chosen_b = chosen_candidate.problem.b
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
            prediction=prediction,
        )
        for hypothesis, prediction in zip(
            hypotheses, chosen_candidate.predictions, strict=True
        )
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
        proof=proof,
    )


def compile_probe(mapping: RuleMappingV1, original_a: int, original_b: int) -> CompileResult:
    """Canonicalize a strict mapping and deterministically select its best probe."""
    return compile_accepted_probe(accept_hypotheses(mapping), original_a, original_b)
