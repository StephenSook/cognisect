"""Canonical construction of privacy-safe evidence receipts."""

from __future__ import annotations

import hashlib
import json

from cognisect.api_models import (
    AuditEventResponse,
    AuditResponse,
    EvidenceReceiptCandidateProof,
    EvidenceReceiptCompiledProbe,
    EvidenceReceiptCompilerProof,
    EvidenceReceiptHypothesis,
    EvidenceReceiptPayload,
    EvidenceReceiptPrediction,
    EvidenceReceiptResponse,
    EvidenceStatusResponse,
    SignedProblemDTO,
    WorkflowResponse,
)


def _problem(problem: SignedProblemDTO) -> SignedProblemDTO:
    return SignedProblemDTO(a=problem.a, b=problem.b)


def _compiled_probe(workflow: WorkflowResponse) -> EvidenceReceiptCompiledProbe | None:
    probe = workflow.compiled_probe
    if probe is None:
        return None
    return EvidenceReceiptCompiledProbe(
        original_problem=_problem(probe.original_problem),
        problem=_problem(probe.problem),
        correct_prediction=probe.correct_prediction,
        specification_hash=probe.specification_hash,
        registry_version=probe.registry_version,
        compiler_version=probe.compiler_version,
        predictions=[
            EvidenceReceiptPrediction(
                template_id=prediction.template_id,
                rank=prediction.rank,
                prediction=prediction.prediction,
            )
            for prediction in sorted(
                probe.predictions,
                key=lambda item: (item.rank, item.template_id),
            )
        ],
        proof=EvidenceReceiptCompilerProof(
            domain_problem_count=probe.proof.domain_problem_count,
            eligible_candidate_count=probe.proof.eligible_candidate_count,
            separating_candidate_count=probe.proof.separating_candidate_count,
            chosen_candidate_rank=probe.proof.chosen_candidate_rank,
            top_candidates=[
                EvidenceReceiptCandidateProof(
                    problem=_problem(candidate.problem),
                    predictions=list(candidate.predictions),
                    distinct_output_count=candidate.distinct_output_count,
                    top_two_separated=candidate.top_two_separated,
                    distinguished_pair_count=candidate.distinguished_pair_count,
                    operand_magnitude=candidate.operand_magnitude,
                    correct_result_magnitude=candidate.correct_result_magnitude,
                    rank=candidate.rank,
                )
                for candidate in sorted(
                    probe.proof.top_candidates,
                    key=lambda item: (
                        item.rank,
                        item.problem.a,
                        item.problem.b,
                    ),
                )
            ],
        ),
    )


def _canonical_json(payload: EvidenceReceiptPayload) -> bytes:
    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def build_evidence_receipt(
    *, workflow: WorkflowResponse, audit: AuditResponse
) -> EvidenceReceiptResponse:
    """Build and hash only the explicitly enumerated privacy-safe fields."""
    if audit.workflow_id != workflow.workflow_id:
        msg = "workflow and audit identifiers must match"
        raise ValueError(msg)
    payload = EvidenceReceiptPayload(
        workflow_id=workflow.workflow_id,
        case_id=workflow.case_id,
        source_tier=workflow.source_tier,
        provenance_record_id=workflow.provenance_record_id,
        state=workflow.state,
        schema_version=workflow.schema_version,
        registry_version=workflow.registry_version,
        prompt_version=workflow.prompt_version,
        compiler_version=workflow.compiler_version,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
        workflow_version=workflow.version,
        accepted_hypotheses=[
            EvidenceReceiptHypothesis(
                template_id=hypothesis.template_id,
                rank=hypothesis.rank,
                truth_table_hash=hypothesis.truth_table_hash,
            )
            for hypothesis in sorted(
                workflow.accepted_hypotheses,
                key=lambda item: (item.rank, item.template_id),
            )
        ],
        compiled_probe=_compiled_probe(workflow),
        deterministic_evidence=[
            EvidenceStatusResponse(
                template_id=evidence.template_id,
                rank=evidence.rank,
                status=evidence.status,
            )
            for evidence in sorted(
                workflow.deterministic_evidence,
                key=lambda item: (item.rank, item.template_id),
            )
        ],
        review_decision=(
            workflow.review_result.decision if workflow.review_result is not None else None
        ),
        reviewed_at=(
            workflow.review_result.created_at if workflow.review_result is not None else None
        ),
        audit_events=[
            AuditEventResponse(
                sequence=event.sequence,
                from_state=event.from_state,
                to_state=event.to_state,
                version=event.version,
                occurred_at=event.occurred_at,
            )
            for event in sorted(audit.events, key=lambda item: item.sequence)
        ],
    )
    return EvidenceReceiptResponse(
        **payload.model_dump(),
        receipt_hash=hashlib.sha256(_canonical_json(payload)).hexdigest(),
    )
