"""Deterministic counterexample compiler tests."""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
from dataclasses import replace
from inspect import Parameter, signature
from typing import cast

from hypothesis import given
from hypothesis import strategies as st

import cognisect.compiler as compiler_module
from cognisect.compiler import (
    CompiledProbe,
    CompilerAbstention,
    _rank_key,
    compile_accepted_probe,
    compile_probe,
    reproduce_probe_hash,
)
from cognisect.interpreter import (
    COMPILER_VERSION,
    DOMAIN_VALUES,
    REGISTRY_VERSION,
    AcceptedHypothesis,
    EvaluatedHypothesis,
    canonical_truth_table_hash,
    deduplicate_evaluated_hypotheses,
    truth_table_for_correct,
)
from cognisect.models import RuleInstanceV1, RuleMappingV1, TemplateId
from oracle import OracleTemplateId, oracle_result

ALL_TEMPLATE_IDS: tuple[TemplateId, ...] = (
    "add_subtrahend",
    "ignore_subtrahend_sign",
    "absolute_difference",
    "subtract_magnitudes",
    "keep_minuend_sign",
    "negative_magnitude_sum",
)
TEMPLATE_LISTS = st.lists(
    st.sampled_from(ALL_TEMPLATE_IDS), min_size=2, max_size=4, unique=True
)


def _mapping(template_ids: list[TemplateId] | tuple[TemplateId, ...]) -> RuleMappingV1:
    return RuleMappingV1(
        schema_version="rule_mapping.v1",
        hypotheses=[
            RuleInstanceV1(
                template_id=template_id,
                evidence_refs=[f"work.{rank}"],
                description=f"Alternative {rank}: {template_id}",
                rank=rank,
            )
            for rank, template_id in enumerate(template_ids, start=1)
        ],
    )


def _independent_best_probe(
    template_ids: tuple[TemplateId, ...], original: tuple[int, int]
) -> tuple[int, int]:
    oracle_ids = tuple(cast("OracleTemplateId", item) for item in template_ids)
    ranked: list[tuple[tuple[int, int, int, int, int, int, int], tuple[int, int]]] = []
    for a in DOMAIN_VALUES:
        for b in DOMAIN_VALUES:
            if (a, b) == original:
                continue
            predictions = tuple(oracle_result(item, a, b) for item in oracle_ids)
            if len(set(predictions)) < 2:
                continue
            distinguished_pairs = sum(
                left != right for left, right in itertools.combinations(predictions, 2)
            )
            rank_key = (
                -len(set(predictions)),
                -int(predictions[0] != predictions[1]),
                -distinguished_pairs,
                abs(a) + abs(b),
                abs(a - b),
                a,
                b,
            )
            ranked.append((rank_key, (a, b)))
    return min(ranked)[1]


def _independent_separating_candidates(
    template_ids: tuple[TemplateId, ...], original: tuple[int, int]
) -> list[tuple[tuple[int, int, int, int, int, int, int], tuple[int, int], tuple[int, ...]]]:
    oracle_ids = tuple(cast("OracleTemplateId", item) for item in template_ids)
    ranked = []
    for a in DOMAIN_VALUES:
        for b in DOMAIN_VALUES:
            if (a, b) == original:
                continue
            predictions = tuple(oracle_result(item, a, b) for item in oracle_ids)
            if len(set(predictions)) < 2:
                continue
            distinguished_pairs = sum(
                left != right for left, right in itertools.combinations(predictions, 2)
            )
            rank_key = (
                -len(set(predictions)),
                -int(predictions[0] != predictions[1]),
                -distinguished_pairs,
                abs(a) + abs(b),
                abs(a - b),
                a,
                b,
            )
            ranked.append((rank_key, (a, b), predictions))
    return sorted(ranked)


def _ranking_fixture(
    predictions_by_problem: dict[tuple[int, int], tuple[int, int, int, int]],
) -> tuple[AcceptedHypothesis, ...]:
    instances = _mapping(ALL_TEMPLATE_IDS[:4]).hypotheses
    tables = [[0] * 625 for _ in instances]
    for (a, b), predictions in predictions_by_problem.items():
        index = (a + 12) * 25 + (b + 12)
        for table, prediction in zip(tables, predictions, strict=True):
            table[index] = prediction
    return tuple(
        AcceptedHypothesis(
            template_id=instance.template_id,
            evidence_refs=tuple(instance.evidence_refs),
            description=instance.description,
            rank=instance.rank,
            truth_table_hash=canonical_truth_table_hash(tuple(table)),
            truth_table=tuple(table),
        )
        for instance, table in zip(instances, tables, strict=True)
    )


