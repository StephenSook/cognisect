# COGNISECT Galaxy Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the highest-ceiling truthful COGNISECT submission by exposing the real 625-domain compiler proof, completing human custody and provenance, hardening production, and binding all public claims to final evidence.

**Architecture:** Extend the existing deterministic compiler with a pure explanation object and derive it from the same ranking pass that selects the probe. Expose only owner-authorized proof and receipt DTOs, keep learner DTOs minimal, and add production controls around the existing FastAPI/Postgres boundary. Preserve the current industrial evidence-workbench frontend while making the judge path fixture-first, progressive, and complete.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy 2 async, PostgreSQL 17, Alembic, LangGraph, OpenAI Responses API, Next.js 16.2.10, React 19.2.7, TypeScript, Vitest, Playwright, Axe, GitHub Actions, Render, Vercel.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-17-cognisect-galaxy-design.md` verbatim.
- Use red-green-refactor TDD for every behavior change. Record the failing command and expected failure before production code.
- Do not add diagnosis, confidence, learning-outcome, adoption, time-saving, or educator-validation claims.
- Do not add mock data, demo bypasses, auth bypasses, or a second source of compiler truth.
- Public copy must use `closed, literature-grounded rule registry`, never `educator-reviewed`.
- Every compiler number displayed by the frontend must come from backend deterministic output.
- Learner responses remain one strict signed integer plus optional review-only rationale.
- Receipt output must exclude raw observed work, learner rationale, capability URLs/tokens, owner cookies, provider credentials, and generated prose.
- Use Python 3.12 and Node 22.22.2 for every verification command.
- Preserve backward-compatible public routes unless the task explicitly adds a new route.
- Keep `main` untouched until the feature branch passes the complete verification and review gates.

---

### Task 1: Truth and submission eligibility guardrails

**Files:**
- Modify: `backend/tests/test_release_claims.py`
- Modify: `README.md`
- Modify: `frontend/src/app/page.tsx`
- Modify: `docs/EVALUATION.md`
- Modify: `docs/specs/rule-registry-v1.md`

**Interfaces:**
- Consumes: checked-in benchmark, security, and stress evidence JSON.
- Produces: public copy that cannot claim educator review and a release test that rejects regression.

- [ ] **Step 1: Write the failing release-claim tests.** Add assertions that the combined public surfaces contain `closed, literature-grounded`, contain `Codex`, contain the five-step final teacher review, and do not contain `educator-reviewed`, `validated by educators`, or a standalone confidence claim.
- [ ] **Step 2: Run `uv run pytest backend/tests/test_release_claims.py -q` and verify it fails because the current README and landing page contain `educator-reviewed` and omit Codex.**
- [ ] **Step 3: Replace the contradictory wording and add an accurate README `How Codex helped build COGNISECT` section.** Attribute the deterministic core to `af43cc2`, durable Postgres workflow to `2b9fd53`, Responses workflow to `42e5bef`, and full vertical slice to `9884be9`. State that product scope, evidence vocabulary, privacy boundaries, human gates, and final claim decisions were human decisions.
- [ ] **Step 4: Extend the judge path to save and read back the final teacher decision.** Do not publish a `/feedback` ID unless the real value is available.
- [ ] **Step 5: Run the focused test, `uv run python scripts/check_public_repo.py`, and `rg -n -i 'educator-reviewed|validated by educators' README.md docs frontend/src`; expect tests and hygiene to pass and search to return no unsupported public claim.**
- [ ] **Step 6: Commit with `docs: restore truthful Codex and review evidence`.**

### Task 2: Deterministic compiler proof contract

**Files:**
- Modify: `backend/src/cognisect/compiler.py`
- Modify: `backend/src/cognisect/api_models.py`
- Modify: `backend/src/cognisect/services.py`
- Modify: `backend/tests/test_compiler.py`
- Modify: `backend/tests/test_workflow_services.py`
- Modify: `backend/tests/test_api_contracts.py`
- Modify: `openapi/openapi.json`
- Modify: `frontend/src/lib/api/schema.d.ts`
- Modify: `frontend/tests/fixtures.ts`

**Interfaces:**
- Produces: `CompilerCandidateProof`, `CompilerSearchProof`, and `CompiledProbeResponse.proof`.
- `CompilerSearchProof` fields are `domain_problem_count`, `eligible_candidate_count`, `separating_candidate_count`, `chosen_candidate_rank`, and `top_candidates`.
- Each candidate exposes `problem`, ordered `predictions`, `distinct_output_count`, `top_two_separated`, `distinguished_pair_count`, `operand_magnitude`, `correct_result_magnitude`, and `rank`.

- [ ] **Step 1: Add failing compiler tests.** Assert a 625-problem domain, 624 eligible candidates after excluding the original, exact separating count from an independent oracle, at most five finalists, stable ranking across input order, chosen rank one, and equality between the first proof candidate and the compiled probe.
- [ ] **Step 2: Run the focused tests and verify failure because no proof contract exists.**
- [ ] **Step 3: Refactor the existing compiler candidate loop into one pure ranking pass that returns both `CompiledProbe` and `CompilerSearchProof`.** Do not execute any rule outside the existing frozen interpreter. Do not change the specification hash payload or compiler version.
- [ ] **Step 4: Reconstruct accepted hypotheses from persisted accepted records inside teacher DTO assembly, derive the proof, and fail closed if its chosen problem or predictions do not reproduce the persisted probe.**
- [ ] **Step 5: Add strict Pydantic proof DTOs and attach `proof` to `CompiledProbeResponse`.**
- [ ] **Step 6: Run compiler, service, contract, property, and hash-reproduction tests.**
- [ ] **Step 7: Regenerate OpenAPI and TypeScript types using the repository generators, then run `uv run pytest backend/tests/test_openapi.py -q` and `npm --prefix frontend run check:api`.**
- [ ] **Step 8: Commit with `feat: expose deterministic compiler proof`.**

### Task 3: Provenance and review-only learner context

**Files:**
- Modify: `backend/src/cognisect/api_models.py`
- Modify: `backend/src/cognisect/db_models.py`
- Modify: `backend/src/cognisect/services.py`
- Create: `backend/alembic/versions/e3b1c7d9a205_case_provenance.py` with `down_revision = "a61bd8e7c204"`
- Modify: `frontend/src/components/lab-form.tsx`
- Modify: `frontend/src/components/report-view.tsx`
- Modify: `backend/tests/test_api_contracts.py`
- Modify: `backend/tests/test_workflow_services.py`
- Modify: `backend/tests/test_persistence_contracts.py`
- Modify: `frontend/tests/forms.test.tsx`
- Modify: `frontend/tests/route-content.test.tsx`

**Interfaces:**
- `CreateCaseRequest.provenance_record_id: str | None`, accepted only for `educator_authored` input and forbidden for custom or other tiers. The public-exemplar frontend path always supplies it; free educator entry leaves it null.
- `WorkflowResponse.provenance_record_id: str | None`.
- `WorkflowResponse.learner_rationale: str | None` is owner-only and review-only.

- [ ] **Step 1: Add failing request validation, persistence, migration, and frontend payload tests for `cognisect-ea-001`.**
- [ ] **Step 2: Verify failures are caused by the absent fields/column.**
- [ ] **Step 3: Add the nullable case provenance column and request validator.** Preserve existing rows as null; do not infer historical provenance.
- [ ] **Step 4: Persist and return the provenance ID to the teacher.** Default the lab to the first public exemplar and send the selected ID with `source_tier: educator_authored`.
- [ ] **Step 5: Return the persisted learner rationale only on the owner-authorized workflow DTO and label it `Review-only learner rationale` in the teacher report.** Confirm `evidence.py` remains rationale-independent.
- [ ] **Step 6: Run focused backend/frontend tests and an Alembic downgrade/upgrade round trip.**
- [ ] **Step 7: Commit with `feat: preserve case provenance and review context`.**

### Task 4: Privacy-safe evidence receipt

**Files:**
- Modify: `backend/src/cognisect/api_models.py`
- Modify: `backend/src/cognisect/services.py`
- Modify: `backend/src/cognisect/api.py`
- Create: `backend/src/cognisect/receipt.py`
- Modify: `backend/tests/test_api.py`
- Create: `backend/tests/test_receipt.py`
- Modify: `frontend/src/components/report-view.tsx`
- Create: `frontend/src/components/evidence-receipt-button.tsx`
- Modify: `frontend/tests/route-content.test.tsx`
- Modify: `frontend/tests/e2e/full-loop.spec.ts`

**Interfaces:**
- Adds `GET /v1/workflows/{workflow_id}/receipt` with owner-cookie authorization.
- Returns `EvidenceReceiptResponse` with `receipt_version: evidence_receipt.v1` and `receipt_hash` over canonical JSON excluding the hash field.

- [ ] **Step 1: Write failing tests for authorization, deterministic hashing, audit ordering, proof inclusion, and forbidden-content absence.** Include sentinel values for observed work, rationale, capability token, generated prose, and owner secret; assert none appear in serialized receipt JSON.
- [ ] **Step 2: Verify the tests fail because the route and sanitizer do not exist.**
- [ ] **Step 3: Implement one canonical receipt builder in `receipt.py`; return only allowlisted DTO fields.**
- [ ] **Step 4: Add the owner-authorized service and route, regenerate OpenAPI/types, and add a download button that names the file `cognisect-evidence-<workflow-id>.json`.**
- [ ] **Step 5: Run focused backend/frontend/E2E tests and inspect one serialized receipt for forbidden fields with `rg`.**
- [ ] **Step 6: Commit with `feat: export privacy-safe evidence receipts`.**

### Task 5: Production retention, abuse control, readiness, and build identity

**Files:**
- Create: `backend/src/cognisect/rate_limit.py`
- Modify: `backend/src/cognisect/config.py`
- Modify: `backend/src/cognisect/db_models.py`
- Modify: `backend/src/cognisect/services.py`
- Modify: `backend/src/cognisect/api.py`
- Create: `backend/alembic/versions/f4c2d8a6b310_rate_limit_windows.py` with `down_revision = "e3b1c7d9a205"`
- Modify: `render.yaml`
- Modify: `.env.example`
- Modify: `backend/tests/test_api.py`
- Create: `backend/tests/test_rate_limit.py`
- Modify: `backend/tests/test_workflow_services.py`
- Modify: `docs/SECURITY.md`
- Modify: `docs/DEPLOYMENT.md`

**Interfaces:**
- `PostgresRateLimiter.consume(scope: str, key_material: str, limit: int, window_seconds: int) -> RateLimitDecision`.
- Production settings include `abuse_key_pepper`, `case_creation_limit_per_hour`, `analysis_limit_per_hour`, and `retention_interval_seconds=21600`.
- Adds `GET /ready`; `VersionResponse.source_revision` is `development` or a 40-character lowercase Git SHA.

- [ ] **Step 1: Write failing atomic limiter tests, including concurrent consumption where exactly the configured limit succeeds.** Assert only HMAC bucket values are stored and HTTP 429 includes `Retry-After`.
- [ ] **Step 2: Write failing lifespan tests proving retention runs once, repeats on the configured interval, logs failure without killing the API, and cancels cleanly.**
- [ ] **Step 3: Write failing readiness/version tests for Alembic-head mismatch and source-revision validation.**
- [ ] **Step 4: Implement the Postgres table, atomic upsert limiter, dedicated pepper, route guards, and expired-bucket purge.** Never persist a raw IP address.
- [ ] **Step 5: Add the cancellable production lifespan retention task and readiness/build identity.** Keep `/health` backward compatible.
- [ ] **Step 6: Update Render/env/security/deployment documentation with exact settings and honest residual limits.**
- [ ] **Step 7: Run focused concurrency tests, full API tests, Alembic downgrade/upgrade, Ruff, and mypy.**
- [ ] **Step 8: Commit with `feat: harden public production boundary`.**

### Task 6: Correct OpenAI response and request telemetry

**Files:**
- Modify: `backend/src/cognisect/model_analyzer.py`
- Modify: `backend/src/cognisect/services.py`
- Modify: `backend/src/cognisect/db_models.py`
- Modify: `backend/src/cognisect/api_models.py`
- Create: `backend/alembic/versions/a5d3e9b7c421_model_response_identity.py` with `down_revision = "f4c2d8a6b310"`
- Modify: `backend/tests/test_model_analyzer.py`
- Modify: `backend/tests/test_model_persistence.py`
- Modify: `backend/tests/test_api_contracts.py`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- `ModelCallTelemetry.response_id` stores `response.id`.
- `ModelCallTelemetry.request_id` stores `response._request_id`.
- Workflow exposes `model_response_id` and `model_request_id` separately.

- [ ] **Step 1: Add failing analyzer tests for separate IDs and returned-model mismatch policy failure.**
- [ ] **Step 2: Verify the existing implementation fails because it maps `response.id` into `request_id` and accepts model mismatch.**
- [ ] **Step 3: Implement strict separation, persistence, DTOs, and migration.** The mismatch path must not return parsed hypotheses to the compiler.
- [ ] **Step 4: Regenerate OpenAPI/types and run analyzer, persistence, benchmark, contract, and live-call artifact checks.**
- [ ] **Step 5: Commit with `fix: preserve provider telemetry identity`.**

### Task 7: Galaxy judge and teacher experience

**Files:**
- Create: `frontend/src/components/compiler-proof-lens.tsx`
- Create: `frontend/src/components/counterfactual-preview.tsx`
- Create: `frontend/src/components/judge-tour.tsx`
- Modify: `frontend/src/components/evidence-topology.tsx`
- Modify: `frontend/src/components/workflow-panel.tsx`
- Modify: `frontend/src/components/report-view.tsx`
- Modify: `frontend/src/components/lab-form.tsx`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/app/globals.css`
- Create: `frontend/tests/compiler-proof-lens.test.tsx`
- Modify: `frontend/tests/evidence-topology.test.tsx`
- Modify: `frontend/tests/forms.test.tsx`
- Modify: `frontend/tests/route-content.test.tsx`
- Modify: `frontend/tests/e2e/full-loop.spec.ts`

