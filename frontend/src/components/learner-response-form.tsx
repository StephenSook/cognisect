"use client";

import { useRef, useState } from "react";

import type { components } from "@/lib/api/schema";
import { createBrowserApiClient } from "@/lib/api/browser-client";
import { mutationKey } from "@/lib/idempotency";
import { strictInteger } from "@/lib/validation";

type LearnerProbe = components["schemas"]["LearnerProbeResponse"];
type LearnerReceipt = components["schemas"]["LearnerReceiptResponse"];

export function LearnerResponseForm({ token, probe }: { token: string; probe: LearnerProbe }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<LearnerReceipt | null>(null);
  const submitKey = useRef<string | null>(null);

  async function submit(formData: FormData) {
    const answer = strictInteger(
      String(formData.get("answer") ?? ""),
      probe.answer_constraints.minimum,
      probe.answer_constraints.maximum,
    );
    if (answer === null) {
      setError("Enter one whole signed integer within the stated range.");
      return;
    }
    const rationale = String(formData.get("rationale") ?? "").trim();
    setPending(true);
    setError(null);
    try {
      const result = await createBrowserApiClient().POST("/v1/respond/{token}", {
        params: {
          path: { token },
          header: { "Idempotency-Key": mutationKey(submitKey) },
        },
        body: { answer, rationale: rationale || null },
      });
      if (result.data !== undefined) {
        setReceipt(result.data);
      } else if (result.response.status === 410) {
        setError("This learner link has expired.");
      } else if (result.response.status === 409) {
        setError("A response has already been recorded for this learner link.");
      } else if (result.response.status === 404) {
        setError("This learner link is invalid.");
      } else {
        setError("The response was not accepted. Check the answer and retry.");
      }
    } catch {
      setError("The response service is unavailable. You can retry safely.");
    } finally {
      setPending(false);
    }
  }

  if (receipt !== null) {
    return (
      <section aria-live="polite">
        <h1>Response received</h1>
        <p>Receipt: {receipt.receipt_id}</p>
        <p>Accepted at: {receipt.accepted_at}</p>
      </section>
    );
  }

  return (
    <section>
      <h1>Learner response</h1>
      <p>
        Solve: {probe.problem.a} − ({probe.problem.b})
      </p>
      <p>{probe.instructions}</p>
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void submit(new FormData(event.currentTarget));
        }}
      >
        <label htmlFor="learner-answer">Your signed integer</label>
        <input id="learner-answer" name="answer" inputMode="numeric" required />
        <label htmlFor="learner-rationale">Rationale (optional)</label>
        <textarea id="learner-rationale" name="rationale" rows={4} />
        {error === null ? null : <p role="alert">{error}</p>}
        <p aria-live="polite">{pending ? "Submitting response…" : ""}</p>
        <button type="submit" disabled={pending}>
          Submit response
        </button>
      </form>
    </section>
  );
}
