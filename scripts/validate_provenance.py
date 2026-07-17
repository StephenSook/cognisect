"""Validate the checked-in public provenance ledger and frozen manifest."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cognisect.provenance import validate_evaluation_manifest, validate_provenance_ledger

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    """Fail closed on provenance, public-display, or split-policy drift."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ledger",
        type=Path,
        default=ROOT / "data" / "provenance" / "public-cases.v1.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "evaluation" / "manifest.v1.json",
    )
    args = parser.parse_args(argv)
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = validate_provenance_ledger(ledger)
    summary = validate_evaluation_manifest(manifest, provenance_records=records)
    print(
        f"validated {summary.record_count} records; "
        f"tiers={','.join(summary.tiers)}; splits={','.join(summary.splits)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
