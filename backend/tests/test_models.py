"""Contract tests for strict registry models and frozen schemas."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from cognisect.db_models import RateLimitWindowRecord
from cognisect.models import RuleInstanceV1, RuleMappingV1

ROOT = Path(__file__).parents[2]
VALID_EXAMPLE = json.loads(
    (ROOT / "schemas/examples/rule-mapping.valid.json").read_text(encoding="utf-8")
)


def _normalize_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_schema(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"$defs", "$id", "$schema", "description", "title"}:
            continue
        if key == "$ref" and item == "#/$defs/RuleInstanceV1":
            normalized[key] = "rule-instance.v1.schema.json"
        else:
            normalized[key] = _normalize_schema(item)

    if "const" in normalized and normalized.get("type") == "string":
        normalized.pop("type")
    return normalized


def _genuine_validation_schema(model: type[BaseModel]) -> dict[str, Any]:
    assert "model_json_schema" not in model.__dict__, "schema generation must not be overridden"
    return model.model_json_schema(mode="validation")


def test_rule_instance_schema_matches_frozen_contract() -> None:
    frozen = json.loads(
        (ROOT / "schemas/rule-instance.v1.schema.json").read_text(encoding="utf-8")
    )

    generated = _genuine_validation_schema(RuleInstanceV1)

    assert _normalize_schema(generated) == _normalize_schema(frozen)


def test_rule_mapping_schema_matches_frozen_contract() -> None:
    frozen = json.loads(
        (ROOT / "schemas/rule-mapping.v1.schema.json").read_text(encoding="utf-8")
    )

    generated = _genuine_validation_schema(RuleMappingV1)

    assert _normalize_schema(generated) == _normalize_schema(frozen)


def test_schema_parity_normalization_retains_validation_constraints() -> None:
    frozen = json.loads(
        (ROOT / "schemas/rule-instance.v1.schema.json").read_text(encoding="utf-8")
    )
    changed = copy.deepcopy(_genuine_validation_schema(RuleInstanceV1))
    changed["properties"]["rank"]["maximum"] = 5

    assert _normalize_schema(changed) != _normalize_schema(frozen)


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


def test_rate_limit_table_has_explicit_constraints_and_expiry_leading_index() -> None:
    table = RateLimitWindowRecord.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    assert {
        "pk_rate_limit_windows",
        "ck_rate_limit_windows_scope",
        "ck_rate_limit_windows_bucket_hash",
        "ck_rate_limit_windows_consumed",
        "ck_rate_limit_windows_expiry",
    } <= constraint_names
    assert ["expires_at"] in [
        [column.name for column in index.columns] for index in table.indexes
    ]
    assert table.c.window_started_at.type.timezone is True
    assert table.c.expires_at.type.timezone is True