**Interfaces:**
- Consumes `CompiledProbeResponse.proof`; never recomputes compiler counts in TypeScript.
- `CounterfactualPreview` consumes persisted predictions and renders an explicit `Counterfactual preview, not observed evidence` label.

- [ ] **Step 1: Add failing component tests for 625 -> 624 -> separating count -> one chosen probe, semantic finalist table, counterfactual labeling, default public case, saved note/rationale, and guided-tour steps.**
- [ ] **Step 2: Verify the tests fail because the new components and default state do not exist.**
- [ ] **Step 3: Implement the proof lens with the existing industrial evidence-workbench aesthetic, CSS-only restrained motion, reduced-motion fallback, and real backend values.**
- [ ] **Step 4: Place probe approval immediately after the proof summary. Collapse the duplicate evidence table by default on desktop while preserving keyboard and screen-reader access.**
- [ ] **Step 5: Implement exponential polling delays of 2, 4, 8, and 15 seconds, resetting to 2 seconds after a successful state change.**
- [ ] **Step 6: Add the live judge rail across landing, lab, workflow, learner handoff instruction, report, and receipt without bypassing any real action.**
- [ ] **Step 7: Run component tests, lint, typecheck, build, and desktop/mobile Playwright with Axe and reduced motion.**
- [ ] **Step 8: Apply the React best-practices checklist to every changed TSX file and fix all critical/high issues.**
- [ ] **Step 9: Commit with `feat: reveal the 625-to-1 compiler proof`.**

