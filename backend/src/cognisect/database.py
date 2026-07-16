"""Async Postgres engine and session construction."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create a Postgres-only SQLAlchemy async engine."""
    if not database_url.lower().startswith("postgresql+psycopg://"):
        msg = "COGNISECT requires postgresql+psycopg"
        raise ValueError(msg)
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create non-expiring async sessions for request-scoped transactions."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def session_dependency(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped session and always close it."""
    async with factory() as session:
        yield session
