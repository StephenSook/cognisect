"""add content-free model telemetry

Revision ID: 20eb6c8c7f3a
Revises: b69c7b913125
Create Date: 2026-07-16 12:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20eb6c8c7f3a"
down_revision: str | Sequence[str] | None = "b69c7b913125"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add bounded telemetry columns without retaining request or response content."""
    columns = (
        sa.Column("requested_model_id", sa.String(length=120), nullable=True),
        sa.Column("returned_model_id", sa.String(length=120), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_input_tokens", sa.Integer(), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("route_version", sa.String(length=48), nullable=True),
        sa.Column("prompt_cache_key", sa.String(length=120), nullable=True),
    )
    for column in columns:
        op.add_column("model_calls", column)
    op.execute(
        """
        UPDATE model_calls SET
            requested_model_id = model_id,
            returned_model_id = COALESCE(model_snapshot, model_id),
            latency_ms = 0,
            input_tokens = 0,
            output_tokens = 0,
            reasoning_tokens = 0,
            cached_input_tokens = 0,
            cache_write_input_tokens = 0,
            prompt_hash = repeat('0', 64),
            route_version = 'legacy.task2',
            prompt_cache_key = 'legacy.task2'
        """
    )
    for name in (
        "requested_model_id",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "prompt_hash",
        "route_version",
        "prompt_cache_key",
    ):
        op.alter_column("model_calls", name, nullable=False)
    op.create_check_constraint(
        "ck_model_calls_nonnegative_counts",
        "model_calls",
        "latency_ms >= 0 AND input_tokens >= 0 AND output_tokens >= 0 "
        "AND reasoning_tokens >= 0 AND cached_input_tokens >= 0 "
        "AND cache_write_input_tokens >= 0",
    )


def downgrade() -> None:
    """Remove Task 3 model telemetry columns."""
    op.drop_constraint("ck_model_calls_nonnegative_counts", "model_calls", type_="check")
    for name in reversed(
        (
            "requested_model_id",
            "returned_model_id",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "prompt_hash",
            "route_version",
            "prompt_cache_key",
        )
    ):
        op.drop_column("model_calls", name)
