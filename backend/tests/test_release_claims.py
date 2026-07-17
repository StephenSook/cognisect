"""Bind public release claims to checked-in benchmark and stress evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _json(relative_path: str) -> dict[str, Any]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_fact_sheet_claims_match_frozen_evidence() -> None:
    benchmark = _json("data/evaluation/benchmark-report.v1.json")
    stress = _json("data/security/production-stress-report.v1.json")
    security = _json("data/security/security-audit.v1.json")
    fact_sheet = (ROOT / "docs" / "FACT_SHEET.md").read_text(encoding="utf-8")

    terra = benchmark["model_comparison"]["terra"]
    sol = benchmark["model_comparison"]["sol"]
    verification = security["verification"]

    required_claims = {
        f"{benchmark['record_count']} educator-authored fixtures",
        f"{benchmark['model_calls_made']} live model calls",
        f"Terra exact set: {round(terra['metrics']['exact_set_rate'] * 6):d}/6",
        f"Sol exact set: {round(sol['metrics']['exact_set_rate'] * 6):d}/6",
        f"Total model cost: `${benchmark['telemetry']['total_cost_usd']}`",
        f"Learner responses collected: {benchmark['learner_responses_collected']}",
        f"{stress['concurrent_submissions']} concurrent submissions",
        (
            f"{stress['accepted_submissions']} accepted and "
            f"{stress['conflicting_submissions']} conflicted"
        ),
        f"{stress['pre_submit_gets']} pre-submit GETs",
        f"Exact replay: HTTP {stress['exact_replay_status']}",
        f"Post-deletion read: HTTP {stress['post_deletion_read_status']}",
        f"{verification['targeted_security_tests_passed']} targeted security tests passed",
        f"{verification['playwright_journeys_passed']} Playwright journeys passed",
        f"Tested preview SHA: `{stress['tested_release_sha']}`",
        "Educator usability review: not conducted",
    }
    assert required_claims <= set(fact_sheet.splitlines())


def test_submission_copy_preserves_claim_boundaries() -> None:
    submission = (ROOT / "docs" / "SUBMISSION_COPY.md").read_text(encoding="utf-8")
    lowered = submission.lower()
    normalized = " ".join(lowered.split())

    for required in (
        "six educator-authored fixtures",
        "zero learner responses",
        "not an accuracy estimate",
        "educator usability review has not been conducted",
        "one accepted submission and 49 conflicts",
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
