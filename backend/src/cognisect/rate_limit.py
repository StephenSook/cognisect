"""Atomic fixed-window abuse controls with HMAC-only persisted identifiers."""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import SecretStr
from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognisect.db_models import RateLimitWindowRecord

MIN_PEPPER_LENGTH = 32
MAX_SCOPE_LENGTH = 64
DEFAULT_PURGE_BATCH_SIZE = 500
MAX_PROXY_AGE_SECONDS = 60
PROXY_BUCKET_HEADER = "x-cognisect-client-bucket"
PROXY_TIMESTAMP_HEADER = "x-cognisect-proxy-timestamp"
PROXY_SIGNATURE_HEADER = "x-cognisect-proxy-signature"
PROXY_REQUEST_CONTEXT = "cognisect:proxy-request:v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Privacy-safe outcome of one atomic quota consumption attempt."""

    allowed: bool
    retry_after_seconds: int


class InvalidProxyIdentityError(ValueError):
    """A partial, stale, or unauthenticated proxy identity was supplied."""


def case_creation_key_material(
    headers: Mapping[str, str],
    *,
    method: str,
    path: str,
    client_host: str,
    proxy_signing_secret: SecretStr | str,
) -> str:
    """Return domain-separated direct or constant-time verified proxy identity."""
    bucket = headers.get(PROXY_BUCKET_HEADER)
    timestamp = headers.get(PROXY_TIMESTAMP_HEADER)
    signature = headers.get(PROXY_SIGNATURE_HEADER)
    if bucket is None and timestamp is None and signature is None:
        return f"direct-client\0{client_host}"
    if bucket is None or timestamp is None or signature is None:
        raise InvalidProxyIdentityError
    if (
        _SHA256_PATTERN.fullmatch(bucket) is None
        or _SHA256_PATTERN.fullmatch(signature) is None
        or not timestamp.isascii()
        or not timestamp.isdigit()
    ):
        raise InvalidProxyIdentityError
    try:
        signed_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (OverflowError, OSError, ValueError):
        raise InvalidProxyIdentityError from None
    reference = datetime.now(UTC)
    if abs((reference - signed_at).total_seconds()) > MAX_PROXY_AGE_SECONDS:
        raise InvalidProxyIdentityError
    raw_secret = (
        proxy_signing_secret.get_secret_value()
        if isinstance(proxy_signing_secret, SecretStr)
        else proxy_signing_secret
    )
    if len(raw_secret) < MIN_PEPPER_LENGTH:
        raise InvalidProxyIdentityError
    message = f"{PROXY_REQUEST_CONTEXT}\n{timestamp}\n{method.upper()}\n{path}\n{bucket}"
    expected = hmac.new(raw_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(signature, expected):
        raise InvalidProxyIdentityError
    return f"verified-proxy-bucket\0{bucket}"


class PostgresRateLimiter:
    """Consume HMAC-keyed fixed-window quotas using one atomic Postgres upsert."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        abuse_key_pepper: SecretStr | str,
        purge_batch_size: int = DEFAULT_PURGE_BATCH_SIZE,
    ) -> None:
        """Keep the dedicated abuse pepper only in process memory."""
        raw_pepper = (
            abuse_key_pepper.get_secret_value()
            if isinstance(abuse_key_pepper, SecretStr)
            else abuse_key_pepper
        )
        if len(raw_pepper) < MIN_PEPPER_LENGTH:
            msg = "abuse_key_pepper must contain at least 32 characters"
            raise ValueError(msg)
        if purge_batch_size < 1:
            msg = "purge_batch_size must be positive"
            raise ValueError(msg)
        self._sessions = session_factory
        self._pepper = raw_pepper.encode()
        self._purge_batch_size = purge_batch_size

    def _bucket_hash(self, scope: str, key_material: str) -> str:
        message = scope.encode() + b"\0" + key_material.encode()
        return hmac.new(self._pepper, message, hashlib.sha256).hexdigest()

    async def consume(
        self,
        scope: str,
        key_material: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        """Atomically increment a fixed-window counter if capacity remains."""
        if not 1 <= len(scope) <= MAX_SCOPE_LENGTH or not key_material:
            msg = "scope and key_material must be non-empty and bounded"
            raise ValueError(msg)
        if limit < 1 or window_seconds < 1:
            msg = "limit and window_seconds must be positive"
            raise ValueError(msg)

        now = datetime.now(UTC)
        window_epoch = (int(now.timestamp()) // window_seconds) * window_seconds
        window_started_at = datetime.fromtimestamp(window_epoch, tz=UTC)
        expires_at = window_started_at + timedelta(seconds=window_seconds)
        statement = (
            pg_insert(RateLimitWindowRecord)
            .values(
                scope=scope,
                bucket_hash=self._bucket_hash(scope, key_material),
                window_started_at=window_started_at,
                consumed=1,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                index_elements=(
                    RateLimitWindowRecord.scope,
                    RateLimitWindowRecord.bucket_hash,
                    RateLimitWindowRecord.window_started_at,
                ),
                set_={"consumed": RateLimitWindowRecord.consumed + 1},
                where=RateLimitWindowRecord.consumed < limit,
            )
            .returning(RateLimitWindowRecord.consumed)
        )
        async with self._sessions() as session, session.begin():
            consumed = await session.scalar(statement)
        retry_after = max(1, math.ceil((expires_at - now).total_seconds()))
        return RateLimitDecision(
            allowed=consumed is not None,
            retry_after_seconds=retry_after,
        )

    async def purge_expired(self) -> int:
        """Drain expired buckets in bounded, skip-locked short transactions."""
        reference = datetime.now(UTC)
        purged = 0
        while True:
            async with self._sessions() as session, session.begin():
                keys = (
                    await session.execute(
                        select(
                            RateLimitWindowRecord.scope,
                            RateLimitWindowRecord.bucket_hash,
                            RateLimitWindowRecord.window_started_at,
                        )
                        .where(RateLimitWindowRecord.expires_at <= reference)
                        .order_by(
                            RateLimitWindowRecord.expires_at,
                            RateLimitWindowRecord.scope,
                            RateLimitWindowRecord.bucket_hash,
                            RateLimitWindowRecord.window_started_at,
                        )
                        .limit(self._purge_batch_size)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
                if not keys:
                    return purged
                await session.execute(
                    delete(RateLimitWindowRecord).where(
                        tuple_(
                            RateLimitWindowRecord.scope,
                            RateLimitWindowRecord.bucket_hash,
                            RateLimitWindowRecord.window_started_at,
                        ).in_(keys)
                    )
                )
                purged += len(keys)
