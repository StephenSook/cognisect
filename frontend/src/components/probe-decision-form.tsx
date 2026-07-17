"use client";

import { useRef, useState } from "react";

import type { components } from "@/lib/api/schema";
import { createBrowserApiClient } from "@/lib/api/browser-client";
import { mutationKey } from "@/lib/idempotency";

type DecisionResult = components["schemas"]["LearnerTokenResponse"];

export function ProbeDecisionForm({
  workflowId,
  version,
  onDecision,
}: {
  workflowId: string;
  version: number;
  onDecision?: (result: DecisionResult) => void;
}) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const approvalKey = useRef<string | null>(null);
  const declineKey = useRef<string | null>(null);

  async function decide(approved: boolean) {
    setPending(true);
    setMessage(null);
    const key = approved ? approvalKey : declineKey;
    try {
      const result = await createBrowserApiClient().POST(
        "/v1/workflows/{workflow_id}/probe-approval",
        {
          params: {
            path: { workflow_id: workflowId },
            header: { "Idempotency-Key": mutationKey(key) },
          },
          body: { expected_version: version, approved, expires_in_seconds: 86_400 },
        },
      );
      if (result.data === undefined) {
        setMessage("The decision was not accepted. Refresh the workflow before retrying.");
      } else {
        onDecision?.(result.data);
        setMessage(
          result.data.response_url === null
            ? "Probe declined. The workflow abstained."
            : "Probe approved. The learner link is ready below.",
        );
      }
    } catch {
      setMessage("The decision service is unavailable. You can retry safely.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="decision-stage" aria-labelledby="probe-decision-heading">
      <p className="card-index mono">TEACHER INTERRUPT / REQUIRED</p>
      <h2 id="probe-decision-heading">Teacher probe decision</h2>
      <p>Inspect the compiled disagreement before releasing the learner link.</p>
      <div className="decision-actions">
        <button className="primary-button" type="button" disabled={pending} onClick={() => void decide(true)}>
          Approve probe
        </button>
        <button className="secondary-button" type="button" disabled={pending} onClick={() => void decide(false)}>
          Decline probe
        </button>
      </div>
      <p aria-live="polite">{message}</p>
    </section>
  );
}