def _chosen_by_rank(
    hypotheses: tuple[AcceptedHypothesis, ...],
    first: tuple[int, int],
    second: tuple[int, int],
) -> tuple[int, int]:
    return min((first, second), key=lambda problem: _rank_key(hypotheses, *problem))


def test_distinct_output_count_independently_decides_winner() -> None:
    winner = (2, 2)
    loser = (0, 1)
    hypotheses = _ranking_fixture(
        {
            winner: (0, 0, 1, 2),
            loser: (0, 1, 0, 1),
        }
    )

    assert _chosen_by_rank(hypotheses, loser, winner) == winner


def test_top_two_separation_independently_decides_winner() -> None:
    winner = (2, 2)
    loser = (0, 1)
    hypotheses = _ranking_fixture(
        {
            winner: (0, 1, 0, 1),
            loser: (0, 0, 1, 1),
        }
    )

    assert _chosen_by_rank(hypotheses, winner, loser) == winner


def test_distinguished_hypothesis_pairs_independently_decide_winner() -> None:
    winner = (2, 2)
    loser = (0, 1)
    hypotheses = _ranking_fixture(
        {
            winner: (0, 1, 0, 1),
            loser: (0, 1, 1, 1),
        }
    )

    assert _chosen_by_rank(hypotheses, winner, loser) == winner


def test_operand_magnitude_independently_decides_winner() -> None:
    winner = (2, 0)
    loser = (2, 1)
    hypotheses = _ranking_fixture(
        {
            winner: (0, 1, 0, 1),
            loser: (0, 1, 0, 1),
        }
    )

    assert _chosen_by_rank(hypotheses, winner, loser) == winner


def test_correct_result_magnitude_independently_decides_winner() -> None:
    winner = (1, 1)
    loser = (-2, 0)
    hypotheses = _ranking_fixture(
        {
            winner: (0, 1, 0, 1),
            loser: (0, 1, 0, 1),
        }
    )

    assert _chosen_by_rank(hypotheses, winner, loser) == winner


def test_stable_operand_order_independently_decides_winner() -> None:
    winner = (-1, 0)
    loser = (0, -1)
    hypotheses = _ranking_fixture(
        {
            winner: (0, 1, 0, 1),
            loser: (0, 1, 0, 1),
        }
    )

    assert _chosen_by_rank(hypotheses, loser, winner) == winner


def test_compiler_uses_the_exact_rank_tuple_and_excludes_original_problem() -> None:
    template_ids: tuple[TemplateId, ...] = (
        "ignore_subtrahend_sign",
        "add_subtrahend",
        "absolute_difference",
        "negative_magnitude_sum",
    )
    original = (-1, 1)

    result = compile_probe(_mapping(template_ids), *original)

    assert isinstance(result, CompiledProbe)
    assert (result.chosen_problem.a, result.chosen_problem.b) == _independent_best_probe(
        template_ids, original
    )
    assert result.chosen_problem != result.original_problem


def test_compiled_probe_contains_complete_versioned_specification() -> None:
    mapping = _mapping(("add_subtrahend", "subtract_magnitudes", "keep_minuend_sign"))

    result = compile_probe(mapping, 4, -3)

    assert isinstance(result, CompiledProbe)
    assert result.registry_version == REGISTRY_VERSION
    assert result.compiler_version == COMPILER_VERSION
    assert result.original_problem.a == 4
    assert result.original_problem.b == -3
    assert result.correct_prediction == result.chosen_problem.a - result.chosen_problem.b
    assert [item.template_id for item in result.hypotheses] == [
        item.template_id for item in mapping.hypotheses
    ]
    assert all(type(item.prediction) is int for item in result.hypotheses)
    assert len(result.specification_hash) == 64
    assert reproduce_probe_hash(result) == result.specification_hash


