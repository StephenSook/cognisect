# Submission fact sheet

Status: local release candidate; production, live-model benchmark, educator
review, video, and submission evidence are not yet recorded.

## Code-audited facts

- Domain: ordered signed-integer subtraction with both operands in `[-12, 12]`.
- Registry: 6 explicit total alternative functions, each evaluated on 625 inputs.
- Compiler: exhaustive bounded search, deterministic lexicographic rank, original
  problem excluded, separating disagreement required.
- Evidence: exact integer matching only; statuses are supported, weakened,
  unresolved, or abstained.
- Persistence: Postgres-only SQLAlchemy/Alembic storage plus Postgres LangGraph
  checkpoints; append-only audit and optimistic versions.
- Public UI: 6 product routes plus the same-origin API proxy.
- Public API: 8 workflow/resource paths plus `/health` and `/version`.
- Public fixtures: 6 educator-authored CC BY 4.0 cases; 0 authentic learner
  records and 0 collected learner responses.
- Deterministic fixture harness: 6/6 registry accepted, 6/6 separating probes,
  and 6/6 reproduced specification hashes. It makes 0 model calls.
- Frontend verification at commit `b8a68f5`: 48 Vitest tests and 8 Playwright
  journeys passed; npm audit reported 0 known vulnerabilities.
- Backend verification for this release slice: 248 tests passed against Postgres
  in the fresh full suite.

## Evidence still required

| Claim area | Current status | Enabling evidence |
| --- | --- | --- |
| Public production | Not claimed | Logged-out smoke and served-SHA match |
| GPT-5.6 live calls | Not claimed | Persisted request/model telemetry |
| Mapping benchmark | Not claimed | Frozen cleared benchmark and baselines |
| Interactive evidence | Not claimed | Real learner responses under consent |
| Educator usability | Not claimed | Completed consented review and rerun |
| Adoption or learning effect | Not claimed | Separate appropriately designed study |

All README, UI, video, and submission numbers must be copied from a regenerated,
code-audited version of this file after production and evaluation gates finish.
