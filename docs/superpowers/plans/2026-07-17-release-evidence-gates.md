# Release Evidence Gates Implementation Plan

> **Execution rule:** Work only from `feat/release-evidence-gates` in the isolated worktree. Preserve the frozen evaluation inputs and production prompt; do not tune either after live results are observed.

**Goal:** Produce claim-limited benchmark, security/stress, educator-outreach, and submission evidence for the shipped COGNISECT release without inventing learner or educator validation.

**Architecture:** Add an evaluation-only runner that calls the same frozen Terra and Sol Responses API contracts used by production, then computes deterministic metrics and compiler ablations from sanitized structured artifacts. Add an opt-in production stress runner that exercises one disposable workflow and records only aggregate, non-secret evidence. Keep KSU identities and email drafts outside the public repository. Generate public claims from checked-in report artifacts.

**Tech stack:** Python 3.12, Pydantic, official OpenAI Responses API, FastAPI/Postgres integration tests, httpx, Next.js, Playwright, GitHub Actions.

---

## Task 1: Freeze the evaluation protocol and repair the clean baseline

**Files:**

- Create: `data/evaluation/protocol.v1.json`
- Modify: `scripts/generate_openapi.py`
- Test: `backend/tests/test_evaluation_protocol.py`

1. Add a failing protocol test that requires exact manifest, provenance-ledger, prompt-source, registry, route, and model identifiers plus SHA-256 digests.
2. Check in `protocol.v1.json` with the already-recorded frozen hashes: manifest `d246b355...953d0`, ledger `a2a3a4d...c67a`, and prompt source `c4f6044...39bc1`.
3. Fix the pre-existing mypy failure by passing `SecretStr` values to `Settings` in `scripts/generate_openapi.py`.
4. Run the protocol test, Ruff, and mypy over backend and scripts.
5. Commit as `test(evaluation): freeze release benchmark protocol` and push.

## Task 2: Implement and run model baselines and compiler ablations

**Files:**

- Create: `backend/src/cognisect/benchmark.py`
- Create: `scripts/run_model_benchmark.py`
- Create: `data/evaluation/benchmark-report.v1.json`
- Modify: `backend/src/cognisect/model_analyzer.py` only if a response-contract helper must be made reusable without changing production behavior
- Modify: `docs/EVALUATION.md`
- Test: `backend/tests/test_benchmark.py`
- Test: `backend/tests/test_model_benchmark_script.py`

1. Write failing tests for leave-one-question-out majority predictions, recall@K, MRR, exact-set rate, selective risk/coverage, per-tier aggregation, latency percentiles, cost totals, schema/registry acceptance, and item-level failure output.
2. Implement deterministic metric and report builders. Gold labels remain evaluation-only and never enter prompts.
3. Write fail-closed script tests: no `--live` or no key produces no claimed live report; mismatched model IDs, invalid structured output, excess calls, or digest drift fail without writing output.
4. Implement exact one-call Terra and Sol comparisons over the same six frozen educator-authored records using `analysis_prompt.v2`, strict structured output, `store=False`, no hidden reasoning request, stable cache keys, and a maximum of two calls per record.
5. Derive four reported comparisons from the frozen calls: leave-one-question-out majority label; direct GPT structured classification; hypothesis mapping without compiler; GPT mapping plus compiler without learner response. Leave the full interactive comparison `NOT RUN` because no real learner responses exist.
6. Record request IDs, returned model IDs, prompt hashes, token details, cost, and latency, but no educational content, API key, owner capability, or learner token.
7. Load the ignored owner `.env` explicitly for the live command without copying or printing it. Run once, persist the sanitized report, and do not modify the prompt or manifest afterward.
8. Regenerate `docs/EVALUATION.md` tables from the report and state the six-item educator-authored limitation prominently.
9. Run targeted tests and report verification.
10. Commit as `feat(evaluation): add frozen baselines and compiler ablations` and push.

## Task 3: Complete application security and production stress gates

**Files:**

- Create: `scripts/run_production_stress.py`
- Create: `data/security/production-stress-report.v1.json`
- Modify: `docs/SECURITY.md`
- Test: `backend/tests/test_production_stress_script.py`
- Test: existing `backend/tests/test_api.py`
- Test: existing `backend/tests/test_workflow_services.py`
- Test: existing `backend/tests/test_prompts_and_routing.py`
- Test: existing `frontend/tests/e2e/full-loop.spec.ts`

