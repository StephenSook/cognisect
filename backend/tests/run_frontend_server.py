"""Test-only real-Postgres API launcher for the frontend Playwright loop."""

from __future__ import annotations

import os
from collections.abc import MutableMapping

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from cognisect.api import create_app
from cognisect.config import Settings
from cognisect.models import RuleInstanceV1, RuleMappingV1
from cognisect.services import AnalysisInput, AnalyzerResult

TEST_DATABASE_URL = (
    "postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect"
)


def _require_local_test_database(database_url: str) -> None:
    """Refuse to reset anything except the checked-in localhost test database."""
    parsed = make_url(database_url)
    expected = make_url(TEST_DATABASE_URL)
    if parsed != expected:
        msg = "frontend harness database reset is restricted to the local test database"
        raise RuntimeError(msg)


def _guard_migration_environment(environment: MutableMapping[str, str]) -> None:
    """Reject inherited Alembic overrides, then force the exact test URL."""
    for name in ("COGNISECT_DATABASE_URL", "DATABASE_URL"):
        inherited = environment.get(name)
        if inherited is not None:
            _require_local_test_database(inherited)
    environment["COGNISECT_DATABASE_URL"] = TEST_DATABASE_URL
    environment.pop("DATABASE_URL", None)


class DeterministicFrontendAnalyzer:
    """Explicit fake transport; never installed by production app construction."""

    async def analyze(self, _case: AnalysisInput) -> AnalyzerResult:
        return AnalyzerResult(
            mapping=RuleMappingV1(
                schema_version="rule_mapping.v1",
                hypotheses=[
                    RuleInstanceV1(
                        template_id="add_subtrahend",
                        evidence_refs=["segment-1"],
                        description="Adds the written second operand.",
                        rank=1,
                    ),
                    RuleInstanceV1(
                        template_id="absolute_difference",
                        evidence_refs=["segment-2"],
                        description="Uses a non-negative magnitude difference.",
                        rank=2,
                    ),
                ],
            ),
            model_id="deterministic-test-fixture",
            model_snapshot="deterministic-test-fixture",
            request_id="test-fixture-request",
            proposal_draft=(
                "Multiple ranked hypotheses are consistent with the observed work. "
                "Review the compiled probe before learner access."
            ),
        )


def main() -> None:
    """Reset only the local test database and serve the explicit fixture app."""
    _guard_migration_environment(os.environ)
    alembic_config = Config("alembic.ini")
    migration_url = alembic_config.get_main_option("sqlalchemy.url")
    _require_local_test_database(migration_url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    settings = Settings(
        app_env="test",
        database_url=TEST_DATABASE_URL,
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        abuse_key_pepper="a" * 32,
        proxy_signing_secret="p" * 32,
        case_creation_limit_per_hour=2,
        public_app_url="http://127.0.0.1:3100",
        openai_api_key="",
    )
    app = create_app(settings=settings, analyzer=DeterministicFrontendAnalyzer())
    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)


if __name__ == "__main__":
    main()
