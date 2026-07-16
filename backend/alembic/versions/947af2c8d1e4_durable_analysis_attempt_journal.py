"""add durable analysis attempt journal

Revision ID: 947af2c8d1e4
Revises: 20eb6c8c7f3a
Create Date: 2026-07-16 15:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "947af2c8d1e4"
down_revision: str | Sequence[str] | None = "20eb6c8c7f3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add stable content-free attempts and separately staged validated artifacts."""
    for column in (
        sa.Column("attempt_ordinal", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=16), nullable=True),
        sa.Column("repair", sa.Boolean(), nullable=True),
        sa.Column("client_request_id", sa.String(length=64), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("model_calls", column)
    op.execute(
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY workflow_id ORDER BY created_at, id
            ) AS ordinal
            FROM model_calls
        )
        UPDATE model_calls AS calls SET
            attempt_ordinal = ranked.ordinal,
            purpose = 'legacy',
            repair = false,
            client_request_id = calls.id::text,
            finalized_at = calls.created_at
        FROM ranked WHERE calls.id = ranked.id
        """
    )
    for name in ("attempt_ordinal", "purpose", "repair", "client_request_id"):
        op.alter_column("model_calls", name, nullable=False)
    op.create_unique_constraint(
        "uq_model_calls_workflow_attempt_ordinal",
        "model_calls",
        ["workflow_id", "attempt_ordinal"],
    )
    op.create_table(
        "analysis_step_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("attempt_ordinal", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("schema_version", sa.String(length=48), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_id",
            "attempt_ordinal",
            name="uq_analysis_step_results_workflow_attempt_ordinal",
        ),
    )
    op.create_index(
        op.f("ix_analysis_step_results_workflow_id"),
        "analysis_step_results",
        ["workflow_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove staged artifacts and durable attempt identity."""
    op.drop_index(
        op.f("ix_analysis_step_results_workflow_id"),
        table_name="analysis_step_results",
    )
    op.drop_table("analysis_step_results")
    op.drop_constraint(
        "uq_model_calls_workflow_attempt_ordinal",
        "model_calls",
        type_="unique",
    )
    for name in reversed(
        ("attempt_ordinal", "purpose", "repair", "client_request_id", "finalized_at")
    ):
        op.drop_column("model_calls", name)
