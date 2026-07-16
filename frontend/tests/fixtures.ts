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
    state,
    schema_version: "workflow.v1",
    registry_version: "rule_registry.v1",
    prompt_version: "analysis_prompt.v2",
    compiler_version: "counterexample_compiler.v1",
    model_snapshot: "gpt-5.6-terra-2026-07-16",
    model_request_id: "req_public_metadata",
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
    },
    deterministic_evidence: [],
    review_result: null,
    generated_proposal: "Review the deterministic evidence after the response.",
    edited_text: null,
  };
}
