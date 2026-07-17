"""Atomic fixed-window abuse controls with HMAC-only persisted identifiers."""

from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognisect.db_models import RateLimitWindowRecord

MIN_PEPPER_LENGTH = 32
MAX_SCOPE_LENGTH = 64


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Privacy-safe outcome of one atomic quota consumption attempt."""

    allowed: bool
    retry_after_seconds: int


class PostgresRateLimiter:
    """Consume HMAC-keyed fixed-window quotas using one atomic Postgres upsert."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        abuse_key_pepper: SecretStr | str,
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
        self._sessions = session_factory
        self._pepper = raw_pepper.encode()

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
        """Delete expired buckets in a short transaction."""
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                delete(RateLimitWindowRecord).where(
                    RateLimitWindowRecord.expires_at <= datetime.now(UTC)
                )
            )
            return result.rowcount  # type: ignore[attr-defined, no-any-return]
