"""Atomic Postgres abuse controls and privacy-safe route boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
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
        proxy_signing_secret="p" * 32,
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


def _signed_proxy_headers(
    bucket: str,
    *,
    timestamp: int | None = None,
    method: str = "POST",
    path: str = "/v1/cases",
) -> dict[str, str]:
    signed_at = timestamp or int(datetime.now(UTC).timestamp())
    message = "\n".join(
        ["cognisect:proxy-request:v1", str(signed_at), method, path, bucket]
    )
    signature = hmac.new(b"p" * 32, message.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Cognisect-Client-Bucket": bucket,
        "X-Cognisect-Proxy-Timestamp": str(signed_at),
        "X-Cognisect-Proxy-Signature": signature,
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
    limiter = PostgresRateLimiter(
        factory,
        abuse_key_pepper="a" * 32,
        purge_batch_size=2,
    )
    for suffix in range(5):
        await limiter.consume(
            scope="case_creation",
            key_material=f"203.0.113.{suffix}",
            limit=1,
            window_seconds=3_600,
        )
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    async with factory() as session, session.begin():
        await session.execute(
            update(RateLimitWindowRecord).values(expires_at=expired_at)
        )
    await limiter.consume(
        scope="analysis",
        key_material="live-owner-capability",
        limit=1,
        window_seconds=3_600,
    )

    assert await limiter.purge_expired() == 5
    async with factory() as session:
        assert await session.scalar(select(func.count(RateLimitWindowRecord.bucket_hash))) == 1


@pytest.mark.postgres
async def test_verified_proxy_bucket_is_shared_across_backend_socket_hosts(
    db_engine, db_session, limited_settings
) -> None:
    del db_session
    from cognisect.db_models import RateLimitWindowRecord

    factory = create_session_factory(db_engine)
    app = create_app(settings=limited_settings, session_factory=factory, analyzer=None)
    headers = {
        "Idempotency-Key": "signed-proxy-bootstrap",
        **_signed_proxy_headers("b" * 64),
    }
    statuses = []
    for host in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(host, 443)),
            base_url="http://testserver",
        ) as client:
            statuses.append(
                (await client.post("/v1/cases", headers=headers, json=_case_payload())).status_code
            )

    assert statuses == [428, 428, 429]
    async with factory() as session:
        rows = list((await session.scalars(select(RateLimitWindowRecord))).all())
    assert len(rows) == 1
    assert all(row.bucket_hash != "b" * 64 for row in rows)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "failure",
    [
        "partial",
        "invalid",
        "stale",
        "spoofed",
        "wrong_method",
        "wrong_path",
        "malformed_timestamp",
    ],
)
async def test_proxy_identity_fails_closed_without_consuming_quota(
    db_engine, db_session, limited_settings, failure: str
) -> None:
    del db_session
    from cognisect.db_models import OwnerRecord, RateLimitWindowRecord

    factory = create_session_factory(db_engine)
    app = create_app(settings=limited_settings, session_factory=factory, analyzer=None)
    headers = _signed_proxy_headers("c" * 64)
    if failure == "partial":
        headers = {"X-Cognisect-Client-Bucket": "c" * 64}
    elif failure == "invalid":
        headers["X-Cognisect-Proxy-Signature"] = "d" * 64
    elif failure == "stale":
        headers = _signed_proxy_headers(
            "c" * 64,
            timestamp=int(datetime.now(UTC).timestamp()) - 300,
        )
    elif failure == "spoofed":
        headers["X-Cognisect-Client-Bucket"] = "e" * 64
    elif failure == "wrong_method":
        headers = _signed_proxy_headers("c" * 64, method="GET")
    elif failure == "wrong_path":
        headers = _signed_proxy_headers("c" * 64, path="/v1/cases/other")
    else:
        headers["X-Cognisect-Proxy-Timestamp"] = "9" * 100
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/v1/cases",
            headers={"Idempotency-Key": f"proxy-{failure}", **headers},
            json=_case_payload(),
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid proxy identity"}
    async with factory() as session:
        assert await session.scalar(select(func.count(RateLimitWindowRecord.bucket_hash))) == 0
        assert await session.scalar(select(func.count(OwnerRecord.id))) == 0


@pytest.mark.postgres
async def test_direct_and_verified_proxy_key_material_are_domain_separated(
    db_engine, db_session, limited_settings
) -> None:
    del db_session
    from cognisect.db_models import RateLimitWindowRecord

    settings = limited_settings.model_copy(update={"case_creation_limit_per_hour": 10})
    factory = create_session_factory(db_engine)
    app = create_app(settings=settings, session_factory=factory, analyzer=None)
    shared_value = "f" * 64
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(shared_value, 443)),
        base_url="http://testserver",
    ) as client:
        direct = await client.post(
            "/v1/cases",
            headers={"Idempotency-Key": "domain-direct"},
            json=_case_payload(),
        )
        client.cookies.clear()
        proxied = await client.post(
            "/v1/cases",
            headers={
                "Idempotency-Key": "domain-proxy",
                **_signed_proxy_headers(shared_value),
            },
            json=_case_payload(),
        )

    assert direct.status_code == proxied.status_code == 428
    async with factory() as session:
        assert await session.scalar(select(func.count(RateLimitWindowRecord.bucket_hash))) == 2


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


@pytest.mark.postgres
async def test_invalid_rotating_owner_capabilities_create_no_analysis_limiter_rows(
    db_engine, db_session, limited_settings
) -> None:
    del db_session
    from cognisect.db_models import RateLimitWindowRecord

    factory = create_session_factory(db_engine)
    app = create_app(settings=limited_settings, session_factory=factory, analyzer=None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for index in range(5):
            client.cookies.set(OWNER_COOKIE_NAME, generate_secret())
            response = await client.post(
                "/v1/cases/00000000-0000-4000-8000-000000000001/analysis",
                headers={"Idempotency-Key": f"rotating-invalid-owner-{index}"},
                json={"expected_version": 0},
            )
            assert response.status_code == 404

    async with factory() as session:
        assert await session.scalar(select(func.count(RateLimitWindowRecord.bucket_hash))) == 0
