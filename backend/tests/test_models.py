"""Contract tests for strict registry models and frozen schemas."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cognisect.models import RuleInstanceV1, RuleMappingV1

ROOT = Path(__file__).parents[2]
VALID_EXAMPLE = json.loads(
    (ROOT / "schemas/examples/rule-mapping.valid.json").read_text(encoding="utf-8")
)


def test_rule_instance_schema_matches_frozen_contract() -> None:
    frozen = json.loads(
        (ROOT / "schemas/rule-instance.v1.schema.json").read_text(encoding="utf-8")
    )

    assert RuleInstanceV1.model_json_schema(mode="validation") == frozen


def test_rule_mapping_schema_matches_frozen_contract() -> None:
    frozen = json.loads(
        (ROOT / "schemas/rule-mapping.v1.schema.json").read_text(encoding="utf-8")
    )

    assert RuleMappingV1.model_json_schema(mode="validation") == frozen


def test_checked_in_valid_example_is_accepted() -> None:
    mapping = RuleMappingV1.model_validate(VALID_EXAMPLE)

    assert [item.rank for item in mapping.hypotheses] == [1, 2]


def test_checked_in_invalid_example_is_rejected() -> None:
    invalid = json.loads(
        (ROOT / "schemas/examples/rule-mapping.invalid-extra-field.json").read_text(
            encoding="utf-8"
        )
    )

    with pytest.raises(ValidationError):
        RuleMappingV1.model_validate(invalid)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("template_id", "execute_source"),
        ("evidence_refs", ["same", "same"]),
        ("evidence_refs", []),
        ("evidence_refs", [str(index) for index in range(9)]),
        ("description", ""),
        ("description", "x" * 281),
        ("rank", True),
        ("rank", 0),
        ("rank", 5),
    ],
)
def test_rule_instance_rejects_invalid_contract_values(field: str, value: object) -> None:
    candidate = copy.deepcopy(VALID_EXAMPLE["hypotheses"][0])
    candidate[field] = value

    with pytest.raises(ValidationError):
        RuleInstanceV1.model_validate(candidate)


def test_rule_instance_rejects_extra_fields() -> None:
    candidate = copy.deepcopy(VALID_EXAMPLE["hypotheses"][0])
    candidate["parameters"] = {"callable": "anything"}

    with pytest.raises(ValidationError):
        RuleInstanceV1.model_validate(candidate)


@pytest.mark.parametrize("count", [1, 5])
def test_mapping_rejects_hypothesis_counts_outside_two_through_four(count: int) -> None:
    candidate = copy.deepcopy(VALID_EXAMPLE)
    candidate["hypotheses"] = [
        {
            **copy.deepcopy(VALID_EXAMPLE["hypotheses"][0]),
            "rank": index + 1,
        }
        for index in range(count)
    ]

    with pytest.raises(ValidationError):
        RuleMappingV1.model_validate(candidate)


def test_mapping_rejects_duplicate_ranks() -> None:
    candidate = copy.deepcopy(VALID_EXAMPLE)
    candidate["hypotheses"][1]["rank"] = 1

    with pytest.raises(ValidationError):
        RuleMappingV1.model_validate(candidate)


def test_mapping_rejects_boolean_rank_even_when_loaded_from_json() -> None:
    payload = json.dumps(
        {
            **VALID_EXAMPLE,
            "hypotheses": [
                {**VALID_EXAMPLE["hypotheses"][0], "rank": True},
                VALID_EXAMPLE["hypotheses"][1],
            ],
        }
    )

    with pytest.raises(ValidationError):
        RuleMappingV1.model_validate_json(payload)


def test_mapping_rejects_extra_fields_and_wrong_schema_version() -> None:
    with_extra = {**copy.deepcopy(VALID_EXAMPLE), "source": "model"}
    wrong_version = {**copy.deepcopy(VALID_EXAMPLE), "schema_version": "rule_mapping.v2"}

    with pytest.raises(ValidationError):
        RuleMappingV1.model_validate(with_extra)
    with pytest.raises(ValidationError):
        RuleMappingV1.model_validate(wrong_version)
