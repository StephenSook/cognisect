# Rule registry v1

Version: `rule_registry.v1`  
Compiler version: `counterexample_compiler.v1`  
Domain: ordered pairs `(a, b)` in `[-12, 12]²`, interpreted as `a - b`.

## Semantics

The correct reference rule is `a - b`. It is an oracle only and can never be accepted as an alternative hypothesis.

The closed alternative registry contains six total, parameter-free functions:

| Template ID | Total function | Teacher-facing description |
| --- | --- | --- |
| `add_subtrahend` | `a + b` | Treats the subtraction sign as addition without taking the opposite of the second integer. |
| `ignore_subtrahend_sign` | `a - abs(b)` | Reads the second integer's magnitude but ignores its negative sign. |
| `absolute_difference` | `abs(abs(a) - abs(b))` | Subtracts the smaller magnitude from the larger and reports a non-negative answer. |
| `subtract_magnitudes` | `abs(a) - abs(b)` | Removes both integer signs, then keeps the written subtraction order. |
| `keep_minuend_sign` | `sign(a) * abs(abs(a) - abs(b))`, with `sign(0) = 1` | Finds the magnitude difference and gives it the first integer's sign. |
| `negative_magnitude_sum` | `-(abs(a) + abs(b))` | Adds magnitudes and makes the answer negative when a minus sign is present. |

These are constrained behavioral hypotheses, not diagnoses or claims about stable learner beliefs. The registry is grounded in published reports of whole-number overgeneralization, confusion between unary and binary minus, sign omission, magnitude-only strategies, and negative-sum strategies. Initial sources include Vlassis (2004), Bofferding-related integer reasoning work, and Maphosa (2017); educator review is still required before public validation claims.

## Instance contract

Every instance has exactly:

- `template_id`: one of the six IDs above.
- `evidence_refs`: one or more unique references to supplied work segments, maximum eight.
- `description`: a teacher-readable description from 1 to 280 characters.
- `rank`: integer from 1 through 4, unique within one model result.

No executable expression, code, arbitrary parameter, nested payload, or additional property is accepted.

## Acceptance pipeline

1. Parse the strict JSON schema.
2. Resolve the template through an explicit mapping.
3. Execute all 625 inputs through both the interpreter and an independent semantic oracle.
4. Canonicalize by the SHA-256 hash of the ordered truth table.
5. Merge equivalent alternatives, preserving the best rank and all evidence references.
6. Reject any truth table equal to the correct rule.
7. Require at least two distinct accepted alternatives for probe compilation; otherwise abstain or route once for repair.

## Versioning

Any semantic change creates a new registry version. Existing workflow records retain the exact registry and compiler versions and remain reproducible under their original implementation.

## References

- Vlassis, J. (2004), *Making sense of the minus sign or becoming flexible in negativity*, Learning and Instruction, 14(5), 469–484. https://doi.org/10.1016/j.learninstruc.2004.06.012
- Bofferding, L. (2014), *Negative integer understanding: Characterizing first graders' mental models*, Journal for Research in Mathematics Education, 45(2), 194–245. https://doi.org/10.5951/jresematheduc.45.2.0194
- Maphosa, C. (2017), *A Study of Errors and Misconceptions in the Learning of Addition and Subtraction of Directed Numbers in Grade 8*, SAGE Open. https://doi.org/10.1177/2158244016671375
