"""Production-only retention scheduling contracts."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import cast

import httpx
import pytest
import structlog
from asgi_lifespan import LifespanManager

from cognisect.api import create_app
from cognisect.config import Settings
from cognisect.database import create_session_factory
from cognisect.services import GraphRuntime


def _settings(*, app_env: str) -> Settings:
    return Settings(
        app_env=app_env,
        database_url="postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect",
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        abuse_key_pepper="a" * 32,
        proxy_signing_secret="p" * 32,
        public_app_url=(
            "https://cognisect.example" if app_env == "production" else "http://localhost:3000"
        ),
        openai_api_key="sk-test-" + ("k" * 32) if app_env == "production" else "",
        retention_interval_seconds=21_600,
    )


@pytest.mark.postgres
async def test_production_retention_runs_immediately_repeats_and_survives_failure(
    db_engine, db_session, monkeypatch
) -> None:
    del db_session
    from cognisect.rate_limit import PostgresRateLimiter
    from cognisect.services import RetentionService

    attempts = 0
    repeated = asyncio.Event()
    sleep_gate = asyncio.Event()
    original_sleep = asyncio.sleep

    async def purge_cases(_self) -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("private retention failure")
        repeated.set()
        return 0

    async def purge_buckets(_self) -> int:
        return 0

    async def controlled_sleep(delay: float) -> None:
        assert delay == 21_600
        if attempts < 2:
            await original_sleep(0)
            return
        await sleep_gate.wait()

    monkeypatch.setattr(RetentionService, "purge_expired", purge_cases)
    monkeypatch.setattr(PostgresRateLimiter, "purge_expired", purge_buckets)
    monkeypatch.setattr("cognisect.api.asyncio.sleep", controlled_sleep)

    runtime = cast("GraphRuntime", object())
    app = create_app(
        settings=_settings(app_env="production"),
        session_factory=create_session_factory(db_engine),
        analyzer=None,
        graph_runtime=runtime,
    )
    with structlog.testing.capture_logs() as logs:
        async with LifespanManager(app):
            await asyncio.wait_for(repeated.wait(), timeout=1)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                assert (await client.get("/health")).json() == {"status": "ok"}
            assert app.state.graph_runtime is runtime

    assert attempts >= 2
    assert any(log.get("event") == "retention_iteration_failed" for log in logs)


@pytest.mark.postgres
async def test_production_retention_task_cancels_and_awaits_cleanly(
    db_engine, db_session, monkeypatch
) -> None:
    del db_session
    from cognisect.services import RetentionService

    started = asyncio.Event()
    cancelled = asyncio.Event()
    never = asyncio.Event()

    async def blocking_purge(_self) -> int:
        started.set()
        try:
            await never.wait()
        finally:
            cancelled.set()
        return 0

    monkeypatch.setattr(RetentionService, "purge_expired", blocking_purge)
    app = create_app(
        settings=_settings(app_env="production"),
        session_factory=create_session_factory(db_engine),
        analyzer=None,
        graph_runtime=cast("GraphRuntime", object()),
    )
    async with LifespanManager(app):
        await asyncio.wait_for(started.wait(), timeout=1)

    await asyncio.wait_for(cancelled.wait(), timeout=1)
    task = app.state.retention_task
    assert task.cancelled()
    with suppress(asyncio.CancelledError):
        await task


@pytest.mark.postgres
async def test_retention_task_does_not_run_outside_production(
    db_engine, db_session, monkeypatch
) -> None:
    del db_session
    from cognisect.services import RetentionService

    called = asyncio.Event()

    async def record_purge(_self) -> int:
        called.set()
        return 0

    monkeypatch.setattr(RetentionService, "purge_expired", record_purge)
    app = create_app(
        settings=_settings(app_env="test"),
        session_factory=create_session_factory(db_engine),
        analyzer=None,
        graph_runtime=cast("GraphRuntime", object()),
    )
    async with LifespanManager(app):
        await asyncio.sleep(0)

    assert not called.is_set()
    assert app.state.retention_task is None
