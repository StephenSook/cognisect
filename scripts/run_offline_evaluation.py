"""Emit a reproducible deterministic public-fixture evaluation report."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cognisect.offline_evaluation import run_public_fixture_evaluation

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "data" / "evaluation" / "report.v1.json"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the claim-limited harness and optionally persist its JSON output."""
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
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    report = run_public_fixture_evaluation(args.ledger, args.manifest)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.check:
        if args.output is not None:
            parser.error("--check and --output cannot be combined")
        if not REPORT_PATH.exists() or REPORT_PATH.read_text(encoding="utf-8") != rendered:
            print("offline evaluation report is out of date")
            return 1
        print("offline evaluation report matches the frozen manifest")
        return 0
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
