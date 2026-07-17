"""Add HMAC-keyed atomic rate-limit windows.

Revision ID: f4c2d8a6b310
Revises: e3b1c7d9a205
Create Date: 2026-07-17 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4c2d8a6b310"
down_revision: str | Sequence[str] | None = "e3b1c7d9a205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create privacy-safe fixed-window counters and expiry lookup index."""
    op.create_table(
        "rate_limit_windows",
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("bucket_hash", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(scope) BETWEEN 1 AND 64",
            name="ck_rate_limit_windows_scope",
        ),
        sa.CheckConstraint(
            "bucket_hash ~ '^[0-9a-f]{64}$'",
            name="ck_rate_limit_windows_bucket_hash",
        ),
        sa.CheckConstraint("consumed >= 1", name="ck_rate_limit_windows_consumed"),
        sa.CheckConstraint(
            "expires_at > window_started_at",
            name="ck_rate_limit_windows_expiry",
        ),
        sa.PrimaryKeyConstraint(
            "scope",
            "bucket_hash",
            "window_started_at",
            name="pk_rate_limit_windows",
        ),
    )
    op.create_index(
        "ix_rate_limit_windows_scope_expires_at",
        "rate_limit_windows",
        ["scope", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop atomic rate-limit counters."""
    op.drop_index(
        "ix_rate_limit_windows_scope_expires_at",
        table_name="rate_limit_windows",
    )
    op.drop_table("rate_limit_windows")
