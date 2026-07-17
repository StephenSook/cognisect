import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidenceTopology } from "@/components/evidence-topology";

describe("evidence topology", () => {
  it("pairs the visual trace with a semantic table containing the same evidence", () => {
    render(
      <EvidenceTopology
        label="Persisted compiler trace"
        statusLabel="Persisted · compiler v1"
        probeLabel="−2 − (−7)"
        teacherStage="Approved for release"
        learnerStage="Response recorded"
        updateStage="Supported / weakened"
        hypotheses={[
          { rank: 1, label: "Adds the written second operand", prediction: -9 },
          { rank: 2, label: "Uses a non-negative magnitude difference", prediction: 5 },
        ]}
      />,
    );

    expect(screen.getByRole("group", { name: "Persisted compiler trace" })).toBeInTheDocument();
    expect(screen.getByText("Persisted · compiler v1")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Persisted compiler trace table" });
    expect(within(table).getByText("Adds the written second operand")).toBeInTheDocument();
    expect(within(table).getByText("−9")).toBeInTheDocument();
    expect(within(table).getByText("−2 − (−7)")).toBeInTheDocument();
    expect(within(table).getByText("Teacher approval")).toBeInTheDocument();
    expect(within(table).getByText("Approved for release")).toBeInTheDocument();
    expect(within(table).getByText("Learner response")).toBeInTheDocument();
    expect(within(table).getByText("Response recorded")).toBeInTheDocument();
    expect(within(table).getByText("Evidence update")).toBeInTheDocument();
    expect(within(table).getByText("Supported / weakened")).toBeInTheDocument();
  });
});
