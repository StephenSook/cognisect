"""Public provenance, leakage, and deterministic evaluation artifact contracts."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cognisect.provenance import (
    ProvenanceError,
    canonical_content_hash,
    validate_evaluation_manifest,
    validate_provenance_ledger,
)

ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = ROOT / "data" / "provenance" / "public-cases.v1.json"
MANIFEST_PATH = ROOT / "data" / "evaluation" / "manifest.v1.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_public_ledger_and_frozen_manifest_validate_together() -> None:
    ledger = _load(LEDGER_PATH)
    manifest = _load(MANIFEST_PATH)

    records = validate_provenance_ledger(ledger)
    summary = validate_evaluation_manifest(manifest, provenance_records=records)

    assert len(records) == 6
    assert summary.record_count == 6
    assert summary.tiers == ("educator_authored",)
    assert summary.splits == ("validation",)
    assert all(record.public_display_permitted for record in records.values())


def test_every_content_hash_is_canonical_and_reproducible() -> None:
    ledger = _load(LEDGER_PATH)

    for record in ledger["records"]:
        assert record["content_sha256"] == canonical_content_hash(record["content"])


def test_ledger_rejects_missing_fields_hash_drift_and_unknown_properties() -> None:
    ledger = _load(LEDGER_PATH)

    missing = copy.deepcopy(ledger)
    del missing["records"][0]["license"]
    with pytest.raises(ProvenanceError, match="record fields"):
        validate_provenance_ledger(missing)

    drifted = copy.deepcopy(ledger)
    drifted["records"][0]["content"]["observed_work"] = "changed"
    with pytest.raises(ProvenanceError, match="content hash"):
        validate_provenance_ledger(drifted)

    extra = copy.deepcopy(ledger)
    extra["records"][0]["student_name"] = "must never be accepted"
    with pytest.raises(ProvenanceError, match="record fields"):
        validate_provenance_ledger(extra)


def test_manifest_rejects_private_display_and_ancestry_split_leakage() -> None:
    ledger = _load(LEDGER_PATH)
    manifest = _load(MANIFEST_PATH)
    records = validate_provenance_ledger(ledger)

    private_ledger = copy.deepcopy(ledger)
    private_ledger["records"][0]["public_display_permitted"] = False
    private_records = validate_provenance_ledger(private_ledger)
    with pytest.raises(ProvenanceError, match="public display"):
        validate_evaluation_manifest(manifest, provenance_records=private_records)

    leaked = copy.deepcopy(manifest)
    leaked_record = copy.deepcopy(leaked["records"][0])
    leaked_record["manifest_id"] = "leaked-copy"
    leaked_record["split"] = "test"
    leaked["records"].append(leaked_record)
    with pytest.raises(ProvenanceError, match="source ancestry"):
        validate_evaluation_manifest(leaked, provenance_records=records)


def test_runtime_inputs_are_separate_from_evaluation_only_targets() -> None:
    manifest = _load(MANIFEST_PATH)

    for record in manifest["records"]:
        assert set(record["runtime_input"]) == {"problem", "observed_work", "source_tier"}
        assert "expected_template_ids" not in record["runtime_input"]
        assert set(record["evaluation_only"]) == {"expected_template_ids", "label_source"}
