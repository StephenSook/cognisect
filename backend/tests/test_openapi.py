"""Frozen OpenAPI artifact drift contract."""

from __future__ import annotations

import json
from pathlib import Path

from cognisect.api import create_app
from cognisect.config import Settings

OPENAPI_PATH = Path(__file__).parents[2] / "openapi" / "openapi.json"


def test_generated_openapi_matches_frozen_artifact():
    settings = Settings(
        app_env="test",
        database_url="postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect",
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        public_app_url="http://localhost:3000",
        openai_api_key="",
    )
    generated = create_app(settings=settings, analyzer=None).openapi()
    frozen = json.loads(OPENAPI_PATH.read_text())
    assert generated == frozen