### Task 8: Dedicated learner layout

**Files:**
- Modify: `frontend/src/app/layout.tsx`
- Create: `frontend/src/app/(teacher)/layout.tsx`
- Move without changing URLs: teacher pages into `frontend/src/app/(teacher)/...`
- Create: `frontend/src/app/(learner)/layout.tsx`
- Move without changing URL: `frontend/src/app/respond/[token]/page.tsx` to `frontend/src/app/(learner)/respond/[token]/page.tsx`
- Modify: `frontend/src/app/globals.css`
- Modify: `frontend/tests/route-content.test.tsx`
- Modify: `frontend/tests/e2e/full-loop.spec.ts`

**Interfaces:**
- Root layout owns only document/fonts/global CSS.
- Teacher layout owns brand navigation, runtime status, main width, and footer.
- Learner layout owns a minimal no-navigation shell.

- [ ] **Step 1: Add failing route/E2E assertions that `/respond/*` contains no Lab, Runtime evidence, registry status, or teacher footer while teacher routes retain them.**
- [ ] **Step 2: Verify the learner route fails those assertions under the current root layout.**
- [ ] **Step 3: Introduce route groups and separate layouts without changing public URLs or metadata.**
- [ ] **Step 4: Run route tests, Next production build, all Playwright journeys, mobile reflow, and Axe.**
- [ ] **Step 5: Commit with `feat: isolate the learner experience`.**

