"""Frozen release benchmark protocol contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cognisect.interpreter import COMPILER_VERSION, REGISTRY_VERSION
from cognisect.model_policy import MODEL_IDS, ROUTE_VERSION
from cognisect.prompts.analysis_v1 import PROMPT_VERSION

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = ROOT / "data" / "evaluation" / "protocol.v1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_release_benchmark_protocol_freezes_all_inputs_before_live_calls() -> None:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))

    assert protocol["schema_version"] == "cognisect.evaluation-protocol.v1"
    assert protocol["frozen_at"] == "2026-07-17T05:30:00Z"
    assert protocol["record_count"] == 6
    assert protocol["tiers"] == {"educator_authored": 6}
    assert protocol["learner_response_count"] == 0
    assert protocol["manifest"] == {
        "path": "data/evaluation/manifest.v1.json",
        "sha256": _sha256(ROOT / "data" / "evaluation" / "manifest.v1.json"),
    }
    assert protocol["provenance_ledger"] == {
        "path": "data/provenance/public-cases.v1.json",
        "sha256": _sha256(ROOT / "data" / "provenance" / "public-cases.v1.json"),
    }
    assert protocol["prompt_source"] == {
        "path": "backend/src/cognisect/prompts/analysis_v1.py",
        "sha256": _sha256(ROOT / "backend" / "src" / "cognisect" / "prompts" / "analysis_v1.py"),
        "version": PROMPT_VERSION,
    }
    assert protocol["registry_version"] == REGISTRY_VERSION
    assert protocol["compiler_version"] == COMPILER_VERSION
    assert protocol["route_version"] == ROUTE_VERSION
    assert protocol["model_ids"] == MODEL_IDS
    assert protocol["max_model_calls_per_record"] == 2
    assert protocol["comparisons"] == [
        "leave_one_question_out_majority_label",
        "direct_gpt_5_6_structured_classification",
        "gpt_5_6_hypothesis_mapping_without_compiler",
        "gpt_5_6_plus_compiler_without_learner_response",
        "full_interactive_workflow",
    ]
    assert protocol["full_interactive_workflow_status"] == (
        "NOT RUN — no real learner responses were collected"
    )
    assert "educator-authored" in protocol["claim_scope"]
    assert "no model-accuracy generalization" in protocol["claim_scope"].lower()
