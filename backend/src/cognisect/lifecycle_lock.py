"""Cross-process serialization for graph/checkpoint and content lifecycle work."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def lifecycle_lock_key(thread_id: UUID) -> int:
    """Map a UUID deterministically into PostgreSQL's signed bigint lock space."""
    return int.from_bytes(thread_id.bytes[:8], byteorder="big", signed=True)


async def acquire_lifecycle_lock(session: AsyncSession, thread_id: UUID) -> None:
    """Hold one transaction-scoped advisory lock until the caller commits or rolls back."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": lifecycle_lock_key(thread_id)},
    )
