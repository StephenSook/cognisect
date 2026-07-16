#!/usr/bin/env python3
"""Create or migrate LangGraph checkpoint tables as an explicit release step."""

from __future__ import annotations

import asyncio
import os

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from cognisect.workflow_graph import (
    checkpoint_connection_url,
    secure_checkpoint_serializer,
)


async def setup_checkpoints(database_url: str) -> None:
    """Run the idempotent checkpointer DDL with strict serialization enabled."""
    async with AsyncPostgresSaver.from_conn_string(
        checkpoint_connection_url(database_url),
        serde=secure_checkpoint_serializer(),
    ) as saver:
        await saver.setup()


def main() -> int:
    """Read the release database URL and run explicit checkpoint setup."""
    database_url = os.environ.get("COGNISECT_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    asyncio.run(setup_checkpoints(database_url))
    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    raise SystemExit(main())
