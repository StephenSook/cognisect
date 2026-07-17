import type { components } from "@/lib/api/schema";

export const learnerProbe: components["schemas"]["LearnerProbeResponse"] = {
  problem: { a: -2, b: -7 },
  answer_constraints: { minimum: -10_000, maximum: 10_000 },
  expires_at: "2026-07-17T12:00:00Z",
  instructions: "Submit one signed integer.",
};

export function workflowFixture(
  state = "PROBE_READY",
): components["schemas"]["WorkflowResponse"] {
  return {
    workflow_id: "00000000-0000-4000-8000-000000000001",
    case_id: "00000000-0000-4000-8000-000000000002",
    source_tier: "educator_authored",
    provenance_record_id: "cognisect-ea-001",
    state,
    schema_version: "workflow.v1",
    registry_version: "rule_registry.v1",
    prompt_version: "analysis_prompt.v2",
    compiler_version: "counterexample_compiler.v1",
    model_snapshot: "gpt-5.6-terra-2026-07-16",
    model_request_id: "req_public_metadata",
    learner_response_url: null,
    created_at: "2026-07-16T10:00:00Z",
    updated_at: "2026-07-16T10:01:00Z",
    version: 2,
    accepted_hypotheses: [
      {
        template_id: "add_subtrahend",
        evidence_refs: ["segment-1"],
        description: "Adds the written second operand.",
        rank: 1,
        truth_table_hash: "a".repeat(64),
      },
      {
        template_id: "absolute_difference",
        evidence_refs: ["segment-2"],
        description: "Uses a non-negative magnitude difference.",
        rank: 2,
        truth_table_hash: "b".repeat(64),
      },
    ],
    compiled_probe: {
      original_problem: { a: -3, b: 5 },
      problem: { a: -2, b: -7 },
      correct_prediction: 5,
      specification_hash: "c".repeat(64),
      registry_version: "rule_registry.v1",
      compiler_version: "counterexample_compiler.v1",
      predictions: [
        { template_id: "add_subtrahend", rank: 1, prediction: -9 },
        { template_id: "absolute_difference", rank: 2, prediction: 5 },
      ],
      proof: {
        domain_problem_count: 625,
        eligible_candidate_count: 624,
        separating_candidate_count: 612,
        chosen_candidate_rank: 1,
        top_candidates: [
          {
            problem: { a: -2, b: -7 },
            predictions: [-9, 5],
            distinct_output_count: 2,
            top_two_separated: true,
            distinguished_pair_count: 1,
            operand_magnitude: 9,
            correct_result_magnitude: 5,
            rank: 1,
          },
        ],
      },
    },
    deterministic_evidence: [],
    learner_rationale: null,
    review_result: null,
    generated_proposal: "Review the deterministic evidence after the response.",
    edited_text: null,
  };
}
