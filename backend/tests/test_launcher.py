"""Production launcher logging-safety contracts against a real Uvicorn process."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgres://owner:secret@db/cognisect",
            "postgresql+psycopg://owner:secret@db/cognisect",
        ),
        (
            "postgresql://owner:secret@db/cognisect",
            "postgresql+psycopg://owner:secret@db/cognisect",
        ),
        (
            "postgresql+psycopg://owner:secret@db/cognisect",
            "postgresql+psycopg://owner:secret@db/cognisect",
        ),
    ],
)
def test_render_database_urls_are_normalized_without_printing_in_launcher(
    raw: str,
    expected: str,
) -> None:
    repository = Path(__file__).resolve().parents[2]
    normalizer = repository / "scripts" / "database_url.sh"
    command = (
        f'. "{normalizer}"; DATABASE_URL="$1"; normalize_database_url; '
        'printf "%s" "$DATABASE_URL"'
    )

    completed = subprocess.run(  # noqa: S603
        ["/bin/sh", "-c", command, "normalize-database-url", raw],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == expected
    assert completed.stderr == ""


def test_database_url_normalizer_rejects_non_postgres_schemes() -> None:
    repository = Path(__file__).resolve().parents[2]
    normalizer = repository / "scripts" / "database_url.sh"
    command = f'. "{normalizer}"; DATABASE_URL="$1"; normalize_database_url'

    completed = subprocess.run(  # noqa: S603
        ["/bin/sh", "-c", command, "normalize-database-url", "mysql://db/cognisect"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_launcher_never_access_logs_raw_learner_request_targets(unused_tcp_port: int):
    repository = Path(__file__).resolve().parents[2]
    launcher = repository / "scripts" / "run-backend.sh"
    sensitive_marker = "RAW-LEARNER-CAPABILITY-DO-NOT-LOG"
    environment = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        "OWNER_SECRET_PEPPER": "o" * 32,
        "LEARNER_TOKEN_PEPPER": "l" * 32,
        "PUBLIC_APP_URL": "http://127.0.0.1",
        "OPENAI_API_KEY": "",
        "PORT": str(unused_tcp_port),
        "PYTHONUNBUFFERED": "1",
    }
    process = subprocess.Popen(  # noqa: S603
        [str(launcher)],
        cwd=repository,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    response: httpx.Response | None = None
    output = ""
    try:
        deadline = time.monotonic() + 10
        with httpx.Client(trust_env=False) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output = process.communicate()[0]
                    pytest.fail(f"launcher exited before serving a request:\n{output}")
                try:
                    response = client.post(
                        f"http://127.0.0.1:{unused_tcp_port}/v1/respond/{sensitive_marker}",
                        json={"answer": "invalid"},
                        timeout=0.25,
                    )
                    break
                except httpx.TransportError:
                    time.sleep(0.05)
            else:
                pytest.fail("launcher did not start within 10 seconds")
    finally:
        process.terminate()
        try:
            output += process.communicate(timeout=5)[0]
        except subprocess.TimeoutExpired:
            process.kill()
            output += process.communicate(timeout=5)[0]

    assert response is not None
    assert response.status_code == 422
    assert '"path_template": "/v1/respond/{token}"' in output
    assert sensitive_marker not in output
    assert "Traceback" not in output
