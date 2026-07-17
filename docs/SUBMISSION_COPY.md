# Submission copy

All text below is claim-limited to the checked-in fact sheet. Update it only by
updating the evidence reports and their release-claim tests first.

## Project name

COGNISECT

## Tagline

Compile the next question, not a diagnosis.

## Short description

COGNISECT helps a secondary mathematics teacher compare constrained explanations
for one signed-integer error. GPT-5.6 ranks curated rule hypotheses; a deterministic
Counterexample Compiler finds a small follow-up problem that separates them, and
the teacher controls the probe and final note.

## Full description

A learner's wrong answer can fit more than one plausible procedure. Asking a model
to choose one explanation can turn uncertainty into an unjustified diagnosis.
COGNISECT takes a narrower approach: it helps the teacher test competing
explanations for signed-integer subtraction while preserving the option to
abstain.

The teacher selects one of six provenance-cleared, educator-authored fixtures or
enters a de-identified case. GPT-5.6 maps the observed work to two to four instances
of a closed rule registry. The application validates those instances with a safe
interpreter and merges semantically equivalent truth tables. The self-built
Counterexample Compiler then searches every bounded subtraction problem and ranks
the smallest question on which the leading valid rules disagree.

Nothing reaches the learner automatically. The teacher first reviews and approves
the probe. A separate opaque link opens a minimal learner page, where one exact
signed integer is recorded atomically. The deterministic updater marks represented
hypotheses as supported, weakened, or unresolved; ambiguous or out-of-registry
evidence causes abstention. The teacher then approves, edits, rejects, or abstains
on the final note, and the persisted audit record is read back from Postgres.

The compiler proves disagreement between formalized rules. It does not prove a
learner's cognitive state.

## How it was built

Codex was used to turn the product specification into a tested vertical slice:
the versioned rule registry, independent semantic oracle, exhaustive compiler,
FastAPI contracts, Postgres schema and migrations, LangGraph interrupt/resume
workflow, Next.js teacher and learner routes, generated TypeScript client,
Playwright journeys, deployment manifests, benchmark runner, security audit, and
release evidence.

GPT-5.6 Terra performs the default constrained hypothesis mapping and drafts the
teacher-facing instructional note. GPT-5.6 Sol is available for bounded ambiguous
case review under the frozen router. Neither model can author executable rules,
release a learner probe, determine authorization, update evidence, or approve the
final note.

The backend uses Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic, LangGraph,
and Postgres. The frontend uses Next.js App Router, React, strict TypeScript, and a
same-origin API proxy. Vercel serves the public frontend; Render hosts the API and
Postgres preview.

## Evidence and testing

The frozen comparison made 12 live model calls: Terra and Sol each processed the
same six educator-authored fixtures. Both returned schema-valid, registry-accepted
outputs on all six. Terra matched the complete expected rule set on four cases and
Sol on five. The compiler produced a separating, reproducible probe for all six
Terra mappings. This is a harness result over project-authored fixtures, not an
accuracy estimate or evidence about learners.

The benchmark contains zero learner responses, so the full interactive evaluation
was not run. The optional educator usability review has not been conducted, and no
pilot, educator approval, classroom adoption, learning improvement, or time-saving
claim is made.

The public concurrency gate issued 50 submissions against one learner capability:
one accepted submission and 49 conflicts. Two prior GETs did not consume the
capability, exact replay returned the original receipt, the audit survived readback,
and deletion made the record unavailable. The release evidence also records 145
targeted security tests and 8 desktop/mobile Playwright journeys passing, with no
known vulnerabilities reported by the checked npm and Python dependency audits.

## Privacy and safety

COGNISECT asks for de-identified educational content only and stores no student
identifier or roster. Teacher ownership and learner response links use separate,
high-entropy capabilities whose verifiers are hashed at rest. Cross-owner failures
are non-enumerating. Learner pages use private no-store responses, no referrer, and
no third-party analytics. Raw request bodies are capped at 32 KiB, and the public
database does not accept external connections.

The evidence vocabulary is deliberately limited to ranked hypothesis, consistent
with, supported, weakened, unresolved, abstained, deterministic, and
teacher-reviewed. Teacher approval remains mandatory before a final note can be
accepted.

## Challenges

The hardest engineering problem was preserving uncertainty through an end-to-end
workflow. It required a closed formal language, truth-table canonicalization,
deterministic counterexample search, atomic single-use response handling, durable
interrupt/resume, and an audit trail that separates generated proposals from human
edits. A second challenge was making every public number reproducible without
mistaking fixtures or fake-model tests for learner evidence.

## Accomplishments

- A complete teacher → learner → teacher workflow backed by Postgres and durable
  LangGraph state.
- A deterministic Counterexample Compiler that releases only separating probes.
- A strict authorization and replay model that accepted exactly one of 50
  concurrent submissions.
- A frozen live-model comparison with item-level telemetry, costs, failures, and
  explicit limits.
- Accessible desktop and mobile journeys exercised with Playwright, reduced motion,
  keyboard navigation, axe checks, slow-network states, replay, expiry, abstention,
  and deletion.

## What comes next

The next evidence step is one consented educator usability review using the fixed
six-case protocol, followed by one documented product change and rerun. A later,
separately approved study would be required before making claims about authentic
learner responses, classroom use, diagnostic performance, time savings, or learning
effects. The free public preview would also need paid, monitored infrastructure and
a distributed rate limiter before being represented as a durable production service.

## Links

- Live preview: <https://cognisect.vercel.app>
- Source: <https://github.com/StephenSook/cognisect>
