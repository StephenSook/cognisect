"""Exhaustive tests for registry semantics and canonicalization."""

from __future__ import annotations

import hashlib
import json
from typing import cast

import pytest

from cognisect.interpreter import (
    DOMAIN_VALUES,
    REGISTRY_TEMPLATE_IDS,
    EvaluatedHypothesis,
    accept_hypotheses,
    canonical_truth_table_hash,
    correct_result,
    deduplicate_evaluated_hypotheses,
    evaluate_template,
    truth_table_for_correct,
    truth_table_for_template,
)
from cognisect.models import RuleInstanceV1, RuleMappingV1, TemplateId
from oracle import OracleTemplateId, oracle_result


@pytest.mark.parametrize("template_id", REGISTRY_TEMPLATE_IDS)
def test_registry_template_matches_independent_oracle_on_all_625_inputs(
    template_id: TemplateId,
) -> None:
    oracle_template = cast("OracleTemplateId", template_id)

    for a in DOMAIN_VALUES:
        for b in DOMAIN_VALUES:
            assert evaluate_template(template_id, a, b) == oracle_result(oracle_template, a, b)


def test_truth_tables_have_canonical_order_and_independent_sha256_hashes() -> None:
    for template_id in REGISTRY_TEMPLATE_IDS:
        oracle_template = cast("OracleTemplateId", template_id)
        expected = tuple(
            oracle_result(oracle_template, a, b) for a in DOMAIN_VALUES for b in DOMAIN_VALUES
        )
        expected_hash = hashlib.sha256(
            json.dumps(list(expected), separators=(",", ":")).encode()
        ).hexdigest()

        actual = truth_table_for_template(template_id)

        assert len(actual) == 625
        assert actual == expected
        assert canonical_truth_table_hash(actual) == expected_hash
        assert len(expected_hash) == 64


def test_correct_truth_table_is_complete_and_ordered() -> None:
    expected = tuple(a - b for a in DOMAIN_VALUES for b in DOMAIN_VALUES)

    assert truth_table_for_correct() == expected
    assert all(correct_result(a, b) == a - b for a in DOMAIN_VALUES for b in DOMAIN_VALUES)


@pytest.mark.parametrize(
    ("template_id", "a", "b"),
    [
        ("unknown", 1, 2),
        ("add_subtrahend", True, 2),
        ("add_subtrahend", 1.0, 2),
        ("add_subtrahend", -13, 2),
        ("add_subtrahend", 1, 13),
    ],
)
def test_interpreter_rejects_unknown_templates_and_invalid_operands(
    template_id: object, a: object, b: object
) -> None:
    with pytest.raises((TypeError, ValueError)):
        evaluate_template(cast("TemplateId", template_id), cast("int", a), cast("int", b))


def _instance(
    template_id: TemplateId,
    *,
    rank: int,
    evidence_refs: list[str],
    description: str,
) -> RuleInstanceV1:
    return RuleInstanceV1(
        template_id=template_id,
        evidence_refs=evidence_refs,
        description=description,
        rank=rank,
    )


def test_semantic_duplicates_merge_deterministically_and_preserve_best_rank_and_evidence() -> None:
    mapping = RuleMappingV1(
        schema_version="rule_mapping.v1",
        hypotheses=[
            _instance(
                "add_subtrahend",
                rank=3,
                evidence_refs=["work.z", "work.a"],
                description="lower ranked duplicate",
            ),
            _instance(
                "negative_magnitude_sum",
                rank=2,
                evidence_refs=["work.n"],
                description="distinct alternative",
            ),
            _instance(
                "add_subtrahend",
                rank=1,
                evidence_refs=["work.best", "work.a"],
                description="best ranked duplicate",
            ),
        ],
    )

    accepted = accept_hypotheses(mapping)

    assert [item.template_id for item in accepted] == [
        "add_subtrahend",
        "negative_magnitude_sum",
    ]
    assert accepted[0].rank == 1
    assert accepted[0].description == "best ranked duplicate"
    assert accepted[0].evidence_refs == ("work.a", "work.best", "work.z")


def test_merge_result_is_independent_of_candidate_order() -> None:
    candidates = [
        EvaluatedHypothesis(
            _instance(
                "add_subtrahend",
                rank=2,
                evidence_refs=["second"],
                description="second",
            ),
            truth_table_for_template("add_subtrahend"),
        ),
        EvaluatedHypothesis(
            _instance(
                "add_subtrahend",
                rank=1,
                evidence_refs=["first"],
                description="first",
            ),
            truth_table_for_template("add_subtrahend"),
        ),
    ]

    assert deduplicate_evaluated_hypotheses(candidates) == deduplicate_evaluated_hypotheses(
        reversed(candidates)
    )


def test_any_alternative_equivalent_to_correct_rule_is_rejected() -> None:
    correct_equivalent = EvaluatedHypothesis(
        _instance(
            "add_subtrahend",
            rank=1,
            evidence_refs=["correct-equivalent"],
            description="must be removed by semantics, not by name",
        ),
        truth_table_for_correct(),
    )
    valid_alternative = EvaluatedHypothesis(
        _instance(
            "negative_magnitude_sum",
            rank=2,
            evidence_refs=["alternative"],
            description="valid alternative",
        ),
        truth_table_for_template("negative_magnitude_sum"),
    )

    accepted = deduplicate_evaluated_hypotheses([correct_equivalent, valid_alternative])

    assert [item.template_id for item in accepted] == ["negative_magnitude_sum"]