def test_compiler_exposes_complete_proof_from_the_selection_ranking_pass() -> None:
    template_ids: tuple[TemplateId, ...] = (
        "ignore_subtrahend_sign",
        "add_subtrahend",
        "absolute_difference",
        "negative_magnitude_sum",
    )
    original = (-1, 1)
    independent = _independent_separating_candidates(template_ids, original)

    result = compile_probe(_mapping(template_ids), *original)

    assert isinstance(result, CompiledProbe)
    assert result.proof.domain_problem_count == 625
    assert result.proof.eligible_candidate_count == 624
    assert result.proof.separating_candidate_count == len(independent)
    assert result.proof.chosen_candidate_rank == 1
    assert 1 <= len(result.proof.top_candidates) <= 5
    assert [candidate.rank for candidate in result.proof.top_candidates] == list(
        range(1, len(result.proof.top_candidates) + 1)
    )
    chosen = result.proof.top_candidates[0]
    assert chosen.problem == result.chosen_problem
    assert chosen.predictions == tuple(item.prediction for item in result.hypotheses)
    assert chosen.distinct_output_count == len(set(chosen.predictions))
    assert chosen.top_two_separated is (chosen.predictions[0] != chosen.predictions[1])
    assert chosen.distinguished_pair_count == sum(
        left != right for left, right in itertools.combinations(chosen.predictions, 2)
    )
    assert chosen.operand_magnitude == abs(chosen.problem.a) + abs(chosen.problem.b)
    assert chosen.correct_result_magnitude == abs(chosen.problem.a - chosen.problem.b)
    assert [
        (
            candidate.problem,
            candidate.predictions,
            candidate.distinct_output_count,
            candidate.top_two_separated,
            candidate.distinguished_pair_count,
            candidate.operand_magnitude,
            candidate.correct_result_magnitude,
            candidate.rank,
        )
        for candidate in result.proof.top_candidates
    ] == [
        (
            compiler_module.SignedProblem(a=problem[0], b=problem[1]),
            predictions,
            -rank_key[0],
            bool(-rank_key[1]),
            -rank_key[2],
            rank_key[3],
            rank_key[4],
            rank,
        )
        for rank, (rank_key, problem, predictions) in enumerate(independent[:5], start=1)
    ]


def test_compiler_reuses_ranking_pass_predictions_for_compiled_hypotheses(
    monkeypatch,
) -> None:
    prediction_calls = 0
    real_prediction = compiler_module._prediction

    def counting_prediction(hypothesis, a, b):
        nonlocal prediction_calls
        prediction_calls += 1
        return real_prediction(hypothesis, a, b)

    monkeypatch.setattr(compiler_module, "_prediction", counting_prediction)

    result = compile_probe(
        _mapping(
            (
                "ignore_subtrahend_sign",
                "add_subtrahend",
                "absolute_difference",
                "negative_magnitude_sum",
            )
        ),
        -1,
        1,
    )

    assert isinstance(result, CompiledProbe)
    assert prediction_calls == (
        result.proof.eligible_candidate_count * len(result.hypotheses)
    )


def test_compiled_probe_requires_a_search_proof() -> None:
    assert signature(CompiledProbe).parameters["proof"].default is Parameter.empty


@given(
    template_ids=TEMPLATE_LISTS,
    a=st.integers(min_value=-12, max_value=12),
    b=st.integers(min_value=-12, max_value=12),
)
def test_selection_is_deterministic_across_input_order(
    template_ids: list[TemplateId], a: int, b: int
) -> None:
    mapping = _mapping(template_ids)
    reordered = RuleMappingV1(
        schema_version="rule_mapping.v1",
        hypotheses=list(reversed(mapping.hypotheses)),
    )

    assert compile_probe(mapping, a, b) == compile_probe(reordered, a, b)


@given(
    template_ids=TEMPLATE_LISTS,
    a=st.integers(min_value=-12, max_value=12),
    b=st.integers(min_value=-12, max_value=12),
)
def test_every_released_probe_separates_accepted_alternatives(
    template_ids: list[TemplateId], a: int, b: int
) -> None:
    result = compile_probe(_mapping(template_ids), a, b)

    assert isinstance(result, CompiledProbe)
    assert len({item.prediction for item in result.hypotheses}) >= 2


