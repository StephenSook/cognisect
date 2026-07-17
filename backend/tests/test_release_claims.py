"""Bind public README claims to checked-in benchmark and stress evidence."""

from __future__ import annotations

import json
import re
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
    registry = (ROOT / "docs" / "specs" / "rule-registry-v1.md").read_text(
        encoding="utf-8"
    )
    landing = (ROOT / "frontend" / "src" / "app" / "page.tsx").read_text(
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

    forbidden_claims = (
        "confirmed misconception",
        "exact diagnosis",
        "educator-reviewed",
        "validated by educators",
        "has classroom adoption",
        "improves learning",
    )
    missing = [claim for claim in required_claims if claim not in normalized]
    present = [claim for claim in forbidden_claims if claim in lowered]
    assert not missing and not present, (
        f"missing public claims: {missing}; forbidden public claims: {present}"
    )

    confidence_claims = (
        r"\b\d+(?:\.\d+)?%\s+confidence\b",
        r"\bconfidence(?:\s+(?:score|level))?\s*(?:of|:|=)\s*\d",
        r"\b(?:high|medium|low)\s+confidence\b",
    )
    for pattern in confidence_claims:
        assert re.search(pattern, lowered) is None


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
