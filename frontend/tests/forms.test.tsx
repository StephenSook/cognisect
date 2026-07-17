import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LabForm } from "@/components/lab-form";
import { LearnerResponseForm } from "@/components/learner-response-form";
import { ProbeDecisionForm } from "@/components/probe-decision-form";
import { ReviewForm } from "@/components/review-form";
import { WorkflowPanel } from "@/components/workflow-panel";
import { learnerProbe, workflowFixture } from "./fixtures";

const navigation = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
}));

describe("lab form", () => {
  beforeEach(() => {
    navigation.push.mockReset();
    navigation.refresh.mockReset();
  });

  afterEach(() => vi.unstubAllGlobals());

  it("requires visible de-identification attestation for a custom case", async () => {
    const fetchImplementation = vi.fn();
    vi.stubGlobal("fetch", fetchImplementation);
    render(<LabForm />);
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText("Case source"), "custom");
    await user.type(screen.getByLabelText("First integer"), "-3");
    await user.type(screen.getByLabelText("Second integer"), "5");
    await user.type(screen.getByLabelText("Observed work"), "-3 - 5 = 2");
    await user.click(screen.getByRole("button", { name: "Create and analyze" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Confirm that custom content");
    expect(fetchImplementation).not.toHaveBeenCalled();
  });

  it("offers a provenance-backed public exemplar and safe free-entry tiers", async () => {
    render(<LabForm />);
    const user = userEvent.setup();
    expect(
      screen.getAllByRole("option").map((option) => (option as HTMLOptionElement).value),
    ).toEqual(["public_exemplar", "educator_authored", "custom"]);

    await user.selectOptions(screen.getByLabelText("Case source"), "public_exemplar");
    expect(screen.getByLabelText("First integer")).toHaveValue("-3");
    expect(screen.getByLabelText("Second integer")).toHaveValue("5");
    expect(screen.getByLabelText("Observed work")).toHaveValue("-3 - 5 = 2");
    expect(screen.getByText(/cognisect-ea-001/i)).toBeInTheDocument();
  });

  it("preserves a cryptographically random idempotency key for exact retry", async () => {
    const fetchImplementation = vi.fn().mockRejectedValue(new Error("network unavailable"));
    vi.stubGlobal("fetch", fetchImplementation);
    render(<LabForm />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("First integer"), "-3");
    await user.type(screen.getByLabelText("Second integer"), "5");
    await user.type(screen.getByLabelText("Observed work"), "-3 - 5 = 2");
    await user.click(screen.getByRole("button", { name: "Create and analyze" }));
    await screen.findByText("The request could not reach the service. You can retry safely.");
    expect(screen.getByLabelText("Observed work")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Retry exact command" }));
    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(2));

    const requests = fetchImplementation.mock.calls.map(([request]) => request as Request);
    const keys = requests.map((request) => request.headers.get("idempotency-key"));
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(keys[1]).toBe(keys[0]);
    expect(await requests[1]!.clone().text()).toBe(await requests[0]!.clone().text());
  });

  it("associates the observed-work API limit with its field before dispatch", async () => {
    const fetchImplementation = vi.fn();
    vi.stubGlobal("fetch", fetchImplementation);
    render(<LabForm />);
    fireEvent.change(screen.getByLabelText("First integer"), { target: { value: "-3" } });
    fireEvent.change(screen.getByLabelText("Second integer"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Observed work"), {
      target: { value: "x".repeat(10_001) },
    });

    fireEvent.click(screen.getByRole("button", { name: "Create and analyze" }));

    expect(screen.getByText(/Observed work must be 10,000 characters or fewer/)).toHaveAttribute(
      "id",
      "observed-work-error",
    );
    expect(screen.getByLabelText("Observed work")).toHaveAttribute(
      "aria-describedby",
      "observed-work-error",
    );
    expect(fetchImplementation).not.toHaveBeenCalled();
  });

  it("retries only analysis after case creation has already succeeded", async () => {
    const created = {
      case_id: "00000000-0000-4000-8000-000000000010",
      workflow_id: "00000000-0000-4000-8000-000000000011",
    };
    const fetchImplementation = vi
      .fn()
      .mockResolvedValueOnce(Response.json(created, { status: 201 }))
      .mockRejectedValueOnce(new Error("analysis network failure"))
      .mockResolvedValueOnce(Response.json(workflowFixture()));
    vi.stubGlobal("fetch", fetchImplementation);
    render(<LabForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("First integer"), "-3");
    await user.type(screen.getByLabelText("Second integer"), "5");
    await user.type(screen.getByLabelText("Observed work"), "-3 - 5 = 2");

    await user.click(screen.getByRole("button", { name: "Create and analyze" }));
    await screen.findByText("The request could not reach the service. You can retry safely.");
    expect(screen.getByLabelText("Observed work")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Retry exact command" }));
    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(3));

    const requests = fetchImplementation.mock.calls.map(([request]) => request as Request);
    expect(requests.map((request) => new URL(request.url).pathname)).toEqual([
      "/api/backend/v1/cases",
      `/api/backend/v1/cases/${created.case_id}/analysis`,
      `/api/backend/v1/cases/${created.case_id}/analysis`,
    ]);
    expect(requests[2]?.headers.get("idempotency-key")).toBe(
      requests[1]?.headers.get("idempotency-key"),
    );
    expect(navigation.push).toHaveBeenCalledWith(
      `/case/${workflowFixture().workflow_id}`,
    );
  });
});

describe("learner response form", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("accepts only one strict signed integer before dispatch", async () => {
    const fetchImplementation = vi.fn();
    vi.stubGlobal("fetch", fetchImplementation);
    render(<LearnerResponseForm token="learner-token" probe={learnerProbe} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Your signed integer"), "1.5");
    await user.click(screen.getByRole("button", { name: "Submit response" }));

    expect(screen.getByRole("alert")).toHaveTextContent("whole signed integer");
    expect(fetchImplementation).not.toHaveBeenCalled();
  });

  it.each([
    [410, "This learner link has expired."],
    [409, "A response has already been recorded for this learner link."],
    [404, "This learner link is invalid."],
  ])("shows an honest learner state for HTTP %s", async (status, message) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ detail: "safe" }, { status })),
    );
    render(<LearnerResponseForm token="learner-token" probe={learnerProbe} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Your signed integer"), "5");
    await user.click(screen.getByRole("button", { name: "Submit response" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("renders only the minimal learner problem and receipt", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          receipt_id: "00000000-0000-4000-8000-000000000099",
          accepted_at: "2026-07-16T12:00:00Z",
        }),
      ),
    );
    const { container } = render(
      <LearnerResponseForm token="learner-token" probe={learnerProbe} />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your signed integer"), "5");
    await user.click(screen.getByRole("button", { name: "Submit response" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Response received" }),
    ).toBeInTheDocument();
    const text = container.textContent ?? "";
    for (const forbidden of ["hypothesis", "correct answer", "teacher", "model request"]) {
      expect(text.toLowerCase()).not.toContain(forbidden);
    }
  });

  it("reuses the learner submission key after a network failure", async () => {
    const fetchImplementation = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetchImplementation);
    render(<LearnerResponseForm token="learner-token" probe={learnerProbe} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your signed integer"), "5");

    await user.click(screen.getByRole("button", { name: "Submit response" }));
    await screen.findByText("The response service is unavailable. You can retry safely.");
    expect(screen.getByLabelText("Your signed integer")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Retry exact response" }));
    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(2));

    const requests = fetchImplementation.mock.calls.map(([request]) => request as Request);
    expect(requests[1]?.headers.get("idempotency-key")).toBe(
      requests[0]?.headers.get("idempotency-key"),
    );
    expect(await requests[1]!.clone().text()).toBe(await requests[0]!.clone().text());
  });

  it("rejects an oversized rationale at its field without dispatch", async () => {
    const fetchImplementation = vi.fn();
    vi.stubGlobal("fetch", fetchImplementation);
    render(<LearnerResponseForm token="learner-token" probe={learnerProbe} />);
    fireEvent.change(screen.getByLabelText("Your signed integer"), {
      target: { value: "5" },
    });
    fireEvent.change(screen.getByLabelText("Rationale (optional)"), {
      target: { value: "r".repeat(1_001) },
    });

    fireEvent.click(screen.getByRole("button", { name: "Submit response" }));

    expect(screen.getByText(/Rationale must be 1,000 characters or fewer/)).toHaveAttribute(
      "id",
      "learner-rationale-error",
    );
    expect(fetchImplementation).not.toHaveBeenCalled();
  });
});

describe("teacher decisions", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each(["approved", "edited", "rejected", "abstained"] as const)(
    "submits the %s terminal review decision",
    async (decision) => {
      const fetchImplementation = vi
        .fn<(request: Request) => Promise<Response>>()
        .mockResolvedValue(Response.json(workflowFixture(decision)));
      vi.stubGlobal("fetch", fetchImplementation);
      render(
        <ReviewForm
          workflowId="00000000-0000-4000-8000-000000000001"
          version={7}
          generatedProposal="Generated proposal"
        />,
      );
      const user = userEvent.setup();
      await user.selectOptions(screen.getByLabelText("Decision"), decision);
      if (decision === "approved" || decision === "edited") {
        await user.type(screen.getByLabelText("Teacher note"), "Teacher-reviewed note");
      }
      if (decision === "edited") {
        await user.type(screen.getByLabelText("Edited proposal"), "Teacher edit");
      }
      await user.click(screen.getByRole("button", { name: "Save review" }));
      await waitFor(() => expect(fetchImplementation).toHaveBeenCalledOnce());
      const body = await (fetchImplementation.mock.calls[0]?.[0] as Request).json();
      expect(body.decision).toBe(decision);
    },
  );

  it("submits teacher probe abstention without creating a learner link", async () => {
    const terminal = workflowFixture("ABSTAINED");
    const fetchImplementation = vi
      .fn<(request: Request) => Promise<Response>>()
      .mockResolvedValue(
        Response.json({ response_url: null, expires_at: null, workflow: terminal }),
      );
    vi.stubGlobal("fetch", fetchImplementation);
    render(
      <ProbeDecisionForm
        workflowId="00000000-0000-4000-8000-000000000001"
        version={2}
      />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Decline probe" }));

    expect(await screen.findByText("Probe declined. The workflow abstained.")).toBeInTheDocument();
    const body = await (fetchImplementation.mock.calls[0]?.[0] as Request).json();
    expect(body.approved).toBe(false);
  });

  it("reuses stable keys when probe and review commands are retried", async () => {
    const probeFetch = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", probeFetch);
    const probe = render(
      <ProbeDecisionForm
        workflowId="00000000-0000-4000-8000-000000000001"
        version={2}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Approve probe" }));
    await screen.findByText("The decision service is unavailable. You can retry safely.");
    await user.click(screen.getByRole("button", { name: "Approve probe" }));
    await waitFor(() => expect(probeFetch).toHaveBeenCalledTimes(2));
    const probeRequests = probeFetch.mock.calls.map(([request]) => request as Request);
    expect(probeRequests[1]?.headers.get("idempotency-key")).toBe(
      probeRequests[0]?.headers.get("idempotency-key"),
    );
    probe.unmount();

    const reviewFetch = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", reviewFetch);
    render(
      <ReviewForm
        workflowId="00000000-0000-4000-8000-000000000001"
        version={7}
        generatedProposal="Generated proposal"
      />,
    );
    await user.type(screen.getByLabelText("Teacher note"), "Teacher-reviewed note");
    await user.click(screen.getByRole("button", { name: "Save review" }));
    await screen.findByText("The review service is unavailable. You can retry safely.");
    expect(screen.getByLabelText("Teacher note")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Retry exact review" }));
    await waitFor(() => expect(reviewFetch).toHaveBeenCalledTimes(2));
    const reviewRequests = reviewFetch.mock.calls.map(([request]) => request as Request);
    expect(reviewRequests[1]?.headers.get("idempotency-key")).toBe(
      reviewRequests[0]?.headers.get("idempotency-key"),
    );
    expect(await reviewRequests[1]!.clone().text()).toBe(
      await reviewRequests[0]!.clone().text(),
    );
  });

  it("associates teacher-note and edited-text limits before dispatch", async () => {
    const fetchImplementation = vi.fn();
    vi.stubGlobal("fetch", fetchImplementation);
    render(
      <ReviewForm
        workflowId="00000000-0000-4000-8000-000000000001"
        version={7}
        generatedProposal="Generated proposal"
      />,
    );
    fireEvent.change(screen.getByLabelText("Teacher note"), {
      target: { value: "n".repeat(4_001) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save review" }));
    expect(screen.getByText(/Teacher note must be 4,000 characters or fewer/)).toHaveAttribute(
      "id",
      "teacher-note-error",
    );
    expect(fetchImplementation).not.toHaveBeenCalled();

    await userEvent.setup().selectOptions(screen.getByLabelText("Decision"), "edited");
    fireEvent.change(screen.getByLabelText("Teacher note"), { target: { value: "note" } });
    fireEvent.change(screen.getByLabelText("Edited proposal"), {
      target: { value: "e".repeat(8_001) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save review" }));
    expect(screen.getByText(/Edited proposal must be 8,000 characters or fewer/)).toHaveAttribute(
      "id",
      "edited-proposal-error",
    );
    expect(fetchImplementation).not.toHaveBeenCalled();
  });
});

describe("workflow polling", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
  });

  it("polls only while the workflow is nonterminal", async () => {
    vi.useFakeTimers();
    const fetchImplementation = vi.fn(async () => Response.json(workflowFixture("PROBE_READY")));
    vi.stubGlobal("fetch", fetchImplementation);
    const { unmount } = render(<WorkflowPanel initialWorkflow={workflowFixture("APPROVED")} />);

    await vi.advanceTimersByTimeAsync(4_000);
    expect(fetchImplementation).not.toHaveBeenCalled();

    unmount();
    render(<WorkflowPanel initialWorkflow={workflowFixture("PROBE_READY")} />);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetchImplementation).toHaveBeenCalledOnce();
  });

  it("keeps the approved learner link available and provides copy success", async () => {
    const responseUrl = "http://localhost:3000/respond/raw-learner-token";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          response_url: responseUrl,
          expires_at: "2026-07-17T12:00:00Z",
          workflow: workflowFixture("AWAITING_RESPONSE"),
        }),
      ),
    );
    const writeText = vi.fn(async () => undefined);
    render(<WorkflowPanel initialWorkflow={workflowFixture("PROBE_READY")} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Approve probe" }));
    const link = await screen.findByRole("textbox", { name: "Learner response link" });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    expect(link).toHaveValue(responseUrl);
    fireEvent.click(screen.getByRole("button", { name: "Copy learner link" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(responseUrl));
    expect(await screen.findByText("Learner link copied.")).toBeInTheDocument();
  });

  it("recovers an active owner-only learner link on reload", () => {
    const workflow = workflowFixture("AWAITING_RESPONSE") as ReturnType<
      typeof workflowFixture
    > & { learner_response_url: string | null };
    workflow.learner_response_url = "http://localhost:3000/respond/recovered-token";

    render(<WorkflowPanel initialWorkflow={workflow} />);

    expect(screen.getByRole("textbox", { name: "Learner response link" })).toHaveValue(
      workflow.learner_response_url,
    );
  });

  it("distinguishes probe-decline abstention from final-review abstention", () => {
    const declinedProbe = workflowFixture("ABSTAINED");
    const declined = render(<WorkflowPanel initialWorkflow={declinedProbe} />);
    expect(
      screen.getByText(
        "The teacher declined this probe. The workflow abstained and no learner link was created.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Persisted compiler trace table" })).toHaveTextContent(
      "Teacher approvalHuman release gateAbstained",
    );
    expect(screen.getByRole("table", { name: "Persisted compiler trace table" })).toHaveTextContent(
      "Evidence updateExact prediction matchingNo update · abstained",
    );
    declined.unmount();

    const finalReview = workflowFixture("ABSTAINED");
    finalReview.deterministic_evidence = [
      { template_id: "add_subtrahend", rank: 1, status: "weakened" },
      { template_id: "absolute_difference", rank: 2, status: "supported" },
    ];
    finalReview.review_result = {
      decision: "abstained",
      note: "The represented rules do not resolve this case.",
      edited_text: null,
      created_at: "2026-07-16T12:00:00Z",
    };

    render(<WorkflowPanel initialWorkflow={finalReview} />);

    expect(
      screen.queryByText(
        "The teacher declined this probe. The workflow abstained and no learner link was created.",
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Persisted compiler trace table" })).toHaveTextContent(
      "Teacher approvalHuman release gateApproved for release",
    );
    expect(screen.getByRole("table", { name: "Persisted compiler trace table" })).toHaveTextContent(
      "Learner responseOne strict signed integerResponse recorded",
    );
  });

  it("shows a selectable-link fallback when clipboard copy is unavailable", async () => {
    const responseUrl = "http://localhost:3000/respond/raw-learner-token";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          response_url: responseUrl,
          expires_at: "2026-07-17T12:00:00Z",
          workflow: workflowFixture("AWAITING_RESPONSE"),
        }),
      ),
    );
    render(<WorkflowPanel initialWorkflow={workflowFixture("PROBE_READY")} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Approve probe" }));
    await screen.findByRole("textbox", { name: "Learner response link" });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
    fireEvent.click(screen.getByRole("button", { name: "Copy learner link" }));
    expect(screen.getByText(
      "Clipboard copy is unavailable. Select the learner link and copy it manually.",
    )).toBeInTheDocument();
  });

  it("never overlaps polls and reports a refresh failure", async () => {
    vi.useFakeTimers();
    let rejectRequest: ((reason?: unknown) => void) | undefined;
    const fetchImplementation = vi.fn(
      () =>
        new Promise<Response>((_resolve, reject) => {
          rejectRequest = reject;
        }),
    );
    vi.stubGlobal("fetch", fetchImplementation);
    render(<WorkflowPanel initialWorkflow={workflowFixture("PROBE_READY")} />);

    await vi.advanceTimersByTimeAsync(8_000);
    expect(fetchImplementation).toHaveBeenCalledOnce();
    await act(async () => {
      rejectRequest?.(new Error("backend unavailable"));
      await Promise.resolve();
    });
    expect(screen.getByText("Workflow refresh is temporarily unavailable.")).toBeInTheDocument();
  });
});
