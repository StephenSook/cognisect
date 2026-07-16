"""Explicit checkpoint setup and fail-closed live model verification contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "cognisect_verify_models", ROOT / "scripts" / "verify_models.py"
)
assert SPEC is not None and SPEC.loader is not None
VERIFY_MODELS = importlib.util.module_from_spec(SPEC)
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
