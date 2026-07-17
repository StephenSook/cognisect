import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LearnerQr } from "@/components/learner-qr";
import { learnerProbe } from "./fixtures";

const qr = vi.hoisted(() => ({
  toString: vi.fn(async () => "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>"),
}));

vi.mock("qrcode", () => ({ default: qr }));

describe("learner QR transport", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders a locally generated QR only after the learner GET smoke passes", async () => {
    const fetchImplementation = vi.fn(async (request: Request) => {
      void request;
      return Response.json(learnerProbe);
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(<LearnerQr learnerLink="http://localhost:3000/respond/opaque-token" />);

    expect(screen.queryByRole("img", { name: /QR code for the learner response link/i })).toBeNull();
    expect(await screen.findByText("QR transport ready.")).toBeInTheDocument();
    const image = screen.getByRole("img", { name: /QR code for the learner response link/i });
    expect(image).toHaveAttribute("src", expect.stringMatching(/^data:image\/svg\+xml/));
    expect(qr.toString).toHaveBeenCalledWith(
      "http://localhost:3000/respond/opaque-token",
      expect.objectContaining({ type: "svg", errorCorrectionLevel: "M" }),
    );
    const request = fetchImplementation.mock.calls[0]?.[0] as Request;
    expect(new URL(request.url).pathname).toBe("/api/backend/v1/respond/opaque-token");
  });

  it("hides the QR and preserves the text-link path when smoke fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ detail: "unavailable" }, { status: 410 })),
    );

    render(<LearnerQr learnerLink="http://localhost:3000/respond/expired-token" />);

    await waitFor(() => {
      expect(screen.getByText("QR unavailable. Copy the learner link instead.")).toBeInTheDocument();
    });
    expect(screen.queryByRole("img", { name: /QR code for the learner response link/i })).toBeNull();
  });
});
