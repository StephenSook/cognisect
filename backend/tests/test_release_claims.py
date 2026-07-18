"""Bind public README claims to checked-in benchmark and stress evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]

UNSUPPORTED_POSITIVE_CLAIM_PATTERNS = (
    r"\bconfirmed misconceptions?\b",
    r"\bexact diagnos(?:is|es)\b",
    r"\beducator[- ]reviewed\b",
    r"\bvalidated by educators?\b",
    r"\beducator validation\b",
    r"\b(?:has|have)\s+classroom adoption\b",
    r"\bimproves?\s+learning\b",
    r"\b(?:used|deployed|adopted|piloted)\s+in\s+\d+\s+classrooms?\b",
    r"\b(?:raises?|improves?|increases?|boosts?)\s+(?:learner|student)\s+scores?\b",
    r"\bdiagnos(?:e|es|ed|ing)\s+misconceptions?\b",
    r"\beducator[- ]validated\b",
    r"\bsaves?\s+(?:teachers?|educators?|instructors?)\s+\d+(?:\.\d+)?\s+"
    r"(?:minutes?|hours?)\b",
    r"\b\d+(?:\.\d+)?%\s+confidence\b",
    r"\b\d+(?:\.\d+)?\s+percent\s+confidence\b",
    r"\bconfidence\b(?:\s+(?:score|level))?\s*(?:of|:|=)\s*\d",
    r"\bconfidence\b(?:\s+(?:score|level))?\s+\d+(?:\.\d+)?%",
    r"\bconfidence\s*:\s*(?:high|medium|low)\b",
    r"\b(?:high|medium|low)\s+confidence\b",
    r"\bconfidence score\b",
)
ALLOWLISTED_NEGATIVE_CLAIM_PATTERNS = (
    r"\beducator validation (?:has|had) not occurred\b",
    r"\bno educator validation (?:has |had )?occurred\b",
    r"\bnot evidence of educator validation\b",
    r"\bno (?:external )?educator(?: usability)? review (?:has |had )?occurred\b",
    r"\b(?:external )?educator(?: usability)? review (?:has|had) not occurred\b",
    r"\b(?:was|were|is|are|has|have|had) not "
    r"(?:used|deployed|adopted|piloted) in \d+ classrooms?\b",
    r"\b(?:does|do|did) not (?:use|deploy|adopt|pilot) "
    r"(?:the tool )?in \d+ classrooms?\b",
    r"\b(?:does|do|did) not save (?:teachers?|educators?|instructors?) "
    r"\d+(?:\.\d+)? (?:minutes?|hours?)\b",
    r"\b(?:does|do|did) not (?:raise|improve|increase|boost) "
    r"(?:learner|student) scores?\b",
    r"\b(?:does|do|did) not diagnose misconceptions?\b",
    r"\b(?:was|were|is|are) not educator[- ]validated\b",
    r"\b(?:not (?:a )?|no )confidence score\b",
)


def _json(relative_path: str) -> dict[str, Any]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _without_allowlisted_negative_claims(public_copy: str) -> str:
    sanitized = " ".join(public_copy.lower().split())
    for pattern in ALLOWLISTED_NEGATIVE_CLAIM_PATTERNS:
        sanitized = re.sub(pattern, " ", sanitized)
    return sanitized


def _assert_no_unsupported_positive_claims(public_copy: str) -> None:
    sanitized = _without_allowlisted_negative_claims(public_copy)
    unsupported = [
        match.group(0)
        for pattern in UNSUPPORTED_POSITIVE_CLAIM_PATTERNS
        for match in re.finditer(pattern, sanitized)
    ]
    assert not unsupported, f"unsupported positive public claims: {unsupported}"


@pytest.mark.parametrize(
    "claim",
    [
        "Used in 20 classrooms.",
        "Raises learner scores.",
        "Diagnoses misconceptions.",
        "Educator-validated.",
        "Educator validation occurred.",
        "Saves teachers 10 minutes.",
        "Confidence: high.",
        "95 percent confidence.",
        "Confidence 95%.",
        "95% confidence.",
        "High confidence.",
        "This is a confidence score.",
        "The tool does not guess and diagnoses misconceptions.",
        "COGNISECT is not experimental and is educator-validated.",
    ],
)
def test_positive_claim_guard_rejects_unsupported_variants(claim: str) -> None:
    with pytest.raises(AssertionError):
        _assert_no_unsupported_positive_claims(claim)


@pytest.mark.parametrize(
    "disclaimer",
    [
        "No educator usability review has occurred.",
        "COGNISECT has no classroom adoption.",
        "This is not a generalized accuracy estimate.",
        "This was not used in 20 classrooms.",
        "The tool does not save teachers 10 minutes.",
        "The tool does not raise learner scores.",
        "The tool does not diagnose misconceptions.",
        "No educator validation occurred.",
        "The tool was not educator-validated.",
        "Educator validation has not occurred.",
        "Inspect the separation, not a confidence score.",
    ],
)
def test_positive_claim_guard_allows_explicit_negative_disclaimers(
    disclaimer: str,
) -> None:
    _assert_no_unsupported_positive_claims(disclaimer)


def test_readme_claims_match_frozen_evidence() -> None:
    benchmark = _json("data/evaluation/benchmark-report.v1.json")
    stress = _json("data/security/production-stress-report.v1.json")
    security = _json("data/security/security-audit.v1.json")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    terra = benchmark["model_comparison"]["terra"]
    sol = benchmark["model_comparison"]["sol"]
    verification = security["verification"]

    required_claims = {
        "six educator-authored fixtures",
        f"{benchmark['model_calls_made']} live model calls",
        f"Terra {round(terra['metrics']['exact_set_rate'] * 6):d}/6; "
        f"Sol {round(sol['metrics']['exact_set_rate'] * 6):d}/6",
        (
            f"{stress['accepted_submissions']} accepted and "
            f"{stress['conflicting_submissions']} conflicted out of "
            f"{stress['concurrent_submissions']}"
        ),
        f"{verification['targeted_security_tests_passed']} passed",
        f"{verification['playwright_journeys_passed']} desktop, mobile",
        "Zero learner responses",
    }
    normalized = " ".join(readme.split())
    for claim in required_claims:
        assert claim in normalized


def test_public_copy_preserves_claim_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    evaluation = (ROOT / "docs" / "EVALUATION.md").read_text(encoding="utf-8")
    registry = (ROOT / "docs" / "specs" / "rule-registry-v1.md").read_text(
        encoding="utf-8"
    )
    landing = (ROOT / "frontend" / "src" / "app" / "(teacher)" / "page.tsx").read_text(
        encoding="utf-8"
    )
    lowered = f"{readme}\n{evaluation}\n{registry}\n{landing}".lower()
    normalized = " ".join(lowered.split())

    required_claims = (
        "six educator-authored fixtures",
        "zero learner responses",
        "not a generalized accuracy estimate",
        "optional ksu usability review has not occurred",
        "1 accepted and 49 conflicted",
        "teacher approval",
        "counterexample compiler",
        "closed, literature-grounded",
        "codex",
        "save the final teacher decision",
        "read the persisted decision back",
    )

    missing = [claim for claim in required_claims if claim not in normalized]
    assert not missing, f"missing public claims: {missing}"
    _assert_no_unsupported_positive_claims(lowered)


def test_readme_judge_path_has_five_steps_and_final_review_readback() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    judge_path = readme.split("## Judge path", maxsplit=1)[1].split("\n## ", maxsplit=1)[0]

    assert re.findall(r"(?m)^\d+\. ", judge_path) == [
        "1. ",
        "2. ",
        "3. ",
        "4. ",
        "5. ",
    ]
    normalized = " ".join(judge_path.lower().split())
    assert "save the final teacher decision" in normalized
    assert "read the persisted decision back" in normalized
