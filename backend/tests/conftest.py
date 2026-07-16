"""Shared deterministic and real-Postgres test configuration."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from alembic import command
from alembic.config import Config
from hypothesis import HealthCheck, settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from cognisect.database import create_engine, create_session_factory
from cognisect.db_models import Base, CaseRecord, OwnerRecord, WorkflowRecord

TEST_DATABASE_URL = os.environ.get(
    "COGNISECT_TEST_DATABASE_URL",
    "postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect",
)

settings.register_profile(
    "cognisect",
    max_examples=200,
    deadline=None,
    derandomize=True,
    suppress_health_check=(HealthCheck.too_slow,),
)
settings.load_profile("cognisect")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Upgrade the checked-in migration and expose the real Postgres engine."""
    if not TEST_DATABASE_URL.startswith("postgresql+psycopg://"):
        msg = "Postgres tests require postgresql+psycopg and never use SQLite"
        raise RuntimeError(msg)
    previous = os.environ.get("COGNISECT_DATABASE_URL")
    os.environ["COGNISECT_DATABASE_URL"] = TEST_DATABASE_URL
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous is None:
            os.environ.pop("COGNISECT_DATABASE_URL", None)
        else:
            os.environ["COGNISECT_DATABASE_URL"] = previous
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Provide a committed-capable isolated session backed by Postgres."""
    table_names = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
    async with db_engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
    factory = create_session_factory(db_engine)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def seeded_workflow(db_session: AsyncSession) -> tuple[WorkflowRecord, OwnerRecord]:
    """Persist one owned CREATED workflow."""
    owner = OwnerRecord(secret_hash="a" * 64)
    db_session.add(owner)
    await db_session.flush()
    case = CaseRecord(
        owner_id=owner.id,
        source_tier="custom",
        original_a=-3,
        original_b=5,
        observed_work="-3 - 5 = 2",
        deidentified_attestation=True,
    )
    db_session.add(case)
    await db_session.flush()
    workflow = WorkflowRecord(case_id=case.id, owner_id=owner.id)
    db_session.add(workflow)
    await db_session.commit()
    return workflow, owner
