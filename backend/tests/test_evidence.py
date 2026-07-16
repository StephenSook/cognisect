"""Strict learner-response and deterministic evidence-update tests."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from cognisect.compiler import (
    CompiledProbe,
    CompilerAbstention,
    ProbeHypothesis,
    SignedProblem,
)
from cognisect.evidence import (
    EvidenceUpdate,
    LearnerResponseV1,
    parse_learner_response_json,
    update_evidence,
    update_evidence_from_json,
)
from cognisect.interpreter import COMPILER_VERSION, REGISTRY_VERSION


def _probe(*predictions: int, correct_prediction: int = 10) -> CompiledProbe:
    template_ids = (
        "add_subtrahend",
        "ignore_subtrahend_sign",
        "absolute_difference",
        "subtract_magnitudes",
    )
    return CompiledProbe(
        registry_version=REGISTRY_VERSION,
        compiler_version=COMPILER_VERSION,
        original_problem=SignedProblem(1, 2),
        chosen_problem=SignedProblem(3, -7),
        correct_prediction=correct_prediction,
        hypotheses=tuple(
            ProbeHypothesis(
                template_id=template_ids[index],
                evidence_refs=(f"work.{index}",),
                description=f"alternative {index}",
                rank=index + 1,
                truth_table_hash=str(index) * 64,
                prediction=prediction,
            )
            for index, prediction in enumerate(predictions)
        ),
        specification_hash="a" * 64,
    )


def test_strict_learner_response_accepts_bounded_integer_and_optional_rationale() -> None:
    without_rationale = parse_learner_response_json('{"answer":-10000}')
    with_rationale = parse_learner_response_json(
        json.dumps({"answer": 10000, "rationale": "x" * 1000})
    )

    assert without_rationale == LearnerResponseV1(answer=-10000)
    assert with_rationale.rationale == "x" * 1000


@pytest.mark.parametrize(
    "payload",
    [
        '{"answer":true}',
        '{"answer":1.0}',
        '{"answer":"1"}',
        '{"answer":10001}',
        '{"answer":-10001}',
        '{"answer":1,"extra":0}',
        '{"answer":1,"rationale":2}',
        json.dumps({"answer": 1, "rationale": "x" * 1001}),
        "1",
        "not-json",
    ],
)
def test_strict_learner_response_rejects_invalid_json_contract(payload: str) -> None:
    with pytest.raises((ValidationError, ValueError)):
        parse_learner_response_json(payload)


@given(
    invalid_answer=st.one_of(
        st.booleans(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=20),
        st.integers(max_value=-10001),
        st.integers(min_value=10001),
    )
)
def test_strict_parser_never_coerces_invalid_answer_types_or_ranges(invalid_answer: object) -> None:
    with pytest.raises(ValidationError):
        LearnerResponseV1.model_validate({"answer": invalid_answer})


def test_exactly_one_matching_alternative_is_supported_and_others_are_weakened() -> None:
    result = update_evidence(_probe(7, 8, 9), LearnerResponseV1(answer=7))

    assert result.status == "supported"
    assert [item.status for item in result.evidence] == ["supported", "weakened", "weakened"]


def test_multiple_matching_alternatives_are_unresolved_and_others_are_weakened() -> None:
    result = update_evidence(_probe(8, 8, 9), LearnerResponseV1(answer=8))

    assert result.status == "unresolved"
    assert [item.status for item in result.evidence] == ["unresolved", "unresolved", "weakened"]


def test_only_correct_answer_matching_weakens_every_alternative() -> None:
    result = update_evidence(_probe(7, 8, 9), LearnerResponseV1(answer=10))

    assert result.status == "weakened"
    assert all(item.status == "weakened" for item in result.evidence)


def test_no_stored_prediction_matching_leaves_every_alternative_unresolved() -> None:
    result = update_evidence(_probe(7, 8, 9), LearnerResponseV1(answer=99))

    assert result.status == "unresolved"
    assert all(item.status == "unresolved" for item in result.evidence)


def test_rationale_never_changes_deterministic_matching() -> None:
    probe = _probe(7, 8, 9)

    first = update_evidence(probe, LearnerResponseV1(answer=7, rationale="first explanation"))
    second = update_evidence(probe, LearnerResponseV1(answer=7, rationale="opposite explanation"))

    assert first == second


@pytest.mark.parametrize("payload", ['{"answer":true}', '{"answer":1.5}', '{"answer":"7"}'])
def test_invalid_input_exposes_abstention(payload: str) -> None:
    result = update_evidence_from_json(_probe(7, 8), payload)

    assert result == EvidenceUpdate(status="abstained", evidence=(), reason="invalid_response")


def test_no_separating_probe_exposes_abstention() -> None:
    compiler_result = CompilerAbstention(status="abstained", reason="no_separating_probe")

    result = update_evidence_from_json(compiler_result, '{"answer":7}')

    assert result == EvidenceUpdate(
        status="abstained",
        evidence=(),
        reason="no_separating_probe",
    )


def test_all_evidence_and_abstention_outputs_exclude_forbidden_vocabulary() -> None:
    outputs = [
        update_evidence(_probe(7, 8), LearnerResponseV1(answer=7)),
        update_evidence_from_json(_probe(7, 8), '{"answer":true}'),
        update_evidence_from_json(
            CompilerAbstention(status="abstained", reason="no_separating_probe"),
            '{"answer":7}',
        ),
    ]
    forbidden = ("confirmed", "proved", "diagnosed", "confidence")

    for output in outputs:
        serialized = json.dumps(asdict(output), sort_keys=True).lower()
        assert all(term not in serialized for term in forbidden)
