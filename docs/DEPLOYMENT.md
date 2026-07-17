# Deployment and incident runbook

No public deployment is claimed by this document. It defines the exact operator
steps and evidence required before that claim is enabled.

## Topology

- Vercel: one Next.js project with repository Root Directory set to `frontend`.
- Render: `cognisect-api` paid Docker web service and `cognisect-postgres` paid
  Postgres in `ohio`, connected by Render's internal connection string.
- Render database public IP allowlist: empty.
- Render deploy trigger: checks must pass; migrations run as `preDeployCommand`.

The checked-in files follow the current official [Render Blueprint
specification](https://render.com/docs/blueprint-spec) and [Vercel monorepo
root-directory guidance](https://vercel.com/docs/monorepos).

## Required operator configuration

1. Create or sync `render.yaml`; confirm the service and database are paid and in
   the same region.
2. Set `OPENAI_API_KEY` and the final HTTPS `PUBLIC_APP_URL` in Render. Generated
   owner and learner peppers must be distinct and retained outside the database.
3. Import the GitHub repository into a dedicated Vercel project and set Root
   Directory to `frontend`.
4. Set `COGNISECT_BACKEND_URL` to the Render HTTPS origin and
   `COGNISECT_FRONTEND_ENV=production` in Vercel. Do not expose either pepper or
   the OpenAI key to Vercel or to `NEXT_PUBLIC_*` variables.
5. Keep preview deployments from using production Postgres or production
   capabilities.

Render's connection string is normalized at process start from `postgres://` or
`postgresql://` to SQLAlchemy's explicit `postgresql+psycopg://` dialect without
logging the credential.

## Release procedure

1. Merge only after all six GitHub checks succeed.
2. Record the merged SHA. Query check runs and require six completed successes.
3. Confirm Render's pre-deploy migration and health check succeed.
4. Confirm Vercel and Render display the same intended source SHA.
5. From a logged-out teacher browser, create and analyze a de-identified case,
   approve the probe, and copy the learner link.
6. In a separate browser context, GET the link, submit one signed integer, and
   verify duplicate submission cannot create a second response.
7. Return to the teacher report, review the evidence, save a decision, reload,
   and read the persisted audit.
8. Repeat five times with real model telemetry. Record request IDs, exact model
   snapshots, latency, token usage, cached tokens, and actual cost.
9. Verify `/version`, `/health`, browser console, CORS, response privacy headers,
   owner isolation, and served SHA evidence.

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

Keep the judged service warm and monitored through the competition's confirmed
availability deadline. Recheck the live Devpost dates rather than relying on a
historical PDF before scheduling shutdown.
