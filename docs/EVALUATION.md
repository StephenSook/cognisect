# Evaluation protocol and current evidence

## What is currently measured

The checked-in offline runner evaluates the deterministic core on six frozen,
public, educator-authored fixtures. It makes zero model calls and includes zero
learner responses. Its results therefore validate the harness—not hypothesis
mapping accuracy or instructional impact.

Run it with:

```sh
uv run python scripts/validate_provenance.py
uv run python scripts/run_offline_evaluation.py
```

The current deterministic fixture report is reproducible:

| Metric | Result | Scope |
| --- | ---: | --- |
| Registry acceptance rate | 1.0 | Six authored mappings |
| Unique semantic rule rate | 1.0 | Accepted rules / submitted rules |
| Separating-probe rate | 1.0 | Six compiled cases |
| Deterministic reproduction rate | 1.0 | Six probe hashes |
| Abstention rate | 0.0 | This authored fixture set only |

No latency number is checked in because machine-local timing is not a stable
fact. Item-level probe hashes and failures are emitted in the JSON report.

## Frozen protocol for model evidence

When cleared benchmark data and credentials are available, evaluation must:

1. Split by question and source ancestry, keeping paraphrases with their source.
2. Keep held-out labels, distractor mappings, and rubric text outside prompts and
   retrieval.
3. Report authentic, synthetic, mixed, published-exemplar, and authored tiers
   separately.
4. Measure recall@K/MRR only where labels support those metrics, plus schema
   validity, registry acceptance, semantic uniqueness, separating-probe rate,
   reproduction, abstention, selective risk/coverage, latency, and actual cost.
5. Publish item-level failures and never pool incompatible tiers.

The required comparison table is reserved now but remains `NOT RUN`:

| Comparison | Status |
| --- | --- |
| Majority-label baseline | NOT RUN — no cleared labeled benchmark |
| Direct GPT-5.6 structured classification | NOT RUN |
| GPT-5.6 generation without compiler | NOT RUN |
| GPT-5.6 plus compiler without learner response | NOT RUN |
| Full interactive workflow | NOT RUN — no real responses collected |

Terra and Sol must be tested on the same frozen validation manifest before an
evaluation-driven route rule is enabled. A fixture analyzer validates application
tests only and is never counted as a live call.

## Claim boundary

The compiler is presently supported as a safety, auditability, and deterministic
probe-selection artifact. No accuracy gain, cognitive-state conclusion, learning
gain, time reduction, adoption, or educator approval is claimed.
