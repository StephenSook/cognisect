# Evaluation protocol and current evidence

## Evidence boundary

The frozen benchmark contains six author-reviewed, educator-authored fixtures. It
contains zero authentic learner records and zero learner responses. The records
are useful for checking a small labeled harness; they do not support a generalized
model-accuracy, classroom, learning, time-saving, adoption, or educator-approval
claim.

The manifest, provenance ledger, production prompt source, model IDs, route,
registry, compiler, metrics, and maximum call count were frozen in
`data/evaluation/protocol.v1.json` before the live run. Gold labels stayed under
`evaluation_only` and were never serialized into a model prompt. The checked-in
report records item-level predictions, failures, prompt hashes, request IDs, token
usage, latency, and cost without recording observed work or credentials.

Verify both deterministic and model reports with:

```sh
uv run python scripts/validate_provenance.py
uv run python scripts/run_offline_evaluation.py --check
uv run python scripts/run_model_benchmark.py --check
```

## Frozen comparison results

Run timestamp: `2026-07-17T05:42:18Z`. All results below are for the single
educator-authored tier (`n=6`) and must not be pooled with another source tier.

| Comparison | Calls | Coverage | Recall@1 | Recall@2 | Recall@4 | MRR | Exact set |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Leave-one-question-out majority label | 0 | 6/6 | 4/6 | 4/6 | 6/6 | 0.777778 | 0/6 |
| Direct GPT-5.6 Terra structured classification | 6 | 6/6 | 6/6 | 6/6 | 6/6 | 1.0 | 4/6 |
| Terra mapping without compiler | shared | 6/6 | 6/6 | 6/6 | 6/6 | 1.0 | 4/6 |
| Terra mapping plus compiler, no learner response | shared | 6/6 | 6/6 | 6/6 | 6/6 | 1.0 | 4/6 |
| Full interactive workflow | NOT RUN | — | — | — | — | — | — |

“Shared” means the ablations reuse the exact same six Terra mapping artifacts; no
extra model call is counted. The compiler does not change mapping metrics. It adds
a deterministic probe-selection gate: 6/6 Terra mappings were schema-valid and
registry-accepted, 6/6 produced a separating probe, and 6/6 probe hashes reproduced.
This supports the compiler as a safety, auditability, and probe-selection artifact,
not as evidence of an accuracy gain.

Terra and Sol were each called once on the same six records and the same frozen
prompt family. Sol also had 6/6 schema-valid, registry-accepted outputs, Recall@1–4
and MRR of 1.0, and an exact-set rate of 5/6. Terra's exact-set rate was 4/6. This
one small, project-authored tier is insufficient to establish a performance-based
routing rule, so production routing remains unchanged.

## Runtime and cost

The 12 comparison calls cost `$0.253746` in total from provider-reported token
usage, or `$0.042291` per fully evaluated record across both models. There were no
abstained model records, so cost per abstained record is not applicable. Model-call
latency was p50 `2,953 ms`, p95 `8,730 ms`, and p99 `8,730 ms` using nearest-rank
percentiles. Compiler timing is intentionally not published as a stable release
fact because the checked run did not capture a controlled machine benchmark.

## Metric definitions

- Recall@K is the fraction of all records with at least one expected registry
  template in the first K predictions. Abstentions remain in the denominator.
- MRR uses the rank of the first expected template; an abstention contributes zero.
- Exact set requires the predicted and expected template sets to match exactly.
- Coverage is the fraction with a schema-valid mapping. Selective risk@1 is the
  top-ranked error rate among covered records.
- Registry acceptance requires every emitted hypothesis to survive the closed
  interpreter. Unique semantic rule rate is accepted truth tables divided by
  emitted rules.
- Separating-probe and reproduction rates use all six records as their denominator.

The item-level source of truth is `data/evaluation/benchmark-report.v1.json`. The
older `report.v1.json` remains the zero-model deterministic fixture harness and is
kept separately so it cannot be mistaken for live model evidence.

## Unavailable evidence

The full workflow comparison remains `NOT RUN`: the project has not collected a
real learner response for evaluation. The optional KSU usability review has not
occurred. No result in this document is evidence of a learner's cognitive state,
instructional effectiveness, teacher approval, or adoption.
