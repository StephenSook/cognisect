# Security, privacy, and release audit

## Release result

The 2026-07-17 release audit passed after two fixes: a 32 KiB pre-parse request
body limit was added at the ASGI and same-origin proxy boundaries, and external
access to the Render Postgres preview was blocked. The public application still
reaches Postgres over Render's internal network and `/health` returns `ok`.

This is an engineering audit and stress test, not a third-party penetration test.
The machine-readable sources are `data/security/security-audit.v1.json` and
`data/security/production-stress-report.v1.json`.

## Four-area source audit

### Authentication and authorization — pass

- `backend/src/cognisect/api.py:67` validates the owner capability shape and
  returns the same non-enumerating 404 for missing or invalid authority.
- `backend/src/cognisect/api.py:260` bootstraps before educational mutation and
  sets a Secure, HttpOnly, SameSite=Lax production cookie.
- `backend/src/cognisect/services.py:276` looks up only a purpose-hashed owner
  capability. `backend/src/cognisect/repositories.py` scopes workflow access by
  owner before any read or transition.
- `backend/src/cognisect/services.py:897` derives a separate learner capability,
  persists only its hash, and uses a row lock for submission.
- `frontend/src/lib/backend-proxy.ts:132` never forwards a teacher owner cookie to
  a learner response path.

The owner/learner/cross-owner matrix, missing-authority equivalence, expiration,
GET non-consumption, replay, stale version, and deletion tests passed.

### Database access — pass after fix

The Render API initially reported its default external-access configuration.
Render documents that new databases default to `0.0.0.0/0` for external URLs.
An empty external allowlist was applied through the official API. A credentialed
external connection attempt is now blocked; the internal application health query
still succeeds. The service uses the internal database URL. See Render's
[Postgres connection rules](https://render.com/docs/postgresql-creating-connecting)
and [private network](https://render.com/docs/private-network) documentation.

SQLAlchemy statements use bound expressions, ownership is resolved before aggregate
access, transitions use compare-and-swap versions, learner writes lock the token
row, audit events are append-only, and deletion leaves only a content-free replay
tombstone. Migration upgrade/check/downgrade/upgrade completed successfully.

### Input validation and resource bounds — pass after fix

`backend/src/cognisect/api_models.py` uses strict Pydantic contracts with forbidden
extra fields and bounded operands, text, ranks, rationale, and list sizes. The
closed interpreter accepts no executable expression, AST, import, recursion,
dynamic dispatch, `eval`, or `exec`.

The audit found that field limits applied only after JSON parsing. The fix adds a
32,768-byte raw-body limit in `backend/src/cognisect/body_limit.py` and mirrors it
in `frontend/src/lib/backend-proxy.ts`. Oversized teacher and learner mutations now
return 413 before parsing or database mutation; learner 413 responses retain
`Cache-Control: no-store, private` and `Referrer-Policy: no-referrer`.

The frozen prompt treats case content as untrusted JSON-escaped evidence. Model
calls have no tools, hidden-reasoning request, arbitrary code, or authorization
authority; invalid structured output receives at most one bounded repair in the
product route and otherwise abstains.

### Secrets and logging — pass

`backend/src/cognisect/config.py` rejects non-Postgres databases, local production
origins, missing/placeholder peppers, and missing production OpenAI credentials.
`backend/src/cognisect/security.py` uses 32 random bytes, purpose-separated HMAC,
and constant-time comparison. `backend/src/cognisect/safe_logging.py` allowlists
only event name, method, route template, status, state, model ID, request ID,
latency, and token/cost metadata. Uvicorn access logging is disabled in production.

The repository hygiene scanner passed. npm audit and pip-audit each reported zero
known vulnerabilities for the installed locked release dependencies. A zero result
means no advisory match at audit time, not proof that every dependency is safe.

## Production stress evidence

The sanitized gate ran against public SHA
`6a7d848b9444a63b4ed62571e55b735c644b39ed`:

| Invariant | Result |
| --- | ---: |
| Learner GETs before submission | 2 successful; token not consumed |
| Concurrent submissions | 50 |
| Accepted | 1 |
| Conflicted | 49 |
| Exact replay | Original receipt returned |
| Persisted readback | `AWAITING_REVIEW` with deterministic evidence |
| Audit transitions | 7 |
| Deletion | 204 |
| Read after deletion | 404 |

The report stores no workflow/case ID, receipt, owner secret, learner token, URL,
answer, observed work, or cookie. The disposable educational record was deleted.

## Verification commands

```sh
uv run pytest backend/tests -q
uv run python scripts/check_public_repo.py
uv run python scripts/run_production_stress.py --check
uv run alembic check
uv run --with pip-audit pip-audit --local --skip-editable
npm audit --audit-level=high
npm run test:e2e
```

## Data lifecycle and residual limits

Default application retention is 30 days and configurable to 365. Owner-authorized
deletion removes workflow educational content and checkpoints; a content-free HMAC
tombstone prevents an old idempotency command from recreating it.

The free preview has no documented distributed application rate limiter. Bounded
payloads, strict schemas, one-response capabilities, provider timeouts, three-call
model limits, and a cost circuit breaker reduce abuse impact but do not replace a
production edge rate limiter. Free-tier backups, high availability, alerting, and
long-term availability are not production-grade guarantees. Provider access and
retention settings should be re-audited before any real educational deployment.
