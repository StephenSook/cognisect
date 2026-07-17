"""Privacy-safe evidence receipt allowlist and hashing contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from cognisect.api_models import (
    AcceptedHypothesisResponse,
    AuditEventResponse,
    AuditResponse,
    CompiledProbeResponse,
    CompilerCandidateProof,
    CompilerSearchProof,
    EvidenceStatusResponse,
    ProbePredictionResponse,
    ReviewResultResponse,
    SignedProblemDTO,
    WorkflowResponse,
)
from cognisect.receipt import build_evidence_receipt


def _workflow_with_forbidden_sentinels() -> WorkflowResponse:
    generated_prose = "FORBIDDEN-GENERATED-PROSE-7f3b"
    edited_prose = "FORBIDDEN-EDITED-PROSE-916c"
    rationale = "FORBIDDEN-LEARNER-RATIONALE-a21d"
    capability = "FORBIDDEN-LEARNER-CAPABILITY-cc45"
    moment = datetime(2026, 7, 17, 12, 30, tzinfo=UTC)
    return WorkflowResponse(
        workflow_id=UUID("00000000-0000-4000-8000-000000000001"),
        case_id=UUID("00000000-0000-4000-8000-000000000002"),
        source_tier="educator_authored",
        provenance_record_id="cognisect-ea-001",
        state="EDITED",
        schema_version="workflow.v1",
        registry_version="rule_registry.v1",
        prompt_version="analysis_prompt.v2",
        compiler_version="counterexample_compiler.v1",
        model_snapshot="FORBIDDEN-PROVIDER-METADATA-62af",
        model_request_id="FORBIDDEN-PROVIDER-REQUEST-b1d3",
        learner_response_url=f"https://example.test/respond/{capability}",
        created_at=moment,
        updated_at=moment,
        version=8,
        accepted_hypotheses=[
            AcceptedHypothesisResponse(
                template_id="add_subtrahend",
                evidence_refs=["FORBIDDEN-OBSERVED-WORK-REF-55d1"],
                description="FORBIDDEN-GENERATED-HYPOTHESIS-PROSE-e031",
                rank=1,
                truth_table_hash="a" * 64,
            ),
            AcceptedHypothesisResponse(
                template_id="absolute_difference",
                evidence_refs=["segment-2"],
                description="FORBIDDEN-GENERATED-HYPOTHESIS-PROSE-3cd2",
                rank=2,
                truth_table_hash="b" * 64,
            ),
        ],
        compiled_probe=CompiledProbeResponse(
            original_problem=SignedProblemDTO(a=-3, b=5),
            problem=SignedProblemDTO(a=-2, b=-7),
            correct_prediction=5,
            specification_hash="c" * 64,
            registry_version="rule_registry.v1",
            compiler_version="counterexample_compiler.v1",
            predictions=[
                ProbePredictionResponse(template_id="add_subtrahend", rank=1, prediction=-9),
                ProbePredictionResponse(template_id="absolute_difference", rank=2, prediction=5),
            ],
            proof=CompilerSearchProof(
                domain_problem_count=625,
                eligible_candidate_count=624,
                separating_candidate_count=612,
                chosen_candidate_rank=1,
                top_candidates=[
                    CompilerCandidateProof(
                        problem=SignedProblemDTO(a=-2, b=-7),
                        predictions=[-9, 5],
                        distinct_output_count=2,
                        top_two_separated=True,
                        distinguished_pair_count=1,
                        operand_magnitude=9,
                        correct_result_magnitude=5,
                        rank=1,
                    )
                ],
            ),
        ),
        deterministic_evidence=[
            EvidenceStatusResponse(template_id="add_subtrahend", rank=1, status="weakened")
        ],
        learner_rationale=rationale,
        review_result=ReviewResultResponse(
            decision="edited",
            note="FORBIDDEN-TEACHER-NOTE-40da",
            edited_text=edited_prose,
            created_at=moment,
        ),
        generated_proposal=generated_prose,
        edited_text=edited_prose,
    )


def test_receipt_is_explicit_allowlist_with_proof_stable_audit_and_canonical_hash() -> None:
    moment = datetime(2026, 7, 17, 12, 30, tzinfo=UTC)
    workflow = _workflow_with_forbidden_sentinels()
    audit = AuditResponse(
        workflow_id=workflow.workflow_id,
        events=[
            AuditEventResponse(
                sequence=2,
                from_state="ANALYZING",
                to_state="PROBE_READY",
                version=2,
                occurred_at=moment,
            ),
            AuditEventResponse(
                sequence=1,
                from_state="CREATED",
                to_state="ANALYZING",
                version=1,
                occurred_at=moment,
            ),
        ],
    )

    receipt = build_evidence_receipt(workflow=workflow, audit=audit)
    repeated = build_evidence_receipt(workflow=workflow, audit=audit)
    serialized = receipt.model_dump_json()
    hash_payload = receipt.model_dump(mode="json", exclude={"receipt_hash"})
    canonical = json.dumps(
        hash_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    assert receipt.receipt_version == "evidence_receipt.v1"
    assert receipt.receipt_hash == hashlib.sha256(canonical).hexdigest()
    assert receipt == repeated
    assert [event.sequence for event in receipt.audit_events] == [1, 2]
    assert receipt.compiled_probe is not None
    assert receipt.compiled_probe.proof.domain_problem_count == 625
    assert receipt.compiled_probe.proof.top_candidates[0].predictions == [-9, 5]
    assert [item.model_dump() for item in receipt.accepted_hypotheses] == [
        {"template_id": "add_subtrahend", "rank": 1, "truth_table_hash": "a" * 64},
        {"template_id": "absolute_difference", "rank": 2, "truth_table_hash": "b" * 64},
    ]
    for forbidden in (
        "FORBIDDEN-OBSERVED-WORK-REF-55d1",
        "FORBIDDEN-GENERATED-HYPOTHESIS-PROSE-e031",
        "FORBIDDEN-GENERATED-HYPOTHESIS-PROSE-3cd2",
        "FORBIDDEN-LEARNER-RATIONALE-a21d",
        "FORBIDDEN-LEARNER-CAPABILITY-cc45",
        "FORBIDDEN-GENERATED-PROSE-7f3b",
        "FORBIDDEN-EDITED-PROSE-916c",
        "FORBIDDEN-TEACHER-NOTE-40da",
        "FORBIDDEN-PROVIDER-METADATA-62af",
        "FORBIDDEN-PROVIDER-REQUEST-b1d3",
    ):
        assert forbidden not in serialized
