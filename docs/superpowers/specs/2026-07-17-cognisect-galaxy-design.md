# COGNISECT Galaxy Build Design

**Date:** 2026-07-17

**Approved direction:** Approach C, the Galaxy Build

## Outcome

COGNISECT will enter submission as a complete, publicly verifiable education product whose
central technical claim is visible in the judge path: GPT-5.6 maps observed work into a closed,
literature-grounded rule registry; deterministic code evaluates the represented procedures over
the complete 625-problem domain and selects the smallest new problem that separates them; the
teacher controls both release and final interpretation.

The build must maximize the four published judging criteria without expanding into unsupported
diagnosis, confidence, learning-outcome, adoption, time-saving, or educator-validation claims.

## Product thesis

The memorable reveal is **625-domain grid -> separating candidates -> one compiled probe**.
The interface must make the transformation inspectable rather than merely asserting it. The
original problem is one member of the 625-problem domain and is excluded from release, leaving
624 eligible follow-up candidates. The UI must show both numbers accurately.

## Non-negotiable boundaries

- The model never authors executable rules, selects a learner-facing probe, updates evidence,
  changes workflow state, or releases content.
- Public copy uses `closed, literature-grounded rule registry`, never `educator-reviewed`, until
  a consented educator review has actually occurred.
- No cognitive-state diagnosis, confidence percentage, learner scoring, or classroom-effect claim.
- No mock or demo-only backend path. The judge tour uses the deployed API, Postgres, model route,
  compiler, capabilities, learner response, and teacher gates.
- The learner surface does not expose hypotheses, predictions, correct answers, teacher controls,
  runtime telemetry, or owner capabilities.
- Every displayed compiler number is derived from the deterministic compiler.
- Exports exclude raw observed work, learner rationale, learner capability URLs/tokens, owner
  cookies, and provider credentials.
- Python 3.12, Node 22.22.2, Next.js 16.2.10, React 19.2.7, FastAPI, Postgres 17, SQLAlchemy 2,
  Alembic, and LangGraph remain the runtime baseline.
- New behavior follows red-green-refactor TDD and remains covered by local, CI, accessibility,
  mobile, integration, concurrency, migration, and production verification.

## Experience design

### Landing page

Retain the existing industrial evidence-workbench visual identity. Rewrite the key language so the
unique mechanism appears before generic AI framing. Add a `Run the live evidence tour` action.
The landing example should visibly distinguish the 625-domain scan from the 624 eligible
follow-up problems.

### Teacher lab

Default to provenance record `cognisect-ea-001`, with its problem and observed work prefilled.
Persist the selected provenance record ID when a public exemplar is submitted. Free entry remains
available. A compact tour rail explains that the case is real API input, not a mock fixture.

### Compiler proof lens

The teacher workbench receives a deterministic `proof` object alongside the persisted probe:

```text
domain_problem_count: 625
eligible_candidate_count: 624
separating_candidate_count: integer
chosen_candidate_rank: 1
top_candidates: at most 5 deterministic candidates
```

Each candidate contains the signed problem, exact predictions keyed by hypothesis rank, distinct
output count, whether ranks 1 and 2 separate, distinguished hypothesis-pair count, operand
magnitude, correct-result magnitude, and final deterministic rank. The chosen candidate in this
proof must reproduce the persisted probe specification.

The frontend turns the proof into a progressive visual sequence: domain grid, rejected agreement,
separating set, ranked finalists, compiled probe. Reduced-motion users receive the final state
without animation. A semantic table remains available but is collapsed by default on desktop.

### Counterfactual preview

Before probe approval, the teacher sees clearly labeled counterfactual branches built from the
persisted predictions: `If the learner responds X, this represented procedure would be
supported/weakened.` It must never be presented as observed evidence.

### Human custody

The approve/decline control appears immediately after the proof summary, before secondary detail.
After a learner response, the final teacher note and decision are both rendered after persistence.
The README judge path and video include this second gate.

