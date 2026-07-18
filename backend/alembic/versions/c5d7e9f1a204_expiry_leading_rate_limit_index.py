"""Lead rate-limit cleanup lookups with expiry.

Revision ID: c5d7e9f1a204
Revises: f4c2d8a6b310
Create Date: 2026-07-17 16:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5d7e9f1a204"
down_revision: str | Sequence[str] | None = "f4c2d8a6b310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace the scope-leading index with the bounded-purge lookup index."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index(
        "ix_rate_limit_windows_scope_expires_at",
        table_name="rate_limit_windows",
    )
    op.create_index(
        "ix_rate_limit_windows_expires_at",
        "rate_limit_windows",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Restore the original scope-leading expiry index."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index(
        "ix_rate_limit_windows_expires_at",
        table_name="rate_limit_windows",
    )
    op.create_index(
        "ix_rate_limit_windows_scope_expires_at",
        "rate_limit_windows",
        ["scope", "expires_at"],
        unique=False,
    )
