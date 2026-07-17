# COGNISECT

COGNISECT is a teacher-controlled formative-assessment workbench for bounded
signed-integer subtraction. The backend combines a closed deterministic rule
registry and counterexample compiler with a Postgres-only durable workflow. A
model may rank constrained hypotheses; it cannot author executable rules or
decide authorization, probe release, evidence status, or teacher approval.

## Current evidence status

The repository and a [time-limited public preview](https://cognisect.vercel.app)
are verified release candidates. The preview uses free Vercel, Render web, and
Render Postgres resources, so it may cold-start and is not represented as a
durable classroom production service. A logged-out, two-context Playwright smoke
has completed the teacher, isolated mobile learner, review, runtime-evidence,
and deletion loop with persisted `gpt-5.6-terra` telemetry.

A frozen comparison made 12 live model calls across six checked-in,
educator-authored fixtures. Terra and Sol produced schema-valid,
registry-accepted mappings for all six, and the compiler generated six separating,
reproducible probes. This small project-authored tier is a harness result, not a
generalized model-accuracy estimate. Authentic learner-response, educator-review,
adoption, and learning-effect claims remain disabled.

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

## Local frontend

Install the exact Node 22 dependencies and start the App Router application:

```sh
cd frontend
npm ci
COGNISECT_BACKEND_URL=http://127.0.0.1:8000 npm run dev
```

Open `http://localhost:3000`. Browser calls use the same-origin backend proxy;
learner links should always be tested in a separate browser context.

## Deterministic public evaluation

```sh
uv run python scripts/validate_provenance.py
uv run python scripts/run_offline_evaluation.py
```

This six-fixture run makes zero model calls and collects zero learner responses.
It is not an accuracy benchmark.

## Capability threat model

Teacher and learner URLs carry bearer capabilities and must be treated as
secrets. Learner capabilities are HMAC-derived from a purpose-specific pepper,
the token identifier, and a fresh 32-byte CSPRNG nonce. Postgres stores the
non-secret nonce and only the HMAC verifier of the resulting raw capability;
the raw capability is returned in memory and can be reconstructed for an exact
idempotent approval replay without being persisted.

A database-only compromise does not reveal bearer capabilities while the
pepper remains separate. A combined database and pepper compromise can derive
them, so incident response must rotate the pepper and revoke outstanding links.
Learner responses use `no-store, private` and `no-referrer` headers to reduce
browser and referrer leakage.

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

The browser gate is Playwright on desktop and mobile and includes the full
teacher → isolated learner → teacher report loop, keyboard-only navigation,
reduced motion, 200%-equivalent reflow, axe scans, slow/offline requests, expired
and duplicate learner submissions, and abstention.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Rule registry](docs/specs/rule-registry-v1.md) and [state machine](docs/specs/state-machine.md)
- [Dataset card](docs/DATASET_CARD.md) and [evaluation protocol](docs/EVALUATION.md)
- [Security and privacy](docs/SECURITY.md)
- [Deployment runbook](docs/DEPLOYMENT.md)
- [Educator review protocol](docs/EDUCATOR_REVIEW.md)
- [Build log](docs/BUILD_LOG.md), [submission fact sheet](docs/FACT_SHEET.md), and
  [submission copy](docs/SUBMISSION_COPY.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md) and [dependency licenses](docs/DEPENDENCY_LICENSES.md)
