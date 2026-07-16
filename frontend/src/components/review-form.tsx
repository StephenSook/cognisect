"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { components } from "@/lib/api/schema";
import { createBrowserApiClient } from "@/lib/api/browser-client";
import { mutationKey } from "@/lib/idempotency";

type Decision = components["schemas"]["ReviewRequest"]["decision"];

export function ReviewForm({
  workflowId,
  version,
  generatedProposal,
}: {
  workflowId: string;
  version: number;
  generatedProposal: string | null;
}) {
  const router = useRouter();
  const [decision, setDecision] = useState<Decision>("approved");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const reviewKey = useRef<string | null>(null);

  async function submit(formData: FormData) {
    const note = String(formData.get("note") ?? "").trim();
    const editedText = String(formData.get("edited_text") ?? "").trim();
    if ((decision === "approved" || decision === "edited") && !note) {
      setMessage("A teacher note is required for approval or editing.");
      return;
    }
    if (decision === "edited" && !editedText) {
      setMessage("Edited proposal text is required for an edited decision.");
      return;
    }
    setPending(true);
    setMessage(null);
    try {
      const result = await createBrowserApiClient().POST(
        "/v1/workflows/{workflow_id}/review",
        {
          params: {
            path: { workflow_id: workflowId },
            header: { "Idempotency-Key": mutationKey(reviewKey) },
          },
          body: {
            expected_version: version,
            decision,
            note: note || null,
            edited_text: decision === "edited" ? editedText : null,
          },
        },
      );
      if (result.data === undefined) {
        setMessage("The review was not accepted. Refresh before retrying.");
      } else {
        setMessage(`Review saved with final state ${result.data.state}.`);
        router.refresh();
      }
    } catch {
      setMessage("The review service is unavailable. You can retry safely.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-labelledby="review-heading">
      <h2 id="review-heading">Teacher review</h2>
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void submit(new FormData(event.currentTarget));
        }}
      >
        <label htmlFor="review-decision">Decision</label>
        <select
          id="review-decision"
          name="decision"
          value={decision}
          onChange={(event) => setDecision(event.target.value as Decision)}
        >
          <option value="approved">Approve</option>
          <option value="edited">Approve with edit</option>
          <option value="rejected">Reject</option>
          <option value="abstained">Abstain</option>
        </select>
        <label htmlFor="teacher-note">Teacher note</label>
        <textarea id="teacher-note" name="note" rows={4} />
        {decision === "edited" ? (
          <>
            <label htmlFor="edited-proposal">Edited proposal</label>
            <textarea
              id="edited-proposal"
              name="edited_text"
              rows={6}
              defaultValue={generatedProposal ?? ""}
            />
          </>
        ) : null}
        <p aria-live="polite" role={message?.includes("required") ? "alert" : undefined}>
          {message ?? (pending ? "Saving review…" : "")}
        </p>
        <button type="submit" disabled={pending}>
          Save review
        </button>
      </form>
    </section>
  );
}
