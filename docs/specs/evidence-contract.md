# Evidence update contract

The learner response is one JSON integer in the inclusive range `[-10_000, 10_000]`. Booleans, floats, numeric strings, and extra fields are invalid. An optional rationale is review-only and never enters deterministic matching.

- Exactly one alternative prediction matches: that hypothesis is `supported`; other alternatives are `weakened`.
- Multiple alternative predictions match: matching hypotheses are `unresolved`; non-matching alternatives are `weakened`.
- Only the correct answer matches: all alternatives are `weakened`.
- No stored prediction matches: all alternatives are `unresolved`.
- Invalid or out-of-range answer: workflow `abstained`.
- No separating probe: workflow `abstained`.

The update never emits `confirmed`, `proved`, `diagnosed`, or a confidence percentage.
