# Security, privacy, and threat model

## Protected assets

COGNISECT protects teacher ownership capabilities, learner response capabilities,
de-identified educational content, learner answers, generated proposals, teacher
edits, model request metadata, and append-only audit evidence.

## Capability design

The first teacher visit receives a high-entropy owner secret in a Secure,
HttpOnly, SameSite cookie in production. Only a purpose-specific hash is stored.
Learner links use independent random material and a separate pepper; only their
verifier and non-secret derivation nonce are persisted. Cross-owner reads use a
non-enumerating not-found response.

GET on a learner link does not consume it. POST atomically records one strict
signed integer and advances the workflow. Replays return the original receipt or
a state-specific conflict. Learner routes return `Cache-Control: no-store,
private` and `Referrer-Policy: no-referrer`; the page loads no analytics or
external QR service.

## Application controls

- Pydantic contracts forbid extra fields and bound all strings, integers, list
  sizes, ranks, and model-call counts.
- The model can select only registry template IDs; it cannot provide executable
  expressions, source, tools, SQL, or interpreter branches.
- There is no `eval`, `exec`, dynamic import, user-authored AST, recursion, demo
  credential, default production secret, or authentication bypass.
- Prompt text treats case content as untrusted data. It cannot modify registry,
  authorization, compiler, or teacher-approval policy.
- Structured logs omit tokens, learner answers, observed work, prompts, model
  responses, and teacher notes. Uvicorn access logging is disabled in production.
- Database transitions use compare-and-swap versions and append-only audit rows.
- Production startup rejects local origins, missing model credentials, short or
  placeholder peppers, non-Postgres databases, and non-TLS public URLs.

## Data lifecycle

Default retention is 30 days and configurable up to 365. Owner-authorized
deletion removes the workflow and educational content; a content-free HMAC
tombstone remains to prevent idempotency replay from recreating deleted work.
Database backups and provider retention must be configured consistently before
production launch.

## Operational threats and response

| Threat | Primary control | Response |
| --- | --- | --- |
| Link disclosure | Separate high-entropy scopes, hashes at rest | Revoke links and rotate the affected pepper |
| Database-only compromise | No raw capabilities stored | Rotate credentials; assess whether pepper stayed separate |
| Database + pepper compromise | Short expiry and deletion | Rotate pepper and revoke all outstanding links |
| Duplicate or concurrent submit | Unique constraints, transaction, replay receipt | Return one receipt; investigate invariant failure |
| Prompt injection | Closed schema/registry and no model tools | Abstain after one bounded repair |
| Stale browser write | Expected workflow version | Return conflict and require fresh state |
| Content in logs | Structured allowlist logging | Stop logging sink, rotate access, delete exposed records |

## Verification and disclosure

Tests cover ownership matrices, replay, expiry, 50-way submission concurrency,
append-only events, restart/resume, deletion, strict input contracts, response
headers, and token/content redaction. Browser tests cover expired, duplicate,
invalid, abstained, offline, and slow-request states.

Report security issues privately to the repository owner. Do not include a real
teacher capability, learner URL, educational record, or provider credential in
an issue.

## Residual limits

The local suite is not a third-party penetration test. Provider access controls,
backups, alerting, rate limits, and production log sinks require verification on
the deployed services. A human privacy/security review remains a release gate.
