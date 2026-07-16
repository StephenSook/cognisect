"""Strict public API and production-configuration contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from cognisect.api_models import (
    CreateCaseRequest,
    LearnerProbeResponse,
    ReviewRequest,
)
from cognisect.config import Settings
from cognisect.security import generate_derivation_nonce, generate_secret, hash_secret

VALID_ENV = {
    "database_url": "postgresql+psycopg://cognisect:password@db:5432/cognisect",
    "owner_secret_pepper": "o" * 32,
    "learner_token_pepper": "l" * 32,
    "public_app_url": "https://cognisect.example",
    "openai_api_key": "sk-test-" + ("k" * 32),
}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "sqlite+aiosqlite:///tmp.db"),
        ("database_url", "postgresql://localhost/not-explicit"),
        ("owner_secret_pepper", "short"),
        ("learner_token_pepper", "replace-with-at-least-32-random-characters"),
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
        "hypotheses",
        "correct_answer",
        "predictions",
        "owner",
        "evidence",
        "model_request_id",
        "teacher_notes",
    }
    assert fields.isdisjoint(forbidden)


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
