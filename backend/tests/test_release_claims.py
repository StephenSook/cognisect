"""Bind public README claims to checked-in benchmark and stress evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _json(relative_path: str) -> dict[str, Any]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


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
    lowered = f"{readme}\n{evaluation}".lower()
    normalized = " ".join(lowered.split())

    for required in (
        "six educator-authored fixtures",
        "zero learner responses",
        "not a generalized accuracy estimate",
        "optional ksu usability review has not occurred",
        "1 accepted and 49 conflicted",
        "teacher approval",
        "counterexample compiler",
    ):
        assert required in normalized

    for forbidden in (
        "confirmed misconception",
        "exact diagnosis",
        "validated by educators",
        "has classroom adoption",
        "improves learning",
    ):
        assert forbidden not in lowered
