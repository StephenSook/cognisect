# Dataset card and provenance

## Current public corpus

The repository contains six original educator-authored signed-integer
subtraction fixtures. They are not learner records, authentic classroom work,
or a representative sample. They exist to exercise public-display custody,
schema validation, closed-registry acceptance, deterministic probe compilation,
and the planned six-case educator usability review.

Each fixture is licensed separately under CC BY 4.0 with attribution to the
COGNISECT project authors. Project source code remains Apache-2.0. The canonical
ledger is `data/provenance/public-cases.v1.json`; every content object has a
recomputed SHA-256 hash and explicit redistribution/display permissions.

## Tiers

Allowed labels are `authentic`, `synthetic`, `mixed`, `published_exemplar`,
`educator_authored`, and `custom`. Results must be reported separately by tier.
The current checked-in manifest contains only `educator_authored` records.

## Frozen manifest and leakage control

`data/evaluation/manifest.v1.json` was frozen before model prompt tuning for this
release slice. It groups by question and source ancestry. Runtime input contains
only the problem, observed work, and source tier; adjudicated template targets
live under a separate `evaluation_only` key and are never part of runtime input.

`scripts/validate_provenance.py` fails on missing or extra fields, content-hash
drift, an unknown tier or template, private display status, non-redistributable
content, target/input mismatch, duplicate IDs, and question or ancestry leakage
across splits.

## MAP research source

The MAP competition dataset is not included. Retrieval requires the repository
owner to accept Kaggle's current competition rules. If acquired, raw material
must remain under ignored `data/restricted/`, receive item-level provenance and
redistribution review, and preserve authentic/synthetic/mixed distinctions.
No MAP record may enter the judged interface merely because it is available to
the project locally.

## PII and retention

The schema has no learner name, roster, email, school, or identifier field.
Custom entries require a de-identification attestation. The default application
retention is 30 days; deletion removes workflow educational content and leaves a
content-free tombstone sufficient for replay safety.

## Known limits

- Six authored fixtures cannot estimate model quality or classroom prevalence.
- Author-reviewed labels are not independent educator adjudication.
- No learner answers were collected for this public set.
- The corpus supports harness verification only; it provides no learning-effect
  or classroom-adoption evidence.
