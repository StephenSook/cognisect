"""Atomic Postgres abuse controls and privacy-safe route boundaries."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update

from cognisect.api import OWNER_COOKIE_NAME, create_app
from cognisect.config import Settings
from cognisect.database import create_session_factory
from cognisect.security import generate_secret


@pytest.fixture
def limited_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect",
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        abuse_key_pepper="a" * 32,
        public_app_url="http://localhost:3000",
        openai_api_key="",
        case_creation_limit_per_hour=2,
        analysis_limit_per_hour=1,
    )


def _case_payload() -> dict[str, object]:
    return {
        "source_tier": "custom",
        "problem": {"a": -3, "b": 5},
        "observed_work": "-3 - 5 = 2",
        "deidentified_attestation": True,
    }


@pytest.mark.postgres
async def test_atomic_concurrent_consumption_allows_exactly_the_configured_limit(
    db_engine, db_session
) -> None:
    del db_session
    from cognisect.db_models import RateLimitWindowRecord
    from cognisect.rate_limit import PostgresRateLimiter

    factory = create_session_factory(db_engine)
    limiter = PostgresRateLimiter(factory, abuse_key_pepper="a" * 32)

    decisions = await asyncio.gather(
        *(
            limiter.consume(
                scope="analysis",
                key_material="owner-capability-never-persist-this",
                limit=5,
                window_seconds=3_600,
            )
            for _ in range(24)
        )
    )

    assert sum(decision.allowed for decision in decisions) == 5
    assert all(1 <= decision.retry_after_seconds <= 3_600 for decision in decisions)
    async with factory() as session:
        row = await session.scalar(select(RateLimitWindowRecord))
        row_count = await session.scalar(select(func.count(RateLimitWindowRecord.bucket_hash)))
    assert row is not None
    assert row_count == 1
    assert row.consumed == 5
    assert re.fullmatch(r"[0-9a-f]{64}", row.bucket_hash)
    assert row.bucket_hash != "owner-capability-never-persist-this"


@pytest.mark.postgres
async def test_expired_limiter_buckets_are_purged(db_engine, db_session) -> None:
    del db_session
    from cognisect.db_models import RateLimitWindowRecord
    from cognisect.rate_limit import PostgresRateLimiter

    factory = create_session_factory(db_engine)
    limiter = PostgresRateLimiter(factory, abuse_key_pepper="a" * 32)
    await limiter.consume(
        scope="case_creation",
        key_material="203.0.113.9",
        limit=1,
        window_seconds=3_600,
    )
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    async with factory() as session, session.begin():
        await session.execute(
            update(RateLimitWindowRecord).values(expires_at=expired_at)
        )

    assert await limiter.purge_expired() == 1
    async with factory() as session:
        assert await session.scalar(select(func.count(RateLimitWindowRecord.bucket_hash))) == 0


@pytest.mark.postgres
async def test_case_bootstrap_attempts_are_bounded_and_429_is_privacy_safe(
    db_engine, db_session, limited_settings
) -> None:
    del db_session
    from cognisect.db_models import RateLimitWindowRecord

    factory = create_session_factory(db_engine)
    app = create_app(
        settings=limited_settings,
        session_factory=factory,
        analyzer=None,
    )
    transport = httpx.ASGITransport(app=app, client=("198.51.100.42", 43120))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        statuses: list[int] = []
        for index in range(3):
            client.cookies.clear()
            response = await client.post(
                "/v1/cases",
                headers={"Idempotency-Key": f"bootstrap-attempt-{index}"},
                json=_case_payload(),
            )
            statuses.append(response.status_code)
        limited = response

    assert statuses == [428, 428, 429]
    assert limited.json() == {"detail": "rate limit exceeded"}
    assert limited.headers["Retry-After"].isdigit()
    assert "198.51.100.42" not in limited.text
    async with factory() as session:
        persisted = list((await session.scalars(select(RateLimitWindowRecord.bucket_hash))).all())
    assert persisted
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in persisted)
    assert all("198.51.100.42" not in value for value in persisted)


@pytest.mark.postgres
async def test_analysis_is_bounded_by_owner_capability_without_persisting_it(
    db_engine, db_session, limited_settings
) -> None:
    del db_session
    from cognisect.db_models import RateLimitWindowRecord

    factory = create_session_factory(db_engine)
    app = create_app(
        settings=limited_settings.model_copy(
            update={"case_creation_limit_per_hour": 20}
        ),
        session_factory=factory,
        analyzer=None,
    )
    owner_secret = generate_secret()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        client.cookies.set(OWNER_COOKIE_NAME, owner_secret)
        created = await client.post(
            "/v1/cases",
            headers={"Idempotency-Key": "limited-owner-create"},
            json=_case_payload(),
        )
        case_id = created.json()["case_id"]
        first = await client.post(
            f"/v1/cases/{case_id}/analysis",
            headers={"Idempotency-Key": "limited-owner-analysis-one"},
            json={"expected_version": 0},
        )
        second = await client.post(
            f"/v1/cases/{case_id}/analysis",
            headers={"Idempotency-Key": "limited-owner-analysis-two"},
            json={"expected_version": 0},
        )

    assert first.status_code == 503
    assert second.status_code == 429
    assert second.json() == {"detail": "rate limit exceeded"}
    assert second.headers["Retry-After"].isdigit()
    async with factory() as session:
        persisted = list((await session.scalars(select(RateLimitWindowRecord.bucket_hash))).all())
    assert owner_secret not in persisted
    assert all(owner_secret not in value for value in persisted)