### Task 9: Dependency and CI custody

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/SECURITY.md`
- Modify: `docs/DEPENDENCY_LICENSES.md` if generated output changes

**Interfaces:**
- TypeScript and ESLint versions must satisfy every installed plugin's declared peer range.
- CI pip-audit command uses `uv export --frozen --no-hashes --no-dev --no-emit-project | uvx --python 3.12 pip-audit -r /dev/stdin`.

- [ ] **Step 1: Capture the current `npm ci` peer warnings as the failing dependency-custody check.**
- [ ] **Step 2: Pin supported TypeScript 6 and ESLint 9 versions compatible with Next 16.2.10 and installed plugins, regenerate the lockfile, and verify `npm ci` emits no peer override warning.**
- [ ] **Step 3: Add frozen Python auditing to the CI hygiene job and update verification documentation.**
- [ ] **Step 4: Run npm clean install, lint, typecheck, tests, build, npm audit, pip-audit, and dependency-license drift.**
- [ ] **Step 5: Commit with `chore: align toolchain and dependency auditing`.**

### Task 10: Final evidence, submission surfaces, and truth audit

**Files:**
- Modify: `README.md`
- Modify: `docs/EVALUATION.md`
- Modify: `docs/SECURITY.md`
- Modify: checked-in evidence only through their official generation scripts
- Modify outside public repo after code freeze: private `FACT_SHEET.md`, `SUBMISSION_COPY.md`, demo script/storyboard, Obsidian COGNISECT project/session/decision notes, and Codex project resume memory

**Interfaces:**
- Final submission evidence binds to one full Git SHA and exact production deployment IDs.
- Devpost requires Education category, public repository, public YouTube URL under three minutes, live URL, and real `/feedback` session ID.

- [ ] **Step 1: Run the complete local quality matrix under Python 3.12 and Node 22.22.2.**
- [ ] **Step 2: Run final whole-branch spec and code-quality review; fix every Critical or Important finding and re-review.**
- [ ] **Step 3: Push a review branch and require all six GitHub CI jobs to pass before merge.**
- [ ] **Step 4: Merge through GitHub, verify Render and Vercel serve the merged SHA through `/version`, and rerun live desktop/mobile browser QA.**
- [ ] **Step 5: Run the disposable 50-way production stress, exact replay, audit, receipt, and deletion flow against the final SHA.**
- [ ] **Step 6: Regenerate the private fact sheet and Devpost copy from final evidence.**
- [ ] **Step 7: Create a sub-three-minute demo script and storyboard centered on the live 625 -> 1 proof, Codex collaboration, GPT-5.6 boundary, both teacher gates, and exact production verification.**
- [ ] **Step 8: Capture the real `/feedback` ID from the primary build thread; if unavailable, block submission rather than inventing it.**
- [ ] **Step 9: Create/update the Devpost draft, upload the final thumbnail and public video URL, and perform a cross-surface truth audit before submission.**
- [ ] **Step 10: Submit only after every required field and public link is independently verified.**
- [ ] **Step 11: Write the final SHA, deployments, tests, claims, outreach status, submission state, and any residual limits into Obsidian and second-brain memory.**
