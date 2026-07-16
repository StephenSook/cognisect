"""Deterministic counterexample compiler tests."""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
from dataclasses import replace
from typing import cast

from hypothesis import given
from hypothesis import strategies as st

from cognisect.compiler import (
    CompiledProbe,
    CompilerAbstention,
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
