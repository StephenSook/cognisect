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

- `backend/src/cognisect/api.py:108` validates the owner capability shape and
  returns the same non-enumerating 404 for missing or invalid authority.
- `backend/src/cognisect/api.py:367-374` consumes the public quota before owner
  bootstrap, and lines 375-391 bootstrap before educational mutation and
  sets a Secure, HttpOnly, SameSite=Lax production cookie.
- `backend/src/cognisect/services.py:396` looks up only a purpose-hashed owner
  capability. `backend/src/cognisect/repositories.py` scopes workflow access by
  owner before any read or transition.
- `backend/src/cognisect/services.py:1023` derives a separate learner capability,
  lines 1027-1036 persist only its hash, and lines 1076-1077 apply the submission
  row lock.
- `frontend/src/lib/backend-proxy.ts:168` reads the teacher cookie, and line 174
  excludes it from every learner response path.

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

The repository hygiene scanner passed. On 2026-07-17, npm audit and pip-audit each
reported zero known vulnerabilities for the installed locked dependency graphs. A
zero result means no advisory match at audit time, not proof that every dependency
is safe.

Public case creation uses a Postgres fixed-window quota. At Vercel, the platform
client address is immediately converted into a domain-separated HMAC bucket; the
raw address is not forwarded to the backend. A distinct shared proxy secret signs
the bucket together with a short timestamp, method, and path. The backend verifies
that signature in constant time and rejects partial, invalid, or stale proxy
identity before quota or owner mutation. Direct backend requests with no signed
identity fall back to the socket host in a separate key-material domain. The quota
is consumed before backend owner bootstrap, so 428 attempts are bounded.

Analysis first authorizes the owner capability, then consumes a separate quota.
Rotating syntactically valid but unauthorized capabilities therefore create no
limiter rows. Only the scope, twice-HMACed bucket, UTC window timestamps, and
counter persist; raw client hosts, proxy buckets, and owner capabilities are never
written to the limiter table. `ABUSE_KEY_PEPPER`, `PROXY_SIGNING_SECRET`, and both
capability peppers must be mutually distinct. Atomic `INSERT ... ON CONFLICT`
consumption makes the configured limit exact across API processes. A rejected
request returns only `{"detail":"rate limit exceeded"}` and a numeric
`Retry-After` header.

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
uv export --frozen --no-hashes --no-dev --no-emit-project | uvx --python 3.12 pip-audit -r /dev/stdin
npm audit --audit-level=high --prefix frontend
npm audit --audit-level=high --prefix frontend/tools/openapi-generator
uv run python scripts/generate_dependency_licenses.py --check
cd frontend && npm ci && npm ci --prefix tools/openapi-generator && npm run check:peers
npm run test:e2e
```

CI enforces the frozen production Python audit, both exact npm lockfile audits,
full npm peer-tree validity, and generated license-inventory drift. These checks
are bounded to the resolved graphs and advisory data available when they run.

## Data lifecycle and residual limits

Default application retention is 30 days and configurable to 365. In production,
the application attaches the graph runtime first, then runs retention immediately
and every 21,600 seconds. Each iteration removes expired educational content and
checkpoints plus expired limiter buckets. Limiter cleanup uses an expiry-leading
index and drains bounded `FOR UPDATE SKIP LOCKED` batches in short transactions.
Iteration failures are logged without stopping the API and are retried at the
next interval. Owner-authorized deletion
removes workflow educational content and checkpoints; a content-free HMAC tombstone
prevents an old idempotency command from recreating it.

The fixed-window limiter is a database-backed abuse bound, not authentication or a
substitute for an edge DDoS service. A shared NAT can aggregate unrelated teachers,
and correctness depends on Vercel supplying the intended platform-owned client
header and Render accepting only the authenticated derived bucket. Rotating
`ABUSE_KEY_PEPPER` starts new logical buckets; rotating the proxy secret requires
an atomic frontend/backend configuration update. Application purge
does not erase provider logs or backups. Free-tier backups, high availability,
alerting, and long-term availability are not production-grade guarantees. Provider
access, proxy topology, quotas, and retention should be re-audited before any real
educational deployment.
