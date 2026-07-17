#!/usr/bin/env python3
"""Run or verify the frozen, claim-limited COGNISECT model benchmark."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from dotenv import dotenv_values
from openai import AsyncOpenAI

from cognisect.benchmark import (
    BenchmarkModelResult,
    BenchmarkResponsesClient,
    build_live_benchmark_report,
    run_live_model_calls,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "data" / "evaluation" / "protocol.v1.json"
MANIFEST_PATH = ROOT / "data" / "evaluation" / "manifest.v1.json"
LEDGER_PATH = ROOT / "data" / "provenance" / "public-cases.v1.json"
PROMPT_SOURCE_PATH = ROOT / "backend" / "src" / "cognisect" / "prompts" / "analysis_v1.py"
REPORT_PATH = ROOT / "data" / "evaluation" / "benchmark-report.v1.json"
_EXPECTED_RECORD_COUNT = 6
_EXPECTED_MODEL_CALL_COUNT = 12
_MIN_API_KEY_LENGTH = 32
_FORBIDDEN_REPORT_KEYS = frozenset(
    {
        "api_key",
        "owner_secret",
        "learner_token",
        "observed_work",
        "answer",
        "response_url",
        "cookie",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        msg = "benchmark inputs must contain JSON objects"
        raise TypeError(msg)
    return value


def _validate_digest(entry: object, path: Path) -> None:
    if not isinstance(entry, Mapping) or entry.get("sha256") != _sha256(path):
        msg = "frozen evaluation input digest drifted"
        raise ValueError(msg)


def validate_frozen_inputs(
    protocol: Mapping[str, object],
    *,
    manifest_path: Path,
    ledger_path: Path,
    prompt_source_path: Path,
) -> None:
    """Fail before any provider call when a frozen input no longer matches."""
    _validate_digest(protocol.get("manifest"), manifest_path)
    _validate_digest(protocol.get("provenance_ledger"), ledger_path)
    _validate_digest(protocol.get("prompt_source"), prompt_source_path)


def _contains_forbidden_content(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in _FORBIDDEN_REPORT_KEYS or _contains_forbidden_content(nested)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_content(item) for item in value)
    return isinstance(value, str) and value.startswith("sk-")


def validate_checked_report(path: Path, *, expected_protocol_sha256: str) -> bool:
    """Validate that a persisted report is complete and content-safe."""
    try:
        report = _load_object(path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return bool(
        report.get("schema_version") == "cognisect.benchmark-report.v1"
        and report.get("record_count") == _EXPECTED_RECORD_COUNT
        and report.get("model_calls_made") == _EXPECTED_MODEL_CALL_COUNT
        and report.get("model_results_status") == "completed"
        and report.get("protocol_sha256") == expected_protocol_sha256
        and report.get("learner_responses_collected") == 0
        and not _contains_forbidden_content(report)
    )


def _api_key(environ: Mapping[str, str], env_file: Path | None) -> str:
    key = environ.get("OPENAI_API_KEY", "").strip()
    if not key and env_file is not None and env_file.exists():
        raw = dotenv_values(env_file).get("OPENAI_API_KEY")
        key = raw.strip() if isinstance(raw, str) else ""
    return key


async def _execute_live(
    api_key: str, manifest: Mapping[str, object]
) -> list[BenchmarkModelResult]:
    async with AsyncOpenAI(api_key=api_key, max_retries=0, timeout=60.0) as client:
        benchmark_client = cast("BenchmarkResponsesClient", client)
        return list(await run_live_model_calls(manifest, client=benchmark_client))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--prompt-source", type=Path, default=PROMPT_SOURCE_PATH)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run only with explicit authority, or verify an existing sanitized report."""
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    try:
        protocol = _load_object(args.protocol)
        validate_frozen_inputs(
            protocol,
            manifest_path=args.manifest,
            ledger_path=args.ledger,
            prompt_source_path=args.prompt_source,
        )
        protocol_sha256 = _sha256(args.protocol)
        if args.check:
            valid = validate_checked_report(
                args.output, expected_protocol_sha256=protocol_sha256
            )
            print("benchmark report verified" if valid else "benchmark report verification FAILED")
            return 0 if valid else 1
        key = _api_key(env, args.env_file)
        if not args.live or len(key) < _MIN_API_KEY_LENGTH:
            print("NOT RUN — pass --live with an explicit OPENAI_API_KEY")
            return 0
        manifest = _load_object(args.manifest)
        results = asyncio.run(_execute_live(key, manifest))
        report = build_live_benchmark_report(
            manifest,
            protocol_sha256=protocol_sha256,
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            model_results=results,
        )
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        if not validate_checked_report(
            args.output, expected_protocol_sha256=protocol_sha256
        ):
            args.output.unlink(missing_ok=True)
            print("FAILED — generated report did not pass content-safe validation")
            return 1
    except Exception:  # noqa: BLE001 - provider/input failures must not leak content.
        args.output.unlink(missing_ok=True)
        print("FAILED — benchmark gate did not produce a report")
        return 1
    print("PASSED — frozen benchmark report written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