1. Write fail-closed stress-script tests covering explicit `--live`, HTTPS base URL, exact served SHA, content-free output, 50 distinct idempotency keys, exactly one accepted response, conflict/replay handling, and cleanup on success/failure.
2. Implement one disposable, de-identified educator-authored workflow against the public same-origin API. Never print or persist owner cookies, learner URLs, tokens, observed work, or answers.
3. Run the existing 50-way local Postgres race, ownership matrix, expiration/replay, restart/resume, deletion/tombstone, prompt-injection, logging-redaction, resource-bound, and strict-input tests.
4. Run repository hygiene/secret checks, `npm audit`, a Python dependency audit, OpenAPI drift, migrations, and container configuration.
5. Run the live 50-way submission stress once, require exactly one accepted response, verify persisted readback, then delete the disposable workflow. Persist only aggregate results and served SHA.
6. Run Playwright desktop/mobile/reduced-motion/expired/duplicate/abstention journeys after the API stress gate.
7. Update `docs/SECURITY.md` with exact audited locations, four-area findings, commands, residual provider limits, and the production stress result.
8. Commit as `test(security): add auditable production stress gate` and push.

## Task 4: Research KSU reviewers and create email drafts without making review claims

**Private files outside Git:**

- Create: `reference-materials/private/ksu-outreach/2026-07-17-research.md`
- Create: `reference-materials/private/ksu-outreach/2026-07-17-gmail-drafts.md`
- Modify: `docs/EDUCATOR_REVIEW.md`

1. Research current Kennesaw State University mathematics education, secondary education, tutoring, and teacher-education contacts using official KSU profile/directory pages and primary publications.
2. Rank at most three suitable contacts by direct role/research fit. Record official source URLs, current public role, one evidence-backed personalization point, and public institutional email in the private research note.
3. Draft three short peer-to-peer messages with lowercase two-to-four-word subjects, one specific personalization, a 20–25 minute low-friction ask, no students or records, and separate consent for any public attribution.
4. Recheck Gmail connector availability. If available, create drafts only and verify draft IDs; never send. If unavailable, preserve the exact drafts privately and report the connector blocker.
5. Update the public protocol to state outreach status separately from session status. Keep all pilot, validation, educator-approval, adoption, and usability-result claims removed until a real consented session and rerun occur.

## Task 5: Generate the final fact sheet and submission copy from evidence

**Files:**

- Modify: `docs/FACT_SHEET.md`
- Create: `docs/SUBMISSION_COPY.md`
- Modify: `README.md`
- Create: `backend/tests/test_release_claims.py`

1. Write failing claim tests that bind benchmark counts/rates, production stress counts, test counts, exact served SHA, source tier, zero learner responses, and educator-review status to checked-in evidence files.
2. Generate concise fact-sheet sections for code-audited facts, benchmark facts, security/stress facts, production facts, and explicitly unavailable evidence.
3. Create Devpost-ready title, tagline, short description, full description, built-with list, challenge/approach/implementation sections, demo steps, limitations, and links. Use only allowed evidence vocabulary.
4. Update README figures only where the evidence reports support them; do not add educator-review or learner-impact claims.
5. Run claim tests and public-repository checks.
6. Commit as `docs(release): generate audited fact sheet and submission copy` and push.

## Task 6: Full verification, review, CI, merge, and deployment evidence

**Files:**

- Modify generated reports or docs only when their verification commands prove drift

1. Run Ruff, strict mypy, all backend tests, provenance/evaluation/report checks, OpenAPI drift, frontend lint/typecheck/unit/build, dependency audits, and the complete Playwright suite.
2. Inspect `git diff --check`, `git status --short`, and the complete branch diff for secrets, private identities, unsupported claims, and unrelated changes.
3. Push the final branch and open one atomic PR. Require the six named GitHub checks to complete successfully.
4. Merge only after checks pass; query the merged SHA check-runs and require six completed `success` conclusions.
5. Verify Vercel and Render serve the merged SHA, then run a logged-out public health/version/browser smoke. Do not conflate merge with deploy.
6. Apply the finishing-development-branch procedure and report any external blocker separately from completed code/evidence work.