### Learner surface

The learner page receives a dedicated minimal layout without teacher navigation or runtime links.
The optional rationale is shown only to the authorized teacher as review-only context and remains
excluded from deterministic evidence computation and the downloadable receipt.

### Evidence receipt

An owner-authorized endpoint returns a privacy-safe JSON receipt containing workflow ID, source
tier and provenance ID, versions, model route metadata, accepted hypothesis identifiers and truth
table hashes, compiled probe proof summary, exact predictions, evidence statuses, teacher final
decision, append-only transitions, and a SHA-256 receipt hash. It excludes all raw educational
text, response rationale, capabilities, secrets, and generated prose. The report offers a download
button using this endpoint.

## Production design

### Retention executor

The existing `RetentionService` runs in production through a cancellable lifespan task. It runs
once after application startup and then every six hours. Failures are safely logged and do not
terminate the API. Shutdown cancels and awaits the task. The service remains idempotent.

### Distributed abuse boundary

Use a Postgres-backed fixed-window limiter for public case creation and analysis. Bucket keys are
HMAC-SHA256 values produced with a dedicated `ABUSE_KEY_PEPPER`; raw IP addresses are never
persisted. Upserts are atomic. The public response is HTTP 429 with `Retry-After`. Expired buckets
are deleted by the retention executor. Limits are explicit settings and tested under concurrency.

### OpenAI telemetry custody

Store three identifiers separately:

- requested/returned model snapshot
- Responses object ID (`response.id`)
- provider request ID (`response._request_id`, from `x-request-id`)

A returned model that does not match the requested frozen route becomes a typed policy failure.
No result from that call enters the compiler.

### Readiness and build identity

`/health` remains a liveness/database connectivity check. `/ready` additionally verifies the
database Alembic revision. `/version` includes the 40-character source revision supplied by
`SOURCE_REVISION` or Render's `RENDER_GIT_COMMIT`; non-production may report `development`.

### Dependency custody

Clean installation must not rely on unsupported TypeScript or ESLint peer overrides. CI runs both
`npm audit` and a frozen Python dependency export through `pip-audit` on Python 3.12.

## Submission design

- README contains accurate Codex collaboration evidence reconstructed from Git, the human decision
  boundary, the GPT-5.6 boundary, a five-step judge path, and current verification commands.
- Public claims are protected by release tests, including a forbidden `educator-reviewed` phrase.
- Private fact sheet and Devpost copy bind every number to the final served SHA.
- The public video is under three minutes with narration and shows the live compiler proof, both
  teacher gates, Codex collaboration, and GPT-5.6's constrained role.
- The real `/feedback` session ID is required before submission and is never fabricated.
- The project submits only to the Education category, as the rules allow one category per project.

## Verification gates

1. Focused red-green tests per behavior.
2. Full backend and frontend suites.
3. Ruff, strict mypy, ESLint, TypeScript, production build, OpenAPI drift, and Alembic round trip.
4. Eight existing Playwright journeys plus proof-lens, receipt, tour, learner-layout, and final-note
   assertions at desktop and mobile sizes with Axe.
5. Dependency, license, secret-history, provenance, benchmark, and claim checks.
6. Preview deployment and exact SHA parity through `/version`.
7. Live browser console/accessibility/reflow checks.
8. Full 50-way disposable production concurrency, replay, audit, and deletion stress.
9. Cross-surface truth audit of README, site, video, fact sheet, and Devpost draft.

## Explicitly excluded

- Cognitive diagnosis, confidence scoring, heatmaps, longitudinal profiles, or classroom analytics
- Additional subjects without an equally validated executable registry
- Google Classroom or LMS integration without a real integration test
- Synthetic educator endorsements or learner outcomes
- Decorative compiler statistics not computed by the shipped implementation
- Submission or publication before the real `/feedback` ID and final truth audit are complete
