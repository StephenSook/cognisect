"""Explicit checkpoint setup and fail-closed live model verification contracts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "cognisect_verify_models", ROOT / "scripts" / "verify_models.py"
)
assert SPEC is not None and SPEC.loader is not None
VERIFY_MODELS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFY_MODELS
SPEC.loader.exec_module(VERIFY_MODELS)


def test_live_verifier_is_not_run_without_both_flag_and_key(monkeypatch, capsys, tmp_path) -> None:
    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("network client must not be constructed")

    monkeypatch.setattr(VERIFY_MODELS, "AsyncOpenAI", forbidden_client)
    output = tmp_path / "must-not-exist.json"

    assert VERIFY_MODELS.main(["--output", str(output)], environ={"OPENAI_API_KEY": "key"}) == 0
    assert VERIFY_MODELS.main(["--live", "--output", str(output)], environ={}) == 0

    captured = capsys.readouterr().out
    assert captured.count("NOT RUN") == 2
    assert not output.exists()


def test_checkpoint_setup_is_explicit_and_migration_runs_it() -> None:
    setup = (ROOT / "scripts" / "setup_checkpoints.py").read_text()
    migrate = (ROOT / "scripts" / "migrate.sh").read_text()
    env_example = (ROOT / ".env.example").read_text()

    assert "await saver.setup()" in setup
    assert "secure_checkpoint_serializer()" in setup
    assert "alembic upgrade head" in migrate
    assert "setup_checkpoints.py" in migrate
    assert migrate.index("alembic upgrade head") < migrate.index("setup_checkpoints.py")
    assert "LANGGRAPH_STRICT_MSGPACK=true" in env_example


async def test_verifier_disables_retries_and_requires_nine_exact_valid_results(
    monkeypatch,
) -> None:
    constructor: dict[str, object] = {}
    requests: list[dict[str, object]] = []

    class Responses:
        async def parse(self, **kwargs):
            requests.append(kwargs)
            payload = json.loads(kwargs["input"])
            return SimpleNamespace(
                id=f"resp-{kwargs['model']}-{payload['sequence']}",
                model=kwargs["model"],
                output_parsed=VERIFY_MODELS.VerificationOutput(**payload),
            )

    class Client:
        responses = Responses()

        def __init__(self, **kwargs):
            constructor.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(VERIFY_MODELS, "AsyncOpenAI", Client)

    calls = await VERIFY_MODELS._verify("key")

    assert constructor["max_retries"] == 0
    assert constructor["timeout"] == 30.0
    assert len(requests) == len(calls) == 9
    assert all(call["structured_output_valid"] is True for call in calls)


def test_live_verifier_fails_closed_on_invalid_or_mismatched_result(
    monkeypatch, capsys, tmp_path
) -> None:
    class InvalidResponses:
        async def parse(self, **kwargs):
            payload = json.loads(kwargs["input"])
            return SimpleNamespace(
                id="resp-invalid",
                model="gpt-5.6-sol" if kwargs["model"] != "gpt-5.6-sol" else "wrong-model",
                output_parsed=SimpleNamespace(verified=False, sequence=payload["sequence"]),
            )

    class InvalidClient:
        responses = InvalidResponses()

        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(VERIFY_MODELS, "AsyncOpenAI", InvalidClient)
    output = tmp_path / "invalid-live.json"

    result = VERIFY_MODELS.main(
        ["--live", "--output", str(output)],
        environ={"OPENAI_API_KEY": "key"},
    )

    captured = capsys.readouterr().out
    assert result == 1
    assert "FAILED" in captured
    assert "PASSED" not in captured
    assert not output.exists()
