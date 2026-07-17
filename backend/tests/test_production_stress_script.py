"""Production stress command and content-safe report contracts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "cognisect_run_production_stress", ROOT / "scripts" / "run_production_stress.py"
)
assert SPEC is not None and SPEC.loader is not None
STRESS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = STRESS
SPEC.loader.exec_module(STRESS)


@pytest.mark.asyncio
async def test_fifty_way_race_uses_distinct_keys_and_requires_one_acceptance() -> None:
    keys: list[str] = []
    winner_receipt = str(uuid4())

    async def post(key: str) -> httpx.Response:
        keys.append(key)
        if len(keys) == 1:
            return httpx.Response(200, json={"receipt_id": winner_receipt})
        return httpx.Response(409, json={"detail": "response already recorded"})

    result = await STRESS.submit_learner_race(post, concurrency=50)

    assert len(keys) == len(set(keys)) == 50
    assert result.accepted_count == 1
    assert result.conflict_count == 49
    assert result.winning_receipt_id == winner_receipt
    assert result.winning_idempotency_key in keys


@pytest.mark.asyncio
async def test_race_fails_closed_when_more_than_one_submission_is_accepted() -> None:
    async def post(_key: str) -> httpx.Response:
        return httpx.Response(200, json={"receipt_id": str(uuid4())})

    with pytest.raises(RuntimeError, match="exactly one accepted response"):
        await STRESS.submit_learner_race(post, concurrency=50)


def test_stress_does_not_run_without_all_explicit_live_authority(
    monkeypatch, capsys, tmp_path
) -> None:
    async def forbidden_run(**_kwargs):
        raise AssertionError("network stress must not run")

    monkeypatch.setattr(STRESS, "run_live_stress", forbidden_run)
    output = tmp_path / "must-not-exist.json"
    sha = "a" * 40

    assert STRESS.main(["--output", str(output)]) == 0
    assert (
        STRESS.main(
            ["--live", "--tested-release-sha", sha, "--output", str(output)]
        )
        == 0
    )

    captured = capsys.readouterr().out
    assert captured.count("NOT RUN") == 2
    assert not output.exists()


def test_report_validation_rejects_capability_or_content_fields(tmp_path) -> None:
    report = STRESS.expected_report_shape(tested_release_sha="a" * 40)
    report["learner_token"] = "must-never-persist"  # noqa: S105
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    assert STRESS.validate_stress_report(path) is False


def test_checked_in_production_stress_report_is_content_safe() -> None:
    assert STRESS.validate_stress_report(
        ROOT / "data" / "security" / "production-stress-report.v1.json"
    )


@pytest.mark.parametrize(
    ("base_url", "sha"),
    [
        ("http://cognisect.example", "a" * 40),
        ("https://localhost", "a" * 40),
        ("https://cognisect.example", "short"),
    ],
)
def test_live_target_requires_public_https_and_full_git_sha(base_url, sha) -> None:
    with pytest.raises(ValueError, match="production stress"):
        STRESS.validate_live_target(base_url, sha)
