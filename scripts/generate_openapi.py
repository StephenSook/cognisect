#!/usr/bin/env python3
"""Generate the frozen OpenAPI contract from the real application factory."""

from __future__ import annotations

import json
from pathlib import Path

from cognisect.api import create_app
from cognisect.config import Settings

ROOT = Path(__file__).parents[1]
OUTPUT = ROOT / "openapi" / "openapi.json"


def main() -> None:
    """Write stable, sorted, UTF-8 OpenAPI JSON."""
    settings = Settings(
        app_env="test",
        database_url="postgresql+psycopg://openapi:openapi@postgres:5432/openapi",
        owner_secret_pepper="openapi-owner-pepper-value-32chars",
        learner_token_pepper="openapi-learner-pepper-value-32ch",
        public_app_url="https://cognisect.example",
        openai_api_key="",
    )
    schema = create_app(settings=settings, analyzer=None).openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
