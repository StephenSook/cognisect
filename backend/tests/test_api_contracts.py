"""Strict public API and production-configuration contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from cognisect.api_models import (
    CompiledProbeResponse,
    CreateCaseRequest,
    LearnerProbeResponse,
    ReviewRequest,
    WorkflowResponse,
)
from cognisect.config import Settings
from cognisect.security import generate_derivation_nonce, generate_secret, hash_secret

VALID_ENV = {
    "database_url": "postgresql+psycopg://cognisect:password@db:5432/cognisect",
    "owner_secret_pepper": "o" * 32,
    "learner_token_pepper": "l" * 32,
    "abuse_key_pepper": "a" * 32,
    "proxy_signing_secret": "p" * 32,
    "public_app_url": "https://cognisect.example",
    "openai_api_key": "sk-test-" + ("k" * 32),
}


def test_workflow_abstention_origin_is_required_nullable_closed_vocabulary() -> None:
    schema = WorkflowResponse.model_json_schema()
    field_schema = schema["properties"]["abstention_origin"]

    assert "abstention_origin" in schema["required"]
    assert field_schema == {
        "anyOf": [
            {
                "enum": [
                    "analysis",
                    "teacher_probe",
                    "learner_response",
                    "teacher_review",
                ],
                "type": "string",
            },
            {"type": "null"},
        ],
        "title": "Abstention Origin",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "sqlite+aiosqlite:///tmp.db"),
        ("database_url", "postgresql://localhost/not-explicit"),
        ("owner_secret_pepper", "short"),
        ("learner_token_pepper", "replace-with-at-least-32-random-characters"),
        ("abuse_key_pepper", "shared-or-short"),
        ("proxy_signing_secret", "short"),
    ],
)
def test_settings_reject_non_postgres_or_placeholder_security_values(field, value):
    values = {**VALID_ENV, "app_env": "development", field: value}
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("public_app_url", "http://localhost:3000"),
        ("public_app_url", "https://127.0.0.1"),
        ("openai_api_key", ""),
        ("openai_api_key", "short-production-key"),
    ],
)
def test_production_settings_reject_local_public_url_and_missing_key(field, value):
    values = {**VALID_ENV, "app_env": "production", field: value}
    with pytest.raises(ValidationError):
        Settings(**values)


def test_development_settings_allow_local_public_url_but_require_explicit_peppers():
    settings = Settings(
        **{
            **VALID_ENV,
            "app_env": "development",
            "public_app_url": "http://localhost:3000",
            "openai_api_key": "",
        }
    )
    assert settings.database_url.startswith("postgresql+")


@pytest.mark.parametrize("shared_with", ["owner_secret_pepper", "learner_token_pepper"])
def test_abuse_pepper_must_be_dedicated(shared_with: str) -> None:
    values = {**VALID_ENV, "abuse_key_pepper": VALID_ENV[shared_with]}

    with pytest.raises(ValidationError, match="ABUSE_KEY_PEPPER must be distinct"):
        Settings(**values)


def test_production_requires_proxy_signing_secret_without_silent_fallback() -> None:
    values = {**VALID_ENV, "app_env": "production"}
    values.pop("proxy_signing_secret")

    with pytest.raises(ValidationError, match="PROXY_SIGNING_SECRET"):
        Settings(**values)


@pytest.mark.parametrize(
    ("case", "invalid_secret"),
    [
        ("whitespace-only reviewer reproduction", " " * 32),
        ("trim-short reviewer reproduction", f" {'p' * 30} "),
        ("byte-order mark", "\ufeff" + ("A" * 32)),
        ("nul control", ("A" * 31) + "\0"),
        ("internal space", ("A" * 16) + " " + ("A" * 16)),
        ("internal tab", ("A" * 16) + "\t" + ("A" * 16)),
        ("internal newline", ("A" * 16) + "\n" + ("A" * 16)),
        ("non-ascii emoji", ("A" * 31) + "😀"),
        ("period punctuation", ("A" * 31) + "."),
        ("plus punctuation", ("A" * 31) + "+"),
        ("slash punctuation", ("A" * 31) + "/"),
        ("under minimum", "A" * 31),
        ("over maximum", "A" * 129),
        ("placeholder", "placeholder" + ("A" * 21)),
    ],
)
def test_proxy_signing_secret_rejects_non_base64url_or_ambiguous_values(
    case: str,
    invalid_secret: str,
) -> None:
    assert case

    with pytest.raises(ValidationError, match="PROXY_SIGNING_SECRET"):
        Settings(
            **{
                **VALID_ENV,
                "app_env": "production",
                "proxy_signing_secret": invalid_secret,
            }
        )


@pytest.mark.parametrize(
    "valid_secret",
    ["Aa0_-" + ("Z" * 27), "A" * 128],
)
def test_proxy_signing_secret_accepts_base64url_boundaries_unchanged(
    valid_secret: str,
) -> None:
    settings = Settings(
        **{
            **VALID_ENV,
            "app_env": "production",
            "proxy_signing_secret": valid_secret,
        }
    )

    assert settings.proxy_signing_secret.get_secret_value() == valid_secret


@pytest.mark.parametrize(
    "shared_with",
    ["owner_secret_pepper", "learner_token_pepper", "abuse_key_pepper"],
)
def test_proxy_signing_secret_must_be_dedicated(shared_with: str) -> None:
    values = {**VALID_ENV, "proxy_signing_secret": VALID_ENV[shared_with]}

    with pytest.raises(ValidationError, match="PROXY_SIGNING_SECRET must be distinct"):
        Settings(**values)


def test_settings_accept_true_environment_string_for_strict_msgpack(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")

    settings = Settings(
        _env_file=None,
        **{
            **VALID_ENV,
            "app_env": "production",
        },
    )

    assert settings.langgraph_strict_msgpack is True


@pytest.mark.parametrize("revision", ["ABCDEF" * 7, "abc123", "g" * 40, ""])
def test_source_revision_rejects_everything_except_development_or_lowercase_git_sha(
    revision: str,
) -> None:
    with pytest.raises(ValidationError):
        Settings(**{**VALID_ENV, "source_revision": revision})


def test_render_git_commit_is_the_source_revision_fallback(monkeypatch) -> None:
    monkeypatch.delenv("SOURCE_REVISION", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)

    settings = Settings(_env_file=None, **VALID_ENV)

    assert settings.source_revision == "a" * 40


def test_custom_case_requires_deidentified_attestation_and_forbids_identifiers():
    payload = {
        "source_tier": "custom",
        "problem": {"a": -3, "b": 5},
        "observed_work": "-3 - 5 = 2",
        "deidentified_attestation": False,
    }
    with pytest.raises(ValidationError):
        CreateCaseRequest.model_validate(payload)

    payload["deidentified_attestation"] = True
    payload["learner_name"] = "A learner"
    with pytest.raises(ValidationError):
        CreateCaseRequest.model_validate(payload)


def test_non_custom_case_does_not_require_attestation():
    request = CreateCaseRequest.model_validate(
        {
            "source_tier": "educator_authored",
            "problem": {"a": -3, "b": 5},
            "observed_work": "-3 - 5 = 2",
        }
    )
    assert request.deidentified_attestation is False


def test_case_source_validator_name_exposes_attestation_and_provenance_rules() -> None:
    validator_doc = CreateCaseRequest.attestation_and_provenance_match_source_tier.__doc__
    assert validator_doc is not None
    assert "attestation" in validator_doc
    assert "provenance" in validator_doc


def test_provenance_record_id_is_strict_and_only_allowed_for_educator_authored() -> None:
    request = CreateCaseRequest.model_validate(
        {
            "source_tier": "educator_authored",
            "provenance_record_id": "cognisect-ea-001",
            "problem": {"a": -3, "b": 5},
            "observed_work": "-3 - 5 = 2",
        }
    )
    assert request.provenance_record_id == "cognisect-ea-001"

    for provenance_record_id in (
        "",
        " cognisect-ea-001",
        "cognisect-ea-001 ",
        "cognisect/ea/001",
        "x" * 81,
        1,
    ):
        with pytest.raises(ValidationError):
            CreateCaseRequest.model_validate(
                {
                    "source_tier": "educator_authored",
                    "provenance_record_id": provenance_record_id,
                    "problem": {"a": -3, "b": 5},
                    "observed_work": "-3 - 5 = 2",
                }
            )

    for source_tier in ("custom", "authentic", "synthetic", "mixed", "published_exemplar"):
        with pytest.raises(ValidationError, match="provenance_record_id"):
            CreateCaseRequest.model_validate(
                {
                    "source_tier": source_tier,
                    "provenance_record_id": "cognisect-ea-001",
                    "problem": {"a": -3, "b": 5},
                    "observed_work": "-3 - 5 = 2",
                    "deidentified_attestation": source_tier == "custom",
                }
            )


@pytest.mark.parametrize("decision", ["approved", "edited"])
def test_positive_review_requires_non_empty_note(decision):
    with pytest.raises(ValidationError):
        ReviewRequest(expected_version=7, decision=decision, note="   ")


def test_final_review_allows_strict_abstention_without_edit_content() -> None:
    request = ReviewRequest(
        expected_version=7,
        decision="abstained",
        note="Evidence remains insufficient for a release decision.",
    )
    assert request.decision == "abstained"
    with pytest.raises(ValueError, match="edited_text"):
        ReviewRequest(
            expected_version=7,
            decision="abstained",
            edited_text="must not be released",
        )


def test_rejected_review_forbids_approved_or_edited_text():
    with pytest.raises(ValidationError):
        ReviewRequest(
            expected_version=7,
            decision="rejected",
            note="not approved",
            edited_text="This must not be stored as approved.",
        )


def test_learner_dto_has_only_approved_problem_constraints_and_expiry():
    dto = LearnerProbeResponse(
        problem={"a": -2, "b": -7},
        answer_constraints={"minimum": -10_000, "maximum": 10_000},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        instructions="Submit one signed integer.",
    )
    fields = set(dto.model_dump(mode="json"))
    assert fields == {"problem", "answer_constraints", "expires_at", "instructions"}
    forbidden = {
        "accepted_hypotheses",
        "compiled_probe",
        "deterministic_evidence",
        "hypotheses",
        "correct_answer",
        "predictions",
        "review_result",
        "source_tier",
        "owner",
        "evidence",
        "model_response_id",
        "model_request_id",
        "teacher_notes",
        "learner_rationale",
    }
    assert fields.isdisjoint(forbidden)


def test_learner_schema_never_includes_teacher_workflow_fields() -> None:
    schema_text = str(LearnerProbeResponse.model_json_schema())
    for teacher_field in (
        "accepted_hypotheses",
        "compiled_probe",
        "correct_prediction",
        "deterministic_evidence",
        "generated_proposal",
        "model_response_id",
        "model_request_id",
        "predictions",
        "review_result",
        "source_tier",
        "learner_rationale",
    ):
        assert teacher_field not in schema_text


def test_compiled_probe_contract_requires_strict_deterministic_proof() -> None:
    payload = {
        "original_problem": {"a": -3, "b": 5},
        "problem": {"a": 0, "b": -1},
        "correct_prediction": 1,
        "specification_hash": "a" * 64,
        "registry_version": "rule_registry.v1",
        "compiler_version": "counterexample_compiler.v1",
        "predictions": [
            {"template_id": "add_subtrahend", "rank": 1, "prediction": -1},
            {"template_id": "absolute_difference", "rank": 2, "prediction": 1},
        ],
        "proof": {
            "domain_problem_count": 625,
            "eligible_candidate_count": 624,
            "separating_candidate_count": 120,
            "chosen_candidate_rank": 1,
            "top_candidates": [
                {
                    "problem": {"a": 0, "b": -1},
                    "predictions": [-1, 1],
                    "distinct_output_count": 2,
                    "top_two_separated": True,
                    "distinguished_pair_count": 1,
                    "operand_magnitude": 1,
                    "correct_result_magnitude": 1,
                    "rank": 1,
                }
            ],
        },
    }

    dto = CompiledProbeResponse.model_validate(payload)

    assert dto.proof.top_candidates[0].predictions == [-1, 1]
    invalid = {**payload, "proof": {**payload["proof"], "domain_problem_count": "625"}}
    with pytest.raises(ValidationError):
        CompiledProbeResponse.model_validate(invalid)


def test_generated_secrets_are_high_entropy_and_hashes_are_purpose_separated():
    secret = generate_secret()
    assert len(secret) >= 43
    owner_hash = hash_secret(secret, "p" * 32, purpose="owner")
    learner_hash = hash_secret(secret, "p" * 32, purpose="learner-token")
    assert owner_hash != learner_hash
    assert secret not in owner_hash


def test_learner_derivation_nonce_uses_32_bytes_from_the_csprng(monkeypatch):
    calls: list[int] = []

    def fake_token_bytes(length: int) -> bytes:
        calls.append(length)
        return b"n" * length

    monkeypatch.setattr("cognisect.security.secrets.token_bytes", fake_token_bytes)

    assert generate_derivation_nonce() == b"n" * 32
    assert calls == [32]
