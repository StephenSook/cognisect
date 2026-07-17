"""Deterministic public-fixture evaluation harness contracts."""

from __future__ import annotations

import json
from pathlib import Path

from cognisect.offline_evaluation import run_public_fixture_evaluation

ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = ROOT / "data" / "provenance" / "public-cases.v1.json"
MANIFEST_PATH = ROOT / "data" / "evaluation" / "manifest.v1.json"
REPORT_PATH = ROOT / "data" / "evaluation" / "report.v1.json"


def test_public_fixture_evaluation_is_reproducible_and_claim_limited() -> None:
    first = run_public_fixture_evaluation(LEDGER_PATH, MANIFEST_PATH)
    second = run_public_fixture_evaluation(LEDGER_PATH, MANIFEST_PATH)

    assert first == second
    assert first["schema_version"] == "cognisect.evaluation-report.v1"
    assert first["evaluation_kind"] == "deterministic_fixture_harness"
    assert first["model_calls_made"] == 0
    assert first["learner_responses_collected"] == 0
    assert first["record_count"] == 6
    assert first["tiers"] == {"educator_authored": 6}
    assert first["metrics"] == {
        "registry_acceptance_rate": 1.0,
        "unique_semantic_rule_rate": 1.0,
        "separating_probe_rate": 1.0,
        "deterministic_reproduction_rate": 1.0,
        "abstention_rate": 0.0,
    }
    assert len(first["item_results"]) == 6
    assert all(item["probe_specification_hash"] for item in first["item_results"])
    assert "no model-accuracy" in first["claim_scope"].lower()
    assert "accuracy_metric" not in json.dumps(first).lower()
    assert "diagnos" not in json.dumps(first).lower()


def test_checked_in_report_matches_the_frozen_manifest() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report == run_public_fixture_evaluation(LEDGER_PATH, MANIFEST_PATH)
