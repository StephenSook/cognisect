"""separate provider response and request identity

Revision ID: a5d3e9b7c421
Revises: c5d7e9f1a204
Create Date: 2026-07-17 18:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a5d3e9b7c421"
down_revision: str | Sequence[str] | None = "c5d7e9f1a204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Relabel historical response IDs and add nullable provider request IDs."""
    op.alter_column(
        "workflows",
        "model_request_id",
        new_column_name="model_response_id",
        existing_type=sa.String(length=160),
        existing_nullable=True,
    )
    op.add_column(
        "workflows",
        sa.Column("model_request_id", sa.String(length=160), nullable=True),
    )
    op.alter_column(
        "model_calls",
        "request_id",
        new_column_name="response_id",
        existing_type=sa.String(length=160),
        existing_nullable=True,
    )
    op.add_column(
        "model_calls",
        sa.Column("request_id", sa.String(length=160), nullable=True),
    )


def downgrade() -> None:
    """Drop provider request IDs and restore the legacy response-ID labels."""
    op.drop_column("model_calls", "request_id")
    op.alter_column(
        "model_calls",
        "response_id",
        new_column_name="request_id",
        existing_type=sa.String(length=160),
        existing_nullable=True,
    )
    op.drop_column("workflows", "model_request_id")
    op.alter_column(
        "workflows",
        "model_response_id",
        new_column_name="model_request_id",
        existing_type=sa.String(length=160),
        existing_nullable=True,
    )
