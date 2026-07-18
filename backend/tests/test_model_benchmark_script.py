"""Fail-closed command contracts for the frozen live benchmark."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "cognisect_run_model_benchmark", ROOT / "scripts" / "run_model_benchmark.py"
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


def test_benchmark_does_not_run_or_write_without_explicit_live_flag_and_key(
    monkeypatch, capsys, tmp_path
) -> None:
    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("provider client must not be constructed")

    monkeypatch.setattr(RUNNER, "AsyncOpenAI", forbidden_client)
    output = tmp_path / "must-not-exist.json"

    assert RUNNER.main(["--output", str(output)], environ={}) == 0
    assert RUNNER.main(["--live", "--output", str(output)], environ={}) == 0

    captured = capsys.readouterr().out
    assert captured.count("NOT RUN") == 2
    assert not output.exists()


def test_digest_drift_fails_before_constructing_provider_client(
    monkeypatch, tmp_path
) -> None:
    drifted_manifest = tmp_path / "manifest.json"
    drifted_manifest.write_text(
        (ROOT / "data" / "evaluation" / "manifest.v1.json").read_text() + " ",
        encoding="utf-8",
    )

    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("provider client must not be constructed after digest drift")

    monkeypatch.setattr(RUNNER, "AsyncOpenAI", forbidden_client)
    output = tmp_path / "must-not-exist.json"

    result = RUNNER.main(
        [
            "--live",
            "--manifest",
            str(drifted_manifest),
            "--output",
            str(output),
        ],
        environ={"OPENAI_API_KEY": "k" * 40},
    )

    assert result == 1
    assert not output.exists()


def test_checked_report_validator_rejects_secret_shaped_fields(tmp_path) -> None:
    report = {
        "schema_version": "cognisect.benchmark-report.v1",
        "record_count": 6,
        "model_calls_made": 12,
        "model_results_status": "completed",
        "protocol_sha256": "a" * 64,
        "api_key": "must-never-be-written",
    }
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    assert RUNNER.validate_checked_report(path, expected_protocol_sha256="a" * 64) is False


def test_checked_in_live_report_matches_the_frozen_protocol() -> None:
    protocol_hash = RUNNER._sha256(ROOT / "data" / "evaluation" / "protocol.v1.json")
    report = json.loads(
        (ROOT / "data" / "evaluation" / "benchmark-report.v1.json").read_text()
    )

    assert RUNNER.validate_checked_report(
        ROOT / "data" / "evaluation" / "benchmark-report.v1.json",
        expected_protocol_sha256=protocol_hash,
    )
    item_calls = [
        item[purpose]
        for item in report["items"]
        for purpose in ("terra", "sol")
    ]
    telemetry_calls = report["telemetry"]["calls"]
    for call in [*item_calls, *telemetry_calls]:
        assert call["response_id"].startswith("resp_")
        assert call["request_id"] is None


def test_checked_report_validator_rejects_response_ids_mislabeled_as_request_ids(
    tmp_path,
) -> None:
    report = json.loads(
        (ROOT / "data" / "evaluation" / "benchmark-report.v1.json").read_text()
    )
    report["telemetry"]["calls"][0].pop("response_id", None)
    report["telemetry"]["calls"][0]["request_id"] = "resp_mislabeled"
    path = tmp_path / "mislabeled.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    assert RUNNER.validate_checked_report(
        path,
        expected_protocol_sha256=report["protocol_sha256"],
    ) is False


def test_checked_report_validator_rejects_equal_response_and_request_ids(
    tmp_path,
) -> None:
    report = json.loads(
        (ROOT / "data" / "evaluation" / "benchmark-report.v1.json").read_text()
    )
    call = report["telemetry"]["calls"][0]
    call["request_id"] = call["response_id"]
    path = tmp_path / "conflated.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    assert RUNNER.validate_checked_report(
        path,
        expected_protocol_sha256=report["protocol_sha256"],
    ) is False
