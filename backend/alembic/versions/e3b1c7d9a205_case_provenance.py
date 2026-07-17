"""Add nullable case provenance.

Revision ID: e3b1c7d9a205
Revises: a61bd8e7c204
Create Date: 2026-07-17 06:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b1c7d9a205"
down_revision: str | Sequence[str] | None = "a61bd8e7c204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add optional provenance without inferring values for existing cases."""
    op.add_column(
        "cases",
        sa.Column("provenance_record_id", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    """Remove optional case provenance."""
    op.drop_column("cases", "provenance_record_id")
