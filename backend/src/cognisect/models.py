"""Strict data contracts for the closed rule registry."""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.json_schema import DEFAULT_REF_TEMPLATE, GenerateJsonSchema, JsonSchemaMode

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

_TEMPLATE_IDS = [
    "add_subtrahend",
    "ignore_subtrahend_sign",
    "absolute_difference",
    "subtract_magnitudes",
    "keep_minuend_sign",
    "negative_magnitude_sum",
]


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

    _frozen_schema: ClassVar[dict[str, Any]] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://cognisect.example/schemas/rule-instance.v1.schema.json",
        "title": "RuleInstanceV1",
        "type": "object",
        "additionalProperties": False,
        "required": ["template_id", "evidence_refs", "description", "rank"],
        "properties": {
            "template_id": {"type": "string", "enum": _TEMPLATE_IDS},
            "evidence_refs": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 80},
            },
            "description": {"type": "string", "minLength": 1, "maxLength": 280},
            "rank": {"type": "integer", "minimum": 1, "maximum": 4},
        },
    }

    @field_validator("evidence_refs")
    @classmethod
    def evidence_references_are_unique(cls, value: list[str]) -> list[str]:
        """Reject repeated references rather than silently coalescing them."""
        if len(value) != len(set(value)):
            msg = "evidence_refs must contain unique values"
            raise ValueError(msg)
        return value

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,  # noqa: FBT001, FBT002
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = "validation",
        *,
        union_format: Literal["any_of", "primitive_type_array"] = "any_of",
    ) -> dict[str, Any]:
        """Return the checked-in, externally referenced schema verbatim."""
        del by_alias, ref_template, schema_generator, mode, union_format
        return deepcopy(cls._frozen_schema)


class RuleMappingV1(StrictContractModel):
    """A bounded, rank-unique collection of registry hypotheses."""

    schema_version: Literal["rule_mapping.v1"]
    hypotheses: Annotated[list[RuleInstanceV1], Field(min_length=2, max_length=4)]

    _frozen_schema: ClassVar[dict[str, Any]] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://cognisect.example/schemas/rule-mapping.v1.schema.json",
        "title": "RuleMappingV1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "hypotheses"],
        "properties": {
            "schema_version": {"const": "rule_mapping.v1"},
            "hypotheses": {
                "type": "array",
                "minItems": 2,
                "maxItems": 4,
                "items": {"$ref": "rule-instance.v1.schema.json"},
            },
        },
    }

    @model_validator(mode="after")
    def ranks_are_unique(self) -> Self:
        """Reject mappings whose ordering signal is ambiguous."""
        ranks = [hypothesis.rank for hypothesis in self.hypotheses]
        if len(ranks) != len(set(ranks)):
            msg = "hypothesis ranks must be unique"
            raise ValueError(msg)
        return self

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,  # noqa: FBT001, FBT002
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = "validation",
        *,
        union_format: Literal["any_of", "primitive_type_array"] = "any_of",
    ) -> dict[str, Any]:
        """Return the checked-in, externally referenced schema verbatim."""
        del by_alias, ref_template, schema_generator, mode, union_format
        return deepcopy(cls._frozen_schema)
