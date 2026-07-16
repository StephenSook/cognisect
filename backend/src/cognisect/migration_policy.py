"""Ownership boundary for application and externally managed database tables."""

from __future__ import annotations

from typing import Final

EXTERNALLY_MANAGED_TABLES: Final = frozenset(
    {
        "checkpoint_migrations",
        "checkpoints",
        "checkpoint_writes",
        "checkpoint_blobs",
    }
)


def include_alembic_name(
    name: str | None,
    type_: str,
    _parent_names: dict[str, str | None],
) -> bool:
    """Exclude only tables owned by LangGraph's explicit saver setup."""
    return not (type_ == "table" and name in EXTERNALLY_MANAGED_TABLES)
