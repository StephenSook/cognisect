import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CompilerProofLens } from "@/components/compiler-proof-lens";
import { CounterfactualPreview } from "@/components/counterfactual-preview";
import { JudgeTour } from "@/components/judge-tour";
import { workflowFixture } from "./fixtures";

describe("compiler proof lens", () => {
  it("renders the persisted 625-to-1 sequence without recomputing the proof", () => {
    const workflow = workflowFixture();
    const compiledProbe = workflow.compiled_probe!;
    compiledProbe.proof.separating_candidate_count = 417;

    render(
      <CompilerProofLens
        compiledProbe={compiledProbe}
        hypotheses={workflow.accepted_hypotheses}
      />,
    );

    const sequence = screen.getByRole("list", { name: "Persisted compiler proof sequence" });
    expect(within(sequence).getAllByTestId("proof-value").map((node) => node.textContent)).toEqual([
      "625",
      "624",
      "417",
      "Rank 1",
    ]);
    expect(within(sequence).getByText("−3 − (5)", { exact: true })).toBeInTheDocument();
    expect(within(sequence).getByText(/excluded as the original problem/i)).toBeInTheDocument();
    expect(
      within(screen.getByTestId("chosen-probe-reveal")).getByText("−2 − (−7)", {
        exact: true,
      }),
    ).toBeInTheDocument();
  });

  it("exposes every persisted finalist metric and aligned prediction in a collapsed table", () => {
    const workflow = workflowFixture();
    const compiledProbe = workflow.compiled_probe!;
    compiledProbe.proof.top_candidates.push({
      problem: { a: 0, b: -6 },
      predictions: [-6, 6],
      distinct_output_count: 2,
      top_two_separated: true,
      distinguished_pair_count: 1,
      operand_magnitude: 6,
      correct_result_magnitude: 6,
      rank: 2,
    });

    render(
      <CompilerProofLens
        compiledProbe={compiledProbe}
        hypotheses={workflow.accepted_hypotheses}
      />,
    );

    const disclosure = screen.getByText("Inspect persisted finalists").closest("details");
    expect(disclosure).not.toHaveAttribute("open");
    const table = screen.getByRole("table", { hidden: true, name: "Persisted compiler finalists" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    const chosen = within(table).getByText("Chosen", { exact: true }).closest("tr");
    expect(chosen).toHaveAttribute("data-chosen", "true");
    expect(chosen).toHaveTextContent("H1: −9");
    expect(chosen).toHaveTextContent("H2: 5");
    expect(chosen).toHaveTextContent("2");
    expect(chosen).toHaveTextContent("Yes");
    expect(chosen).toHaveTextContent("1");
    expect(chosen).toHaveTextContent("9");
    expect(chosen).toHaveTextContent("5");
  });
});

describe("counterfactual preview", () => {
  it("groups prediction collisions without dropping hypothesis ranks", () => {
    const workflow = workflowFixture();
    workflow.accepted_hypotheses.push({
      template_id: "third_rule",
      evidence_refs: ["segment-3"],
      description: "Applies a third represented procedure.",
      rank: 3,
      truth_table_hash: "d".repeat(64),
    });
    workflow.compiled_probe!.predictions.push({
      template_id: "third_rule",
      rank: 3,
      prediction: -9,
    });

    render(
      <CounterfactualPreview
        hypotheses={workflow.accepted_hypotheses}
        predictions={workflow.compiled_probe!.predictions}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Counterfactual preview, not observed evidence" }),
    ).toBeInTheDocument();
    const negativeBranch = screen.getByRole("listitem", { name: "If answer −9 were submitted" });
    expect(negativeBranch).toHaveTextContent("Hypotheses 1 and 3");
    expect(negativeBranch).toHaveTextContent(
      "matching represented procedures would be supported and nonmatching ones weakened",
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(document.body.textContent?.toLowerCase()).not.toMatch(
      /learner (believes|understands|intended|is likely)|confidence score/,
    );
  });
});

describe("judge tour", () => {
  it("marks persisted progress without rendering a bypass control", () => {
    render(<JudgeTour currentStage="teacher-gate-one" />);

    expect(screen.getByRole("navigation", { name: "Live evidence tour" })).toBeInTheDocument();
    expect(screen.getByText("First teacher gate")).toHaveAttribute("aria-current", "step");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.getAllByRole("listitem")).toHaveLength(8);
  });
});
