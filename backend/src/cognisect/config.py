"""Strict runtime settings with no demo or authentication-bypass mode."""

from __future__ import annotations

import ipaddress
from contextlib import suppress
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_PARTS = ("replace-with", "placeholder", "change-me", "changeme")
MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Validated application settings; production fails closed."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str
    owner_secret_pepper: SecretStr
    learner_token_pepper: SecretStr
    public_app_url: str
    openai_api_key: SecretStr = SecretStr("")
    retention_days: int = Field(default=30, ge=1, le=365)
    max_model_calls_per_case: int = Field(default=3, ge=1, le=3)
    max_model_cost_usd: float = Field(default=1.0, gt=0)
    model_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    model_luna: Literal["gpt-5.6-luna"] = "gpt-5.6-luna"
    model_terra: Literal["gpt-5.6-terra"] = "gpt-5.6-terra"
    model_sol: Literal["gpt-5.6-sol"] = "gpt-5.6-sol"
    langgraph_strict_msgpack: Literal[True] = True

    @field_validator("langgraph_strict_msgpack", mode="before")
    @classmethod
    def strict_msgpack_accepts_true_environment_string(cls, value: object) -> object:
        """Normalize the only permitted environment-string representation."""
        if isinstance(value, str) and value.strip().lower() == "true":
            return True
        return value

    @field_validator("database_url")
    @classmethod
    def database_is_explicit_async_postgres(cls, value: str) -> str:
        """Reject missing, placeholder, SQLite, and non-psycopg database URLs."""
        normalized = value.strip()
        lowered = normalized.lower()
        if not normalized or any(part in lowered for part in _PLACEHOLDER_PARTS):
            msg = "DATABASE_URL must be explicit"
            raise ValueError(msg)
        if not lowered.startswith("postgresql+psycopg://"):
            msg = "DATABASE_URL must use postgresql+psycopg"
            raise ValueError(msg)
        parsed = urlparse(normalized)
        if not parsed.hostname or not parsed.path.strip("/"):
            msg = "DATABASE_URL must include a host and database"
            raise ValueError(msg)
        return normalized

    @field_validator("owner_secret_pepper", "learner_token_pepper")
    @classmethod
    def pepper_is_explicit_and_long(cls, value: SecretStr) -> SecretStr:
        """Require purpose-specific, non-placeholder peppers of at least 32 characters."""
        raw = value.get_secret_value()
        lowered = raw.lower()
        if len(raw) < MIN_SECRET_LENGTH or any(
            part in lowered for part in _PLACEHOLDER_PARTS
        ):
            msg = "secret peppers must be explicit and at least 32 characters"
            raise ValueError(msg)
        return value

    @field_validator("public_app_url")
    @classmethod
    def public_url_is_http(cls, value: str) -> str:
        """Require an absolute HTTP(S) application URL."""
        normalized = value.rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            msg = "PUBLIC_APP_URL must be an absolute HTTP(S) URL"
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def production_fails_closed(self) -> Self:
        """Apply production-only public-origin and OpenAI credential requirements."""
        if self.app_env != "production":
            return self
        parsed = urlparse(self.public_app_url)
        hostname = parsed.hostname or ""
        is_loopback = hostname.lower() == "localhost"
        with suppress(ValueError):
            is_loopback = is_loopback or ipaddress.ip_address(hostname).is_loopback
        if parsed.scheme != "https" or is_loopback:
            msg = "production PUBLIC_APP_URL must be non-local HTTPS"
            raise ValueError(msg)
        api_key = self.openai_api_key.get_secret_value().strip()
        if len(api_key) < MIN_SECRET_LENGTH or any(
            part in api_key.lower() for part in _PLACEHOLDER_PARTS
        ):
            msg = "OPENAI_API_KEY must be explicit and at least 32 characters in production"
            raise ValueError(msg)
        return self


def is_production(settings: Settings) -> bool:
    """Return whether cookie and transport hardening must use production policy."""
    return settings.app_env == "production"
