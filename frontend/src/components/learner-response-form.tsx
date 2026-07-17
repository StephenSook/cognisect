"use client";

import { useRef, useState } from "react";

import type { components } from "@/lib/api/schema";
import { createBrowserApiClient } from "@/lib/api/browser-client";
import { mutationKey } from "@/lib/idempotency";
import { strictInteger } from "@/lib/validation";

type LearnerProbe = components["schemas"]["LearnerProbeResponse"];
type LearnerReceipt = components["schemas"]["LearnerReceiptResponse"];
type LearnerCommand = components["schemas"]["LearnerSubmitRequest"];

export function LearnerResponseForm({ token, probe }: { token: string; probe: LearnerProbe }) {
  const [pending, setPending] = useState(false);
  const [commandLocked, setCommandLocked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answerError, setAnswerError] = useState<string | null>(null);
  const [rationaleError, setRationaleError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<LearnerReceipt | null>(null);
  const submitKey = useRef<string | null>(null);
  const command = useRef<LearnerCommand | null>(null);

  async function submit(formData: FormData) {
    if (command.current === null) {
      const answer = strictInteger(
        String(formData.get("answer") ?? ""),
        probe.answer_constraints.minimum,
        probe.answer_constraints.maximum,
      );
      const rationale = String(formData.get("rationale") ?? "").trim();
      setAnswerError(null);
      setRationaleError(null);
      if (answer === null) {
        setAnswerError("Enter one whole signed integer within the stated range.");
        return;
      }
      if (rationale.length > 1_000) {
        setRationaleError("Rationale must be 1,000 characters or fewer.");
        return;
      }
      command.current = { answer, rationale: rationale || null };
      setCommandLocked(true);
    }
    setPending(true);
    setError(null);
    try {
      const result = await createBrowserApiClient().POST("/v1/respond/{token}", {
        params: {
          path: { token },
          header: { "Idempotency-Key": mutationKey(submitKey) },
        },
        body: command.current,
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
      <section className="learner-card learner-receipt" aria-live="polite">
        <span className="receipt-mark" aria-hidden="true">✓</span>
        <h1>Response received</h1>
        <p>Your signed-integer answer was recorded once.</p>
        <dl className="receipt-metadata mono">
          <div><dt>Receipt</dt><dd>{receipt.receipt_id}</dd></div>
          <div><dt>Accepted</dt><dd>{receipt.accepted_at}</dd></div>
        </dl>
      </section>
    );
  }

  return (
    <section className="learner-card">
      <p className="eyebrow eyebrow--ink">One separating probe</p>
      <h1>Learner response</h1>
      <p className="learner-instructions">{probe.instructions}</p>
      <p className="math-problem" aria-label={`Solve ${probe.problem.a} minus ${probe.problem.b}`}>
        <span className="math-label">Solve:</span>
        <span>{probe.problem.a}</span>
        <span aria-hidden="true">−</span>
        <span>({probe.problem.b})</span>
      </p>
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void submit(new FormData(event.currentTarget));
        }}
      >
        <label htmlFor="learner-answer">Your signed integer</label>
        <input
          id="learner-answer"
          name="answer"
          inputMode="numeric"
          required
          disabled={commandLocked}
          aria-describedby={answerError ? "learner-answer-error" : undefined}
        />
        {answerError ? <p id="learner-answer-error" role="alert">{answerError}</p> : null}
        <label htmlFor="learner-rationale">Rationale (optional)</label>
        <textarea
          id="learner-rationale"
          name="rationale"
          rows={4}
          maxLength={1_000}
          disabled={commandLocked}
          aria-describedby={rationaleError ? "learner-rationale-error" : undefined}
        />
        {rationaleError ? (
          <p id="learner-rationale-error" role="alert">{rationaleError}</p>
        ) : null}
        {error === null ? null : <p className="form-alert" role="alert">{error}</p>}
        {commandLocked ? (
          <p>The response fields are locked so every retry sends the exact same answer.</p>
        ) : null}
        <p aria-live="polite">{pending ? "Submitting response…" : ""}</p>
        <button className="primary-button" type="submit" disabled={pending}>
          {commandLocked ? "Retry exact response" : "Submit response"}
        </button>
      </form>
    </section>
  );
}
