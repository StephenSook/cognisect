# Data tiers and display gate

Every evaluated or displayed record requires a provenance ledger entry with source URL and record ID, license/version, retrieval date, SHA-256 content hash, tier, transformation history, redistribution permission, public-display permission, label source, and adjudication status.

Allowed tiers are `authentic`, `synthetic`, `mixed`, `published_exemplar`, `educator_authored`, and `custom`. Metrics are reported separately by tier. Splits are by question and source ancestry; paraphrases stay with their source. Restricted Kaggle data remains local and ignored. No record enters the judged experience unless display and attribution are documented.
