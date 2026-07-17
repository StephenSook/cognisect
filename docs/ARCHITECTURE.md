# Architecture

COGNISECT is a teacher-controlled signed-integer subtraction workbench. A model
may propose instances from a closed registry; deterministic code decides whether
those instances are admissible, selects a separating probe, records one learner
answer, updates evidence, and stops for teacher review.

## Runtime topology

```text
Teacher browser ── same-origin Next.js proxy ── FastAPI ── Render Postgres
       │                                          │              │
       │                                          │              ├─ workflow rows
       │                                          │              ├─ append-only audit
       │                                          │              └─ LangGraph checkpoints
       │                                          │
       └─ learner link / QR ── isolated learner browser
                                                  │
                                                  └─ Responses API (analysis only)
```

Vercel serves the Next.js App Router application. Browser calls go through
`/api/backend`; FastAPI remains the authority for ownership, learner tokens,
workflow state, idempotency, and public DTO filtering. Render Postgres is the
only database in development, test, and production.

## Deterministic core

`rule_registry.v1` has six parameter-free total functions over all 625 ordered
pairs in `[-12, 12]²`. The interpreter uses explicit branches. Each rule is
canonicalized by its full truth table, semantic duplicates are merged, and any
correct-equivalent rule is removed.

The Counterexample Compiler enumerates every candidate except the original
problem. It releases only a problem where at least two accepted rules disagree,
using the frozen lexicographic rank in `docs/specs/rule-registry-v1.md`. The full
probe, predictions, versions, and SHA-256 specification hash are stored before a
learner GET can expose the question.

## Durable state and interrupts

The state machine is specified in `docs/specs/state-machine.md`. Analysis and
response processing use a stable workflow/thread ID, Postgres checkpoints,
LangGraph interrupts, and explicit resume commands. Database transitions use an
expected version; stale writes fail without side effects. Model calls execute
outside database locks, while attempt journals make retry and restart behavior
auditable.

Every mutation requires an idempotency key. Approval replays return the same
learner URL, learner submission replays never create a second response, and
audit rows are protected by a database-level append-only trigger.

## Trust boundaries

- The teacher owner cookie is Secure and HttpOnly in production and stores only
  the raw high-entropy capability in the browser. Postgres stores its hash.
- Learner URLs use a distinct purpose-specific capability. GET does not consume
  it; POST records at most one response atomically.
- Learner DTOs contain only the probe, answer constraints, instructions, and
  expiry. Teacher evidence and model telemetry are not serialized to that route.
- Custom content is accepted only with a de-identification attestation and strict
  extra-field rejection.
- Generated text and teacher-edited text occupy separate records.

## Public API

The checked-in OpenAPI document is authoritative for:

- `POST /v1/cases`
- `POST /v1/cases/{case_id}/analysis`
- `GET /v1/workflows/{workflow_id}`
- `POST /v1/workflows/{workflow_id}/probe-approval`
- `GET|POST /v1/respond/{token}`
- `POST /v1/workflows/{workflow_id}/review`
- `GET /v1/workflows/{workflow_id}/audit`
- `DELETE /v1/workflows/{workflow_id}`
- `GET /health` and `GET /version`

The TypeScript client is generated from `openapi/openapi.json`; CI fails on drift.
