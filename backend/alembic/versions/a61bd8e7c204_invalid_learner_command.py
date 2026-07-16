"""add invalid learner command receipt

Revision ID: a61bd8e7c204
Revises: 947af2c8d1e4
Create Date: 2026-07-16 16:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a61bd8e7c204"
down_revision: str | Sequence[str] | None = "947af2c8d1e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add one content-free invalid-answer receipt per learner token."""
    op.create_table(
        "invalid_learner_commands",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("learner_token_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["learner_token_id"], ["learner_tokens.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("learner_token_id"),
        sa.UniqueConstraint("workflow_id"),
    )


def downgrade() -> None:
    """Remove invalid-answer receipts."""
    op.drop_table("invalid_learner_commands")
