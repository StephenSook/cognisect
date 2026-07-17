"""Strict public provenance and frozen evaluation-manifest validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from cognisect.interpreter import DOMAIN_VALUES, REGISTRY_TEMPLATE_IDS

LEDGER_SCHEMA_VERSION = "cognisect.provenance.v1"
MANIFEST_SCHEMA_VERSION = "cognisect.evaluation-manifest.v1"
ALLOWED_TIERS = {
    "authentic",
    "synthetic",
    "mixed",
    "published_exemplar",
    "educator_authored",
    "custom",
}
ALLOWED_AUTHENTICITY = {
    "authentic",
    "synthetic",
    "mixed",
    "published-exemplar",
    "educator-authored",
    "custom",
}
PROVENANCE_FIELDS = {
    "record_id",
    "source_url",
    "source_path",
    "license",
    "version",
    "created_at",
    "retrieved_at",
    "content_sha256",
    "tier",
    "authenticity",
    "transformation_history",
    "redistribution_permitted",
    "public_display_permitted",
    "label_source",
    "adjudication_status",
    "content",
}
MANIFEST_RECORD_FIELDS = {
    "manifest_id",
    "provenance_record_id",
    "question_id",
    "source_ancestry",
    "split",
    "tier",
    "runtime_input",
    "evaluation_only",
}
MIN_HYPOTHESES = 2
MAX_HYPOTHESES = 4


class ProvenanceError(ValueError):
    """Raised when public data custody or split policy fails closed."""


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    """Validated public-display provenance record."""

    record_id: str
    tier: str
    source_path: str
    content_sha256: str
    content: dict[str, Any]
    label_source: str
    redistribution_permitted: bool
    public_display_permitted: bool


@dataclass(frozen=True, slots=True)
class ManifestSummary:
    """Content-free summary of a validated frozen manifest."""

    record_count: int
    tiers: tuple[str, ...]
    splits: tuple[str, ...]


def _require_exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        msg = f"{label} fields do not match contract; missing={missing}, extra={extra}"
        raise ProvenanceError(msg)


def _require_nonempty_string(value: object, label: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        msg = f"{label} must be a non-empty bounded string"
        raise ProvenanceError(msg)
    return value


def _require_iso_date(value: object, label: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str):
        msg = f"{label} must be an ISO date"
        raise ProvenanceError(msg)
    try:
        date.fromisoformat(value)
    except ValueError as error:
        msg = f"{label} must be an ISO date"
        raise ProvenanceError(msg) from error


def canonical_content_hash(content: object) -> str:
    """Hash JSON content with stable key ordering and no insignificant whitespace."""
    canonical = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_content(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        msg = "content must be an object"
        raise ProvenanceError(msg)
    _require_exact_fields(value, {"problem", "observed_work"}, "content")
    problem = value["problem"]
    if not isinstance(problem, dict):
        msg = "content problem must be an object"
        raise ProvenanceError(msg)
    _require_exact_fields(problem, {"a", "b"}, "content problem")
    if any(type(problem[key]) is not int for key in ("a", "b")):
        msg = "content operands must be strict integers"
        raise ProvenanceError(msg)
    if any(problem[key] not in DOMAIN_VALUES for key in ("a", "b")):
        msg = "content operands must be in [-12, 12]"
        raise ProvenanceError(msg)
    _require_nonempty_string(value["observed_work"], "observed work", maximum=500)
    return value


def _validate_record_source(raw_record: dict[str, Any]) -> tuple[str, str, str]:
    record_id = _require_nonempty_string(raw_record["record_id"], "record ID", maximum=80)
    source_url = raw_record["source_url"]
    if source_url is not None:
        _require_nonempty_string(source_url, "source URL")
    source_path = _require_nonempty_string(raw_record["source_path"], "source path")
    _require_nonempty_string(raw_record["license"], "license", maximum=100)
    _require_nonempty_string(raw_record["version"], "version", maximum=80)
    _require_iso_date(raw_record["created_at"], "created_at")
    _require_iso_date(raw_record["retrieved_at"], "retrieved_at", nullable=True)
    label_source = _require_nonempty_string(raw_record["label_source"], "label source")
    return record_id, source_path, label_source


def _validate_record_labels(raw_record: dict[str, Any]) -> None:
    if raw_record["tier"] not in ALLOWED_TIERS:
        msg = "unknown provenance tier"
        raise ProvenanceError(msg)
    if raw_record["authenticity"] not in ALLOWED_AUTHENTICITY:
        msg = "unknown authenticity label"
        raise ProvenanceError(msg)
    _require_nonempty_string(
        raw_record["adjudication_status"], "adjudication status", maximum=100
    )


def _validate_history_and_permissions(raw_record: dict[str, Any]) -> None:
    history = raw_record["transformation_history"]
    if not isinstance(history, list) or not history:
        msg = "transformation history must be non-empty"
        raise ProvenanceError(msg)
    for entry in history:
        _require_nonempty_string(entry, "transformation history entry")
    for field in ("redistribution_permitted", "public_display_permitted"):
        if type(raw_record[field]) is not bool:
            msg = f"{field} must be a strict boolean"
            raise ProvenanceError(msg)


def _validated_provenance_record(raw_record: object) -> ProvenanceRecord:
    if not isinstance(raw_record, dict):
        msg = "provenance record must be an object"
        raise ProvenanceError(msg)
    _require_exact_fields(raw_record, PROVENANCE_FIELDS, "record")
    record_id, source_path, label_source = _validate_record_source(raw_record)
    _validate_record_labels(raw_record)
    _validate_history_and_permissions(raw_record)
    content = _validate_content(raw_record["content"])
    expected_hash = canonical_content_hash(content)
    if raw_record["content_sha256"] != expected_hash:
        msg = f"content hash mismatch for {record_id}"
        raise ProvenanceError(msg)
    return ProvenanceRecord(
        record_id=record_id,
        tier=raw_record["tier"],
        source_path=source_path,
        content_sha256=expected_hash,
        content=content,
        label_source=label_source,
        redistribution_permitted=raw_record["redistribution_permitted"],
        public_display_permitted=raw_record["public_display_permitted"],
    )


def validate_provenance_ledger(payload: object) -> dict[str, ProvenanceRecord]:
    """Validate a complete public ledger and return records keyed by stable ID."""
    if not isinstance(payload, dict):
        msg = "provenance ledger must be an object"
        raise ProvenanceError(msg)
    _require_exact_fields(payload, {"schema_version", "records"}, "ledger")
    if payload["schema_version"] != LEDGER_SCHEMA_VERSION:
        msg = "unsupported provenance schema version"
        raise ProvenanceError(msg)
    raw_records = payload["records"]
    if not isinstance(raw_records, list) or not raw_records:
        msg = "provenance ledger requires records"
        raise ProvenanceError(msg)

    records: dict[str, ProvenanceRecord] = {}
    for raw_record in raw_records:
        record = _validated_provenance_record(raw_record)
        if record.record_id in records:
            msg = "provenance record IDs must be unique"
            raise ProvenanceError(msg)
        records[record.record_id] = record
    return records


def _validate_frozen_at(value: object) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        msg = "frozen_at must be an explicit UTC timestamp"
        raise ProvenanceError(msg)
    try:
        datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        msg = "frozen_at must be an explicit UTC timestamp"
        raise ProvenanceError(msg) from error


def _validated_manifest_runtime_input(
    raw_input: object,
    provenance: ProvenanceRecord,
) -> None:
    if not isinstance(raw_input, dict):
        msg = "runtime input must be an object"
        raise ProvenanceError(msg)
    _require_exact_fields(
        raw_input,
        {"problem", "observed_work", "source_tier"},
        "runtime input",
    )
    expected_input = {
        "problem": provenance.content["problem"],
        "observed_work": provenance.content["observed_work"],
        "source_tier": provenance.tier,
    }
    if raw_input != expected_input:
        msg = "runtime input does not match provenance content"
        raise ProvenanceError(msg)


def _validate_manifest_target(raw_target: object, provenance: ProvenanceRecord) -> None:
    if not isinstance(raw_target, dict):
        msg = "evaluation-only target must be an object"
        raise ProvenanceError(msg)
    _require_exact_fields(
        raw_target,
        {"expected_template_ids", "label_source"},
        "evaluation-only target",
    )
    template_ids = raw_target["expected_template_ids"]
    if (
        not isinstance(template_ids, list)
        or not MIN_HYPOTHESES <= len(template_ids) <= MAX_HYPOTHESES
        or len(template_ids) != len(set(template_ids))
        or any(template_id not in REGISTRY_TEMPLATE_IDS for template_id in template_ids)
    ):
        msg = "evaluation-only template IDs violate the closed registry"
        raise ProvenanceError(msg)
    if raw_target["label_source"] != provenance.label_source:
        msg = "evaluation-only label source does not match provenance"
        raise ProvenanceError(msg)


def _validated_manifest_record(
    raw_record: object,
    provenance_records: dict[str, ProvenanceRecord],
) -> tuple[str, str, str, str, str]:
    if not isinstance(raw_record, dict):
        msg = "manifest record must be an object"
        raise ProvenanceError(msg)
    _require_exact_fields(raw_record, MANIFEST_RECORD_FIELDS, "manifest record")
    manifest_id = _require_nonempty_string(raw_record["manifest_id"], "manifest ID", maximum=80)
    provenance_id = _require_nonempty_string(
        raw_record["provenance_record_id"], "provenance record ID", maximum=80
    )
    provenance = provenance_records.get(provenance_id)
    if provenance is None:
        msg = "manifest references unknown provenance record"
        raise ProvenanceError(msg)
    if not provenance.public_display_permitted:
        msg = f"public display is not permitted for {provenance_id}"
        raise ProvenanceError(msg)
    if not provenance.redistribution_permitted:
        msg = f"redistribution is not permitted for {provenance_id}"
        raise ProvenanceError(msg)
    tier = _require_nonempty_string(raw_record["tier"], "manifest tier", maximum=80)
    if tier != provenance.tier:
        msg = "manifest tier does not match provenance"
        raise ProvenanceError(msg)
    split = _require_nonempty_string(raw_record["split"], "split", maximum=40)
    question_id = _require_nonempty_string(
        raw_record["question_id"], "question ID", maximum=100
    )
    ancestry = _require_nonempty_string(
        raw_record["source_ancestry"], "source ancestry", maximum=200
    )
    _validated_manifest_runtime_input(raw_record["runtime_input"], provenance)
    _validate_manifest_target(raw_record["evaluation_only"], provenance)
    return manifest_id, tier, split, question_id, ancestry


def validate_evaluation_manifest(
    payload: object,
    *,
    provenance_records: dict[str, ProvenanceRecord],
) -> ManifestSummary:
    """Validate a frozen manifest without exposing targets to runtime input."""
    if not isinstance(payload, dict):
        msg = "evaluation manifest must be an object"
        raise ProvenanceError(msg)
    _require_exact_fields(
        payload,
        {"schema_version", "frozen_at", "split_policy", "claim_scope", "records"},
        "manifest",
    )
    if payload["schema_version"] != MANIFEST_SCHEMA_VERSION:
        msg = "unsupported evaluation manifest schema version"
        raise ProvenanceError(msg)
    _validate_frozen_at(payload["frozen_at"])
    _require_nonempty_string(payload["split_policy"], "split policy")
    _require_nonempty_string(payload["claim_scope"], "claim scope")
    raw_records = payload["records"]
    if not isinstance(raw_records, list) or not raw_records:
        msg = "evaluation manifest requires records"
        raise ProvenanceError(msg)

    manifest_ids: set[str] = set()
    ancestry_splits: dict[str, set[str]] = {}
    question_splits: dict[str, set[str]] = {}
    tiers: set[str] = set()
    splits: set[str] = set()
    for raw_record in raw_records:
        manifest_id, tier, split, question_id, ancestry = _validated_manifest_record(
            raw_record,
            provenance_records,
        )
        if manifest_id in manifest_ids:
            msg = "manifest IDs must be unique"
            raise ProvenanceError(msg)
        manifest_ids.add(manifest_id)
        ancestry_splits.setdefault(ancestry, set()).add(split)
        question_splits.setdefault(question_id, set()).add(split)
        tiers.add(tier)
        splits.add(split)

    if any(len(values) > 1 for values in ancestry_splits.values()):
        msg = "source ancestry appears across evaluation splits"
        raise ProvenanceError(msg)
    if any(len(values) > 1 for values in question_splits.values()):
        msg = "question appears across evaluation splits"
        raise ProvenanceError(msg)
    return ManifestSummary(
        record_count=len(raw_records),
        tiers=tuple(sorted(tiers)),
        splits=tuple(sorted(splits)),
    )
