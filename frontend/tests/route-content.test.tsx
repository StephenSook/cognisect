import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReportView } from "@/components/report-view";
import { RuntimeEvidence } from "@/components/runtime-evidence";
import { workflowFixture } from "./fixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

describe("teacher report content", () => {
  it("renders persisted deterministic evidence, proposal, review, and audit readback", () => {
    const workflow = workflowFixture("AWAITING_REVIEW");
    workflow.deterministic_evidence = [
      { template_id: "add_subtrahend", rank: 1, status: "weakened" },
      { template_id: "absolute_difference", rank: 2, status: "supported" },
    ];
    render(
      <ReportView
        workflow={workflow}
        audit={{
          workflow_id: workflow.workflow_id,
          events: [
            {
              sequence: 1,
              from_state: "CREATED",
              to_state: "ANALYZING",
              version: 1,
              occurred_at: "2026-07-16T10:00:00Z",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("supported").closest("li")).toHaveTextContent(
      "Hypothesis 02supported",
    );
    expect(screen.getByText("Generated proposal").parentElement).toHaveTextContent(
      "Review the deterministic evidence after the response.",
    );
    expect(screen.getByRole("button", { name: "Save review" })).toBeInTheDocument();
    expect(screen.getByText(/CREATED → ANALYZING/)).toBeInTheDocument();
  });
});

describe("runtime evidence allowlist", () => {
  it("shows only proven version, route, source-tier, and model request metadata", () => {
    const workflow = workflowFixture("AWAITING_REVIEW");
    const privateMarker = "raw-learner-token-must-not-render";
    workflow.generated_proposal = privateMarker;
    workflow.edited_text = privateMarker;
    workflow.learner_response_url = `http://localhost:3000/respond/${privateMarker}`;
    workflow.accepted_hypotheses[0]!.description = privateMarker;
    render(
      <RuntimeEvidence
        version={{
          version: "0.1.0",
          schema_version: "workflow.v1",
          registry_version: "rule_registry.v1",
          compiler_version: "counterexample_compiler.v1",
        }}
        workflow={workflow}
      />,
    );

    expect(screen.getByText("rule_registry.v1")).toBeInTheDocument();
    expect(screen.getByText("educator_authored")).toBeInTheDocument();
    expect(screen.getByText("req_public_metadata")).toBeInTheDocument();
    expect(screen.getByText(/No live-model status is claimed/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(privateMarker);
    expect(document.body).not.toHaveTextContent("correct_prediction");
  });
});
