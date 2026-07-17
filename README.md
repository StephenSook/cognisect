<p align="center">
  <img src="docs/assets/cognisect-product-overview.png" alt="COGNISECT landing page showing two competing signed-integer hypotheses flowing through the deterministic Counterexample Compiler to a teacher-reviewed probe" width="100%" />
</p>

# COGNISECT

**Compile the next question, not a diagnosis.**

COGNISECT helps a secondary mathematics teacher test competing explanations for
one signed-integer subtraction error. GPT-5.6 maps observed work into a closed
rule registry; a deterministic Counterexample Compiler finds the smallest
follow-up problem on which the represented rules disagree.

[![CI](https://github.com/StephenSook/cognisect/actions/workflows/ci.yml/badge.svg)](https://github.com/StephenSook/cognisect/actions/workflows/ci.yml)
[![Live preview](https://img.shields.io/badge/live%20preview-online-3fb950.svg)](https://cognisect.vercel.app)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**[Try the live preview](https://cognisect.vercel.app)** ·
**[Open the teacher lab](https://cognisect.vercel.app/lab)** ·
**[Inspect runtime evidence](https://cognisect.vercel.app/runtime)**

The compiler proves disagreement between formalized rules. It does not prove a
learner's cognitive state.

## The problem

One wrong answer can fit more than one plausible procedure. A model that selects
one explanation too early can turn ambiguity into an unjustified diagnosis.
COGNISECT preserves the alternatives long enough to ask a question that actually
separates them, while keeping the teacher in control of what reaches the learner.

## Judge path

1. Open the [teacher lab](https://cognisect.vercel.app/lab) and choose a
   provenance-cleared public case.
2. Review the constrained rule hypotheses and the compiled separating probe.
3. Approve the probe, then open its learner link in a separate browser context.
4. Submit one signed integer, return to the report, and inspect the persisted
   evidence update and audit record.

The preview uses free Vercel, Render web, and Render Postgres resources, so the
first request may cold-start.

## COGNISECT in one loop

> A teacher submits de-identified observed work. GPT-5.6 ranks instances from an
> educator-reviewed rule registry. The Counterexample Compiler searches all 625
> bounded subtraction problems and persists the smallest probe where the leading
> alternatives disagree. The teacher approves it, the learner submits one signed
> integer, exact matching updates the evidence, and the teacher approves, edits,
> rejects, or abstains on the final note.

## What is real

| Component | Shipped behavior |
| --- | --- |
| Constrained model mapping | GPT-5.6 Terra and Sol return strict structured instances from `rule_registry.v1`; they cannot author executable rules. |
| Counterexample Compiler | Exhaustive deterministic search over `a - b`, where both operands are in `[-12, 12]`; a probe is released only when represented rules disagree. |
| Evidence update | One strict signed integer is matched exactly against predictions and labeled `supported`, `weakened`, `unresolved`, or `abstained`. |
| Human custody | The teacher approves the probe and separately approves, edits, rejects, or abstains on the final note. |
| Durable workflow | FastAPI, Postgres, SQLAlchemy, Alembic, and LangGraph checkpoints preserve interrupt and resume state. |
| Capability security | Teacher and learner links use separate high-entropy capabilities with hashed verifiers, atomic response recording, replay protection, and deletion. |

## Architecture

```mermaid
flowchart TD
    T["Teacher<br/>de-identified case"] --> API["FastAPI workflow"]

    subgraph MODEL["Bounded model step"]
      MAP["GPT-5.6 Terra / Sol<br/>constrained rule mapping"]
    end

    subgraph CORE["Deterministic application core"]
      REG["Closed rule registry<br/>schema + truth-table validation"]
      COMP["Counterexample Compiler<br/>bounded exhaustive search"]
      GATE{"Teacher approves<br/>the probe?"}
      UPDATE["Exact evidence update<br/>supported / weakened / unresolved"]
    end

    API --> MAP --> REG --> COMP --> GATE
    GATE -->|yes| LINK["Opaque one-time<br/>learner link"]
    GATE -->|no| ABSTAIN["Abstained"]
    LINK --> ANSWER["Learner submits<br/>one signed integer"]
    ANSWER --> UPDATE --> REVIEW["Teacher reviews<br/>the final note"]

    STORE[("Postgres records<br/>+ LangGraph checkpoints")]
    API -. workflow state .-> STORE
    COMP -. predictions + probe hash .-> STORE
    UPDATE -. evidence + audit event .-> STORE
    REVIEW -. decision .-> STORE
```

The model proposes only registry data. Authorization, rule execution, probe
selection, response matching, state transitions, and teacher approval remain in
deterministic application code.

## Measured evidence

| Gate | Checked result |
| --- | --- |
| Frozen model comparison | 12 live model calls across six educator-authored fixtures |
| Schema and registry acceptance | Terra 6/6; Sol 6/6 |
| Exact expected rule set | Terra 4/6; Sol 5/6 |
| Separating probe and hash reproduction | 6/6 Terra mappings |
| Concurrent learner submissions | 1 accepted and 49 conflicted out of 50 |
| Targeted security tests | 145 passed |
| Playwright journeys | 8 desktop, mobile, accessibility, replay, expiry, abstention, and deletion journeys passed |
| Learner responses used for evaluation | Zero learner responses |

This is a small project-authored harness, not a generalized accuracy estimate.
No educator usability review, classroom adoption, learning improvement, or
teacher time-saving result is claimed. See the [evaluation report](docs/EVALUATION.md)
and [security report](docs/SECURITY.md) for methods and limitations.

## Quickstart

Python 3.12, Node 22, `uv`, and Docker are required.

```sh
git clone https://github.com/StephenSook/cognisect.git
cd cognisect
cp .env.example .env
docker compose up -d --wait postgres
uv sync --frozen
./scripts/migrate.sh
./scripts/run-backend.sh
```

In a second terminal:

```sh
cd frontend
npm ci
COGNISECT_BACKEND_URL=http://127.0.0.1:8000 npm run dev
```

Replace the two pepper placeholders with different random values of at least 32
characters. Set `OPENAI_API_KEY` to run the production analyzer. Browser requests
use the same-origin frontend proxy; learner links should be tested in a separate
browser context.

## Verification

```sh
uv run ruff check backend scripts
uv run mypy backend/src
uv run pytest backend/tests -q
uv run python scripts/validate_provenance.py
uv run python scripts/run_offline_evaluation.py --check
uv run python scripts/run_model_benchmark.py --check
gitleaks git --redact

cd frontend
npm run lint
npm run typecheck
npm test
npm run build
npm run test:e2e
```

CI runs six jobs covering hygiene and full-history secret scanning, backend
quality, Postgres integration and property tests, frontend checks, Playwright
accessibility journeys, OpenAPI drift, migrations, and container builds.

## Documentation

- [Architecture and API](docs/ARCHITECTURE.md)
- [Rule registry](docs/specs/rule-registry-v1.md), [evidence contract](docs/specs/evidence-contract.md), and [state machine](docs/specs/state-machine.md)
- [Dataset card](docs/DATASET_CARD.md), [data tiers](docs/specs/data-tiers.md), and [evaluation](docs/EVALUATION.md)
- [Security, privacy, and retention](docs/SECURITY.md)
- [Deployment and incident runbook](docs/DEPLOYMENT.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md) and [dependency licenses](docs/DEPENDENCY_LICENSES.md)

## License

Apache-2.0. See [LICENSE](LICENSE), [NOTICE](NOTICE), and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
