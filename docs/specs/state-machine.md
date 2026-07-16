# Workflow state machine

```text
CREATED
→ ANALYZING
→ PROBE_READY
→ AWAITING_RESPONSE
→ RESPONSE_RECORDED
→ RESUME_PENDING
→ UPDATING
→ AWAITING_REVIEW
→ APPROVED | EDITED | REJECTED | ABSTAINED | FAILED
```

Every edge is explicit and compare-and-swap guarded. `ABSTAINED` and `FAILED` are reachable from bounded validation or runtime failure paths. `APPROVED`, `EDITED`, `REJECTED`, `ABSTAINED`, and `FAILED` are terminal. A rejected or abstained workflow can never emit an approved note.

Interrupt boundaries occur after the compiled probe is persisted and before teacher probe approval, and after deterministic evidence is persisted and before teacher review. Resumption uses the stable workflow `thread_id`; replayed commands must return the existing result without duplicating side effects.