@given(
    rank=st.integers(min_value=1, max_value=4),
    evidence_ref=st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=12
    ),
)
def test_correct_equivalent_rules_are_always_removed(rank: int, evidence_ref: str) -> None:
    instance = RuleInstanceV1(
        template_id="add_subtrahend",
        evidence_refs=[evidence_ref],
        description="semantics are the authority",
        rank=rank,
    )
    evaluated = EvaluatedHypothesis(instance, truth_table_for_correct())

    assert deduplicate_evaluated_hypotheses([evaluated]) == ()


@given(
    template_ids=TEMPLATE_LISTS,
    a=st.integers(min_value=-12, max_value=12),
    b=st.integers(min_value=-12, max_value=12),
)
def test_probe_hash_reproduces_for_all_generated_specs(
    template_ids: list[TemplateId], a: int, b: int
) -> None:
    result = compile_probe(_mapping(template_ids), a, b)

    assert isinstance(result, CompiledProbe)
    assert reproduce_probe_hash(result) == result.specification_hash


def test_probe_hash_changes_when_complete_specification_changes() -> None:
    result = compile_probe(_mapping(("add_subtrahend", "absolute_difference")), 2, -7)
    assert isinstance(result, CompiledProbe)
    changed = replace(result, correct_prediction=result.correct_prediction + 1)

    assert reproduce_probe_hash(changed) != result.specification_hash


def test_probe_hash_covers_persisted_version_fields() -> None:
    result = compile_probe(_mapping(("add_subtrahend", "absolute_difference")), 2, -7)
    assert isinstance(result, CompiledProbe)
    changed_registry = replace(result, registry_version="rule_registry.v2")
    changed_compiler = replace(result, compiler_version="counterexample_compiler.v2")

    assert reproduce_probe_hash(changed_registry) != result.specification_hash
    assert reproduce_probe_hash(changed_compiler) != result.specification_hash


def test_probe_hash_is_reproducible_in_another_process() -> None:
    result = compile_probe(_mapping(("add_subtrahend", "absolute_difference")), 2, -7)
    assert isinstance(result, CompiledProbe)
    source = """
from cognisect.compiler import compile_probe
from cognisect.models import RuleInstanceV1, RuleMappingV1
mapping = RuleMappingV1(schema_version='rule_mapping.v1', hypotheses=[
    RuleInstanceV1(
        template_id='add_subtrahend', evidence_refs=['work.1'],
        description='Alternative 1: add_subtrahend', rank=1,
    ),
    RuleInstanceV1(
        template_id='absolute_difference', evidence_refs=['work.2'],
        description='Alternative 2: absolute_difference', rank=2,
    ),
])
print(compile_probe(mapping, 2, -7).specification_hash)
"""
    environment = {**os.environ, "PYTHONPATH": "backend/src"}

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", source],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.stdout.strip() == result.specification_hash


def test_semantic_collapse_below_two_alternatives_abstains() -> None:
    mapping = RuleMappingV1(
        schema_version="rule_mapping.v1",
        hypotheses=[
            RuleInstanceV1(
                template_id="add_subtrahend",
                evidence_refs=["first"],
                description="first",
                rank=1,
            ),
            RuleInstanceV1(
                template_id="add_subtrahend",
                evidence_refs=["second"],
                description="duplicate",
                rank=2,
            ),
        ],
    )

    result = compile_probe(mapping, 1, 2)

    assert result == CompilerAbstention(status="abstained", reason="insufficient_hypotheses")


def test_no_separating_candidate_abstains() -> None:
    first_table = tuple(0 for _ in range(625))
    second_values = list(first_table)
    original_index = (2 + 12) * 25 + (-7 + 12)
    second_values[original_index] = 1
    instances = _mapping(("add_subtrahend", "absolute_difference")).hypotheses
    accepted = (
        AcceptedHypothesis(
            template_id=instances[0].template_id,
            evidence_refs=tuple(instances[0].evidence_refs),
            description=instances[0].description,
            rank=instances[0].rank,
            truth_table_hash=canonical_truth_table_hash(first_table),
            truth_table=first_table,
        ),
        AcceptedHypothesis(
            template_id=instances[1].template_id,
            evidence_refs=tuple(instances[1].evidence_refs),
            description=instances[1].description,
            rank=instances[1].rank,
            truth_table_hash=canonical_truth_table_hash(tuple(second_values)),
            truth_table=tuple(second_values),
        ),
    )

    result = compile_accepted_probe(accepted, 2, -7)

    assert result == CompilerAbstention(status="abstained", reason="no_separating_probe")
