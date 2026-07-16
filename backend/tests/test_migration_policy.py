"""Alembic ownership boundary for LangGraph-managed tables."""

from cognisect.migration_policy import (
    EXTERNALLY_MANAGED_TABLES,
    include_alembic_name,
)


def test_only_exact_langgraph_tables_are_excluded_from_autogenerate() -> None:
    assert {
        "checkpoint_migrations",
        "checkpoints",
        "checkpoint_writes",
        "checkpoint_blobs",
    } == EXTERNALLY_MANAGED_TABLES
    for table in EXTERNALLY_MANAGED_TABLES:
        assert not include_alembic_name(table, "table", {})

    assert include_alembic_name("unknown_extra_table", "table", {})
    assert include_alembic_name("workflows", "table", {})
    assert include_alembic_name("checkpoints_thread_id_idx", "index", {})
