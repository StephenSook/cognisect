"""Lock-wait safety contracts for Galaxy schema migrations."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "backend" / "alembic" / "versions"
MIGRATIONS = (
    "e3b1c7d9a205_case_provenance.py",
    "f4c2d8a6b310_rate_limit_windows.py",
    "c5d7e9f1a204_expiry_leading_rate_limit_index.py",
    "a5d3e9b7c421_model_response_identity.py",
)
LOCK_TIMEOUT_SQL = "SET LOCAL lock_timeout = '5s'"


class _RecordingOperations:
    """Record Alembic operations without requiring a database connection."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def execute(self, statement: object) -> None:
        self.events.append(("execute", str(statement)))

    def __getattr__(self, operation: str) -> Any:
        def record(*args: object, **kwargs: object) -> None:
            del args, kwargs
            self.events.append(("ddl", operation))

        return record


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("filename", MIGRATIONS)
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_galaxy_migration_bounds_lock_wait_before_ddl(
    filename: str,
    direction: str,
) -> None:
    module = _load_migration(filename)
    operations = _RecordingOperations()
    module.op = operations

    getattr(module, direction)()

    assert operations.events[0] == ("execute", LOCK_TIMEOUT_SQL)
    assert operations.events.count(("execute", LOCK_TIMEOUT_SQL)) == 1
    assert all(
        statement.startswith("SET LOCAL ")
        for kind, statement in operations.events
        if kind == "execute"
    )
    assert any(kind == "ddl" for kind, _ in operations.events[1:])
