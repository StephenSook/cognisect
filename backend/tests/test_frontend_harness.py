"""Safety contract for the explicitly test-only frontend server."""

import pytest

from run_frontend_server import (
    TEST_DATABASE_URL,
    FrontendReadDelay,
    _guard_migration_environment,
    _require_local_test_database,
)


def test_frontend_harness_reset_is_restricted_to_exact_local_test_database():
    _require_local_test_database(TEST_DATABASE_URL)
    for unsafe_url in (
        "postgresql+psycopg://cognisect:cognisect@db:5432/cognisect",
        "postgresql+psycopg://cognisect:cognisect@localhost:54329/production",
    ):
        with pytest.raises(RuntimeError, match="restricted"):
            _require_local_test_database(unsafe_url)


@pytest.mark.parametrize("name", ["COGNISECT_DATABASE_URL", "DATABASE_URL"])
def test_frontend_harness_rejects_unsafe_alembic_environment_override(name):
    environment = {name: "postgresql+psycopg://owner:secret@production/db"}
    with pytest.raises(RuntimeError, match="restricted"):
        _guard_migration_environment(environment)


def test_frontend_harness_forces_exact_local_alembic_environment():
    environment = {"DATABASE_URL": TEST_DATABASE_URL}
    _guard_migration_environment(environment)
    assert environment == {"COGNISECT_DATABASE_URL": TEST_DATABASE_URL}


def test_frontend_harness_delay_is_allowlisted_and_one_shot():
    delay = FrontendReadDelay()

    delay.arm("/v1/workflows/owned-workflow")
    assert delay.consume("/v1/workflows/owned-workflow") == 3.0
    assert delay.consume("/v1/workflows/owned-workflow") == 0.0

    with pytest.raises(ValueError, match="allowlisted"):
        delay.arm("/health")
