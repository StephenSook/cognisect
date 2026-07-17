# Codex build and decision log

This public log records durable implementation facts without private strategy,
credentials, educator identity, or restricted educational records.

| Commit | Decision or delivered capability |
| --- | --- |
| `d85b145` | Frozen the signed-subtraction scope, schemas, state vocabulary, and repository boundary. |
| `d2ecfc7` | Completed the independent semantic oracle, registry interpreter, canonicalizer, compiler, and evidence update. |
| `521e39c` | Added Postgres records, migrations, ownership, learner capabilities, replay, concurrency, deletion, and append-only audit. |
| `b174437` | Added bounded Responses API routing, structured repair/abstention, telemetry, and durable LangGraph workflow behavior. |
| `0b4054a` | Completed the plain teacher/learner/review vertical slice and hardened owner recovery and command replay. |
| `b8a68f5` | Implemented the Observatory Hybrid interface, five-stage topology, local QR transport, responsive states, and browser accessibility gates. |

## Core decisions

- The product tests competing formalized explanations; it does not assert a
  learner's internal cognitive state.
- Model output is data mapped into `rule_registry.v1`, never executable code.
- The compiler, evidence updater, authorization, and state transitions are
  deterministic application code.
- Postgres is used everywhere; SQLite and in-memory workflow substitutes are
  deliberately unsupported.
- Reference handoffs, captures, and source bundles stay outside the public child
  repository.
- Educator-authored fixtures are labeled exactly and are not substituted for a
  usability session or authentic learner evidence.

## Codex contribution

Codex was used to translate the plan into schemas, implementation, migrations,
tests, UI, documentation, and release checks; inspect failures; and apply review
feedback. Deterministic tests, persisted telemetry, Git history, and production
service evidence—not the assistant's assertions—are the source of verifiable
claims.
