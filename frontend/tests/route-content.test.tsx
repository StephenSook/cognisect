import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReportView } from "@/components/report-view";
import { RuntimeEvidence } from "@/components/runtime-evidence";
import HomePage from "@/app/page";
import LabPage from "@/app/lab/page";
import { workflowFixture } from "./fixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

describe("live evidence tour route content", () => {
  it("leads with the deterministic 625-to-624 mechanism and a real lab route", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("heading", { name: /625 problems\.\s*One teacher-controlled probe\./ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/excludes the original problem to leave 624 eligible follow-ups/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Run the live evidence tour" })).toHaveAttribute(
      "href",
      "/lab",
    );
    expect(screen.getByRole("navigation", { name: "Live evidence tour" })).toBeInTheDocument();
  });

  it("identifies the default exemplar as real API input while preserving free entry", () => {
    render(<LabPage />);

    expect(screen.getByText(/default prefilled/i)).toHaveTextContent("cognisect-ea-001");
    expect(screen.getByText(/real API input with persisted provenance/i)).toBeInTheDocument();
    expect(screen.getByText(/not a mock or a demo bypass/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Case source")).toHaveValue("public_exemplar");
    expect(screen.getByLabelText("Public case")).toHaveValue("cognisect-ea-001");
  });
});

describe("teacher report content", () => {
  it.each([
    ["ANALYZING", "Constrained GPT mapping"],
    ["RESPONSE_RECORDED", "Exact evidence update"],
    ["AWAITING_REVIEW", "Second teacher gate"],
  ])("maps report state %s instead of assuming the second teacher gate", (state, stage) => {
    const workflow = workflowFixture(state);
    render(<ReportView workflow={workflow} audit={{ workflow_id: workflow.workflow_id, events: [] }} />);

    const tour = screen.getByRole("navigation", { name: "Live evidence tour" });
    expect(within(tour).getByText(stage)).toHaveAttribute("aria-current", "step");
  });

  it("renders persisted deterministic evidence, proposal, review, and audit readback", () => {
    const workflow = workflowFixture("AWAITING_REVIEW");
    workflow.deterministic_evidence = [
      { template_id: "add_subtrahend", rank: 1, status: "weakened" },
      { template_id: "absolute_difference", rank: 2, status: "supported" },
    ];
    workflow.learner_rationale = "I kept the second sign and counted left.";
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
    expect(screen.getByText("Review-only learner rationale").parentElement).toHaveTextContent(
      "I kept the second sign and counted left.",
    );
    const download = screen.getByRole("button", { name: "Download evidence receipt" });
    expect(download.closest("form")).toHaveAttribute(
      "action",
      `/api/backend/v1/workflows/${workflow.workflow_id}/receipt`,
    );
  });

  it("renders the persisted final teacher note and edit separately from deterministic evidence", () => {
    const workflow = workflowFixture("EDITED");
    workflow.learner_rationale = "I moved left from the first number.";
    workflow.review_result = {
      decision: "edited",
      note: "Persisted teacher note after review.",
      edited_text: "Persisted teacher-edited proposal.",
      created_at: "2026-07-16T12:00:00Z",
    };
    workflow.edited_text = "Persisted teacher-edited proposal.";

    render(<ReportView workflow={workflow} audit={{ workflow_id: workflow.workflow_id, events: [] }} />);

    const result = screen.getByRole("region", { name: "Persisted final teacher decision" });
    expect(result).toHaveTextContent("Persisted teacher note after review.");
    expect(result).toHaveTextContent("Persisted teacher-edited proposal.");
    expect(screen.getByText("Review-only learner rationale").parentElement).toHaveTextContent(
      "I moved left from the first number.",
    );
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
          source_revision: "a".repeat(40),
        }}
        workflow={workflow}
      />,
    );

    expect(screen.getByText("rule_registry.v1")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(40))).toBeInTheDocument();
    expect(screen.getByText("educator_authored")).toBeInTheDocument();
    expect(screen.getByText("resp_public_metadata")).toBeInTheDocument();
    expect(screen.getByText("req_public_metadata")).toBeInTheDocument();
    expect(screen.getByText(/No live-model status is claimed/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(privateMarker);
    expect(document.body).not.toHaveTextContent("correct_prediction");
  });
});
