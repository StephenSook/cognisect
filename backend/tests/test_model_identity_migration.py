"""Exact schema migration contracts for provider response and request identity."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "a5d3e9b7c421_model_response_identity.py"
)


class _Operations:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def alter_column(self, table: str, column: str, **kwargs: object) -> None:
        self.events.append(("rename", table, column, kwargs.get("new_column_name")))

    def add_column(self, table: str, column: object) -> None:
        self.events.append(
            (
                "add",
                table,
                column.name,
                column.type.length,
                column.nullable,
            )
        )

    def drop_column(self, table: str, column: str) -> None:
        self.events.append(("drop", table, column))


def _module() -> object:
    assert MIGRATION.is_file(), "provider identity migration is required"
    spec = importlib.util.spec_from_file_location("model_response_identity", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_identity_migration_chain_and_upgrade_operations() -> None:
    module = _module()
    operations = _Operations()
    module.op = operations

    module.upgrade()

    assert module.revision == "a5d3e9b7c421"
    assert module.down_revision == "c5d7e9f1a204"
    assert operations.events == [
        ("rename", "workflows", "model_request_id", "model_response_id"),
        ("add", "workflows", "model_request_id", 160, True),
        ("rename", "model_calls", "request_id", "response_id"),
        ("add", "model_calls", "request_id", 160, True),
    ]


def test_model_identity_migration_downgrade_is_symmetric() -> None:
    module = _module()
    operations = _Operations()
    module.op = operations

    module.downgrade()

    assert operations.events == [
        ("drop", "model_calls", "request_id"),
        ("rename", "model_calls", "response_id", "request_id"),
        ("drop", "workflows", "model_request_id"),
        ("rename", "workflows", "model_response_id", "model_request_id"),
    ]
