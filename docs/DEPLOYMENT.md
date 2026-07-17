# Deployment and incident runbook

COGNISECT has a time-limited public preview at
[cognisect.vercel.app](https://cognisect.vercel.app). It is a release candidate,
not a durable classroom production claim. The preview was verified through a
logged-out desktop teacher browser and an isolated mobile learner browser; its
smoke workflow was deleted after persisted readback.

## Topology

- Vercel: one Next.js project with repository Root Directory set to `frontend`.
- Vercel's **Include source files outside of the Root Directory** setting is
  enabled because the frontend imports the cleared provenance ledger.
- Render: a free Docker web service and free Postgres in `ohio`, connected by
  Render's internal connection string.
- Render database public IP allowlist: empty.
- Render deploy trigger: checks must pass. The free preview runs migrations in
  the Docker start command before starting Uvicorn because pre-deploy commands
  are reserved for an upgraded service topology.

The checked-in files follow the current official [Render Blueprint
specification](https://render.com/docs/blueprint-spec) and [Vercel monorepo
root-directory guidance](https://vercel.com/docs/monorepos).

## Required operator configuration

1. Create or sync `render.yaml`; confirm the service and database are free and in
   the same region. Upgrade both deliberately before making durability or backup
   claims.
2. Set `OPENAI_API_KEY` and the final HTTPS `PUBLIC_APP_URL` in Render. Generated
   `OWNER_SECRET_PEPPER`, `LEARNER_TOKEN_PEPPER`, and `ABUSE_KEY_PEPPER` values
   must all be distinct and retained outside the database.
3. Import the GitHub repository into a dedicated Vercel project and set Root
   Directory to `frontend`; enable source files outside that directory.
4. Run `openssl rand -hex 32` once to generate a fourth, distinct secret. Its
   64-character lowercase-hex output satisfies the required unnormalized
   base64url ASCII contract (`[A-Za-z0-9_-]{32,128}`). Set that exact output as
   `PROXY_SIGNING_SECRET` in Render and
   `COGNISECT_PROXY_SIGNING_SECRET` in Vercel. It is a server-only shared proxy
   credential: do not add quotes or whitespace, never use a `NEXT_PUBLIC_*`
   variable, and rotate both copies together.
5. Set `COGNISECT_BACKEND_URL` to the Render HTTPS origin and
   `COGNISECT_FRONTEND_ENV=production` in Vercel. Do not expose a persistence
   pepper or the OpenAI key to Vercel or to `NEXT_PUBLIC_*` variables.
6. Keep preview deployments from using production Postgres or production
   capabilities.

For case-creation quotas, the Vercel route reads the platform-owned
`x-vercel-forwarded-for` value described in Vercel's official
[request-header reference](https://vercel.com/docs/headers/request-headers),
immediately replaces the address with an HMAC bucket, and sends only that bucket
to Render. A short-lived, method-and-path-bound HMAC authenticates the bucket.
Render rejects partial, stale, or invalid signed identity headers before quota or
owner mutation. Direct calls with no proxy identity use the backend socket host
in a separate HMAC domain. Re-audit this trust boundary if another reverse proxy
is placed in front of Vercel.

Render's connection string is normalized at process start from `postgres://` or
`postgresql://` to SQLAlchemy's explicit `postgresql+psycopg://` dialect without
logging the credential.

The production Blueprint sets `RETENTION_DAYS=30`,
`RETENTION_INTERVAL_SECONDS=21600`, `CASE_CREATION_LIMIT_PER_HOUR=60`, and
`ANALYSIS_LIMIT_PER_HOUR=30`. Render supplies `RENDER_GIT_COMMIT`; local and other
platform deployments may set `SOURCE_REVISION`. Either value must be a full
40-character lowercase Git SHA; when neither is present, `/version` reports the
explicit local sentinel `development`. Operators must reject that sentinel when
verifying a production release.

## Release procedure

1. Merge only after all six GitHub checks succeed.
2. Record the merged SHA. Query check runs and require six completed successes.
3. Confirm startup migration and the `/ready` Render check succeed. `/ready`
   requires database access and exact Alembic head `a5d3e9b7c421`; `/health`
   remains the backward-compatible database liveness response.
4. Confirm Vercel and Render display the same intended source SHA.
5. From a logged-out teacher browser, create and analyze a de-identified case,
   approve the probe, and copy the learner link.
6. In a separate browser context, GET the link, submit one signed integer, and
   verify duplicate submission cannot create a second response.
7. Return to the teacher report, review the evidence, save a decision, reload,
   and read the persisted audit.
8. Repeat five times with real model telemetry. Record request IDs, exact model
   snapshots, latency, token usage, cached tokens, and actual cost.
9. Verify `/version`, `/health`, `/ready`, browser console, CORS, response privacy
   headers, owner isolation, limiter `Retry-After`, and served SHA evidence.

Fixture analyzers and local test servers do not satisfy production evidence.

## Rollback and incidents

- Application regression: stop auto-deploy, redeploy the last known-good SHA,
  then re-run the production loop. Do not reverse an irreversible migration.
- Migration failure: leave the prior service active, inspect the release log,
  and restore from the provider backup only through a rehearsed recovery plan.
- Capability exposure: revoke outstanding learner links, rotate the affected
  pepper, and assess combined database/secret access.
- Model cost or availability event: open the circuit breaker and abstain; do not
  silently substitute an unverified model ID.
- Content in logs: disable the sink, restrict access, remove affected entries,
  and document scope without copying content into an issue.

## Operational expiry

The current free Postgres resource reports an expiry date of August 16, 2026.
Free services can cold-start and do not establish backup, uptime, or durability
evidence. Keep the judged preview monitored through the competition's confirmed
availability deadline, then recheck the live Devpost dates and provider state
before scheduling an upgrade or shutdown.
