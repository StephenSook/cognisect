# Submission fact sheet

Generated from the checked-in benchmark, security audit, and production stress
reports. Status: release candidate plus time-limited public preview. This sheet is
the source of truth for README, interface, video, and submission numbers.

## Product and implementation

- Domain: ordered signed-integer subtraction with both operands in `[-12, 12]`.
- Registry: 6 closed, total alternative-rule templates, each interpreted across
  all 625 bounded inputs; arbitrary model-authored code is never executed.
- Counterexample Compiler: exhaustive bounded search, deterministic
  lexicographic rank, original problem excluded, and disagreement required before
  a probe can be released.
- Evidence update: exact signed-integer matching only; statuses are `supported`,
  `weakened`, `unresolved`, or `abstained`.
- Custody: the teacher approves the probe and final note. Generated proposals and
  teacher edits remain separate in the append-only audit history.
- Durability: Postgres-only SQLAlchemy/Alembic storage with Postgres LangGraph
  checkpoints, optimistic transition versions, and actual interrupt/resume.
- Ownership: hashed teacher and learner capabilities, non-enumerating owner
  failures, atomic single-use response recording, and deletion.

## Frozen live-model comparison

6 educator-authored fixtures

12 live model calls

Terra exact set: 4/6

Sol exact set: 5/6

Total model cost: `$0.253746`

- Terra and Sol each received the same six frozen records and prompt family.
  Both produced 6/6 schema-valid, registry-accepted mappings with Recall@1,
  Recall@2, Recall@4, and MRR of 1.0 on this single tier.
- The leave-one-question-out majority baseline reached Recall@1 of 4/6, MRR of
  0.777778, and exact set of 0/6.
- The Terra no-compiler and compiler ablations share the same mapping artifacts.
  The compiler added 6/6 separating probes and 6/6 reproduced probe hashes; it did
  not change mapping metrics.
- Total provider-derived cost was `$0.253746`, or `$0.042291` per record across
  both models. Model-call latency was p50 2,953 ms and p95/p99 8,730 ms.
- These six author-reviewed project fixtures are not independent educator
  adjudication and do not support a generalized model-accuracy, learner,
  classroom, learning-effect, time-saving, adoption, or routing claim.

Learner responses collected: 0

## Security and public stress evidence

50 concurrent submissions

1 accepted and 49 conflicted

2 pre-submit GETs

Exact replay: HTTP 200

Post-deletion read: HTTP 404

145 targeted security tests passed

8 Playwright journeys passed

Tested preview SHA: `6a7d848b9444a63b4ed62571e55b735c644b39ed`

- The public stress run created one disposable de-identified workflow, confirmed
  GET did not consume its learner capability, accepted exactly one of 50
  concurrent submissions, returned the original receipt for exact replay,
  persisted deterministic evidence and seven audit events, then deleted the
  educational record.
- Repository hygiene, OpenAPI drift, and the Postgres migration round trip passed.
  npm and Python dependency audits reported zero known vulnerabilities.
- Security review added a 32 KiB raw request-body cap at the public proxy and API
  boundary. External access to Render Postgres was disabled and a credentialed
  external connection was blocked while internal application health remained OK.
- This was not a third-party penetration test. The free preview has no documented
  distributed application rate limiter; provider and cost circuit breakers are
  the current abuse bounds.

## Production status

- Public preview: <https://cognisect.vercel.app>.
- The stress report verified Render's deployment metadata and the SHA above,
  `/health` returned HTTP 200, and `/version` returned `0.1.0`.
- The preview uses free Vercel, Render web, and Render Postgres resources. It may
  cold-start and has no production-grade guarantee for backups, high
  availability, alerting, or long-term retention.
- The current public service is a time-limited preview, not a durable classroom
  production deployment.

## Explicitly unavailable evidence

Educator usability review: not conducted

- Three KSU outreach messages were sent by the project owner. No educator
  response, consent, review session, approval, or usability result is recorded or
  claimed.
- Authentic learner records: 0.
- Evaluated learner responses: 0.
- Full interactive evaluation: not run because no real learner responses were
  collected.
- Classroom adoption, learning improvement, diagnostic accuracy, and teacher time
  savings: not measured and not claimed.

## Machine-readable sources

- `data/evaluation/protocol.v1.json`
- `data/evaluation/benchmark-report.v1.json`
- `data/security/security-audit.v1.json`
- `data/security/production-stress-report.v1.json`
