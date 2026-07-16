# COGNISECT canonical implementation plan

Status: active  
Track: Education  
Domain: signed-integer subtraction only  
Repository boundary: this repository contains public code and cleared documentation only.

## Product contract

COGNISECT is a teacher-controlled formative-assessment workbench. A model maps de-identified observed work to instances from a closed rule registry. A deterministic Counterexample Compiler chooses the simplest bounded `a - b` probe that separates represented alternatives. The teacher approves the probe, the learner submits one signed integer, the system updates evidence deterministically, and the teacher reviews the resulting note.

The compiler proves disagreement between formalized rules. It does not prove a learner's cognitive state.

## Binding constraints

- Domain: `a - b`, with both operands in `[-12, 12]`.
- Closed `rule_registry.v1`; no arbitrary executable model output, `eval`, `exec`, dynamic imports, AST execution, recursion, or source strings.
- Strict schemas reject unknown templates, parameters, oversized values, and extra fields.
- Rules are canonicalized by complete truth tables; semantic duplicates and the correct rule are rejected.
- Probe rank: more distinct outputs, separation of leading alternatives, more hypotheses distinguished, lower operand magnitude, lower result magnitude, then stable operand order.
- Predictions and a hash of the full probe specification are persisted before learner access.
- Learner answer is a strict signed integer; rationale is review-only.
- Evidence vocabulary is limited to `supported`, `weakened`, `unresolved`, and `abstained`.
- Evidence matching tests the stored correct prediction first; when the learner answer equals it, every alternative is `weakened`, even if an alternative prediction collides.
- Python 3.12, FastAPI, SQLAlchemy 2, Alembic, LangGraph, Postgres only; Next.js App Router and strict TypeScript.
- Owner and learner secrets are opaque, high entropy, hashed at rest, redacted from logs, and separated by purpose.
- GET never consumes learner tokens. POST is atomic and idempotent.
- Every mutation accepts an idempotency key. Every transition uses compare-and-swap versioning.
- Generated proposals and teacher edits are stored separately; audit events are append-only.
- No production demo mode, auth bypass, default credential, roster, learner identifier, or PII.
- Model calls use the official Responses API, bounded structured outputs, no hidden reasoning trace, at most one repair, three calls per case, and a configurable cost breaker.
- Model IDs: `gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol`.
- Allowed claims: ranked hypothesis, consistent with, weakened, unresolved, abstained, teacher-reviewed, deterministic compiler/update.

## Delivery sequence

1. Freeze schemas, registry semantics, state machine, privacy contract, provenance tiers, and public API.
2. Test-first independent oracle, interpreter, truth-table canonicalizer, compiler, and evidence updater.
3. Postgres schema, migrations, durable state machine, API, ownership, tokens, replay, concurrency, and deletion.
4. Plain end-to-end teacher and learner UI, generated client, then Observatory Hybrid visual layer.
5. Evaluation manifest and baselines, provenance/leakage checks, security/accessibility checks, CI, deployment manifests, and public documentation.
6. Fresh full verification. External claims remain disabled until real production, educator, and benchmark evidence exists.

## External gates

Kaggle acceptance, OpenAI credentials, managed Render/Vercel resources, educator consent, public video publishing, and Devpost submission require the owner. Local code must never manufacture evidence for these gates.
