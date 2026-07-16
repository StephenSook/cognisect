# COGNISECT

COGNISECT is a teacher-controlled formative-assessment workbench for bounded
signed-integer subtraction. The backend combines a closed deterministic rule
registry and counterexample compiler with a Postgres-only durable workflow.

## Local backend

Python 3.12, `uv`, and Docker Compose are required. Start the checked-in
Postgres service and install the exact lockfile:

```sh
docker compose up -d --wait postgres
uv sync --frozen
```

Create `.env` from `.env.example`, replace both pepper placeholders with
different random values of at least 32 characters, and set an OpenAI key for
production. Development accepts a local public URL but still requires Postgres
and explicit peppers. SQLite, demo mode, default credentials, and authentication
bypasses are not supported.

Apply the schema and run the API:

```sh
./scripts/migrate.sh
./scripts/run-backend.sh
```

The application factory deliberately has no built-in analyzer fake. Tests inject
their fake explicitly; a production analyzer must be supplied at construction.

## Verification

The integration tests connect to the Compose service on port `54329` and never
skip or substitute SQLite:

```sh
uv run ruff check backend
uv run mypy backend/src
uv run pytest backend/tests -q
uv run alembic downgrade base
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
uv run python scripts/generate_openapi.py
uv run pytest backend/tests/test_openapi.py -q
git diff --check
```

Regenerating `openapi/openapi.json` is an intentional contract change and must
be reviewed with the API implementation and drift test.
