"""Opaque capability generation and purpose-separated hashing."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from base64 import urlsafe_b64encode
from uuid import UUID

SECRET_BYTES = 32
MIN_PEPPER_LENGTH = 32


def generate_secret() -> str:
    """Generate at least 256 bits of URL-safe entropy."""
    return secrets.token_urlsafe(SECRET_BYTES)


def generate_derivation_nonce() -> bytes:
    """Generate a fresh 256-bit nonce for replayable capability derivation."""
    return secrets.token_bytes(SECRET_BYTES)


def hash_secret(secret: str, pepper: str, *, purpose: str) -> str:
    """Hash a capability with HMAC-SHA-256 and an explicit purpose domain."""
    if len(pepper) < MIN_PEPPER_LENGTH:
        msg = "pepper must be at least 32 characters"
        raise ValueError(msg)
    if not secret or not purpose:
        msg = "secret and purpose are required"
        raise ValueError(msg)
    message = f"cognisect:{purpose}:v1\x00{secret}".encode()
    return hmac.new(pepper.encode(), message, hashlib.sha256).hexdigest()


def hash_payload(payload: bytes) -> str:
    """Return a deterministic request fingerprint without retaining request content."""
    return hashlib.sha256(payload).hexdigest()


def derive_learner_secret(token_id: UUID, derivation_nonce: bytes, pepper: str) -> str:
    """Derive a replayable capability from a token identity and fresh nonce."""
    if len(pepper) < MIN_PEPPER_LENGTH:
        msg = "pepper must be at least 32 characters"
        raise ValueError(msg)
    if len(derivation_nonce) != SECRET_BYTES:
        msg = "derivation nonce must be exactly 32 bytes"
        raise ValueError(msg)
    digest = hmac.new(
        pepper.encode(),
        b"cognisect:learner-token-secret:v2\x00" + token_id.bytes + derivation_nonce,
        hashlib.sha256,
    ).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode()


def secrets_match(left: str, right: str) -> bool:
    """Compare already-hashed secrets without timing-sensitive equality."""
    return hmac.compare_digest(left, right)
