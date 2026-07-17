"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { components } from "@/lib/api/schema";
import { createBrowserApiClient } from "@/lib/api/browser-client";
import { mutationKey } from "@/lib/idempotency";

type Decision = components["schemas"]["ReviewRequest"]["decision"];
type ReviewCommand = components["schemas"]["ReviewRequest"];

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
  const [commandLocked, setCommandLocked] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [editedTextError, setEditedTextError] = useState<string | null>(null);
  const reviewKey = useRef<string | null>(null);
  const command = useRef<ReviewCommand | null>(null);

  async function submit(formData: FormData) {
    if (command.current === null) {
      const note = String(formData.get("note") ?? "").trim();
      const editedText = String(formData.get("edited_text") ?? "").trim();
      setNoteError(null);
      setEditedTextError(null);
      if ((decision === "approved" || decision === "edited") && !note) {
        setNoteError("A teacher note is required for approval or editing.");
        return;
      }
      if (note.length > 4_000) {
        setNoteError("Teacher note must be 4,000 characters or fewer.");
        return;
      }
      if (decision === "edited" && !editedText) {
        setEditedTextError("Edited proposal text is required for an edited decision.");
        return;
      }
      if (editedText.length > 8_000) {
        setEditedTextError("Edited proposal must be 8,000 characters or fewer.");
        return;
      }
      command.current = {
        expected_version: version,
        decision,
        note: note || null,
        edited_text: decision === "edited" ? editedText : null,
      };
      setCommandLocked(true);
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
          body: command.current,
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
    <section className="review-stage" aria-labelledby="review-heading">
      <p className="card-index mono">FINAL HUMAN DECISION</p>
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
          disabled={commandLocked}
          onChange={(event) => setDecision(event.target.value as Decision)}
        >
          <option value="approved">Approve</option>
          <option value="edited">Approve with edit</option>
          <option value="rejected">Reject</option>
          <option value="abstained">Abstain</option>
        </select>
        <label htmlFor="teacher-note">Teacher note</label>
        <textarea
          id="teacher-note"
          name="note"
          rows={4}
          maxLength={4_000}
          disabled={commandLocked}
          aria-describedby={noteError ? "teacher-note-error" : undefined}
        />
        {noteError ? <p id="teacher-note-error" role="alert">{noteError}</p> : null}
        {decision === "edited" ? (
          <>
            <label htmlFor="edited-proposal">Edited proposal</label>
            <textarea
              id="edited-proposal"
              name="edited_text"
              rows={6}
              maxLength={8_000}
              disabled={commandLocked}
              aria-describedby={editedTextError ? "edited-proposal-error" : undefined}
              defaultValue={generatedProposal ?? ""}
            />
            {editedTextError ? (
              <p id="edited-proposal-error" role="alert">{editedTextError}</p>
            ) : null}
          </>
        ) : null}
        <p aria-live="polite" role={message?.includes("required") ? "alert" : undefined}>
          {message ?? (pending ? "Saving review…" : "")}
        </p>
        {commandLocked ? (
          <p>The review fields are locked so every retry sends the exact same decision.</p>
        ) : null}
        <button className="primary-button" type="submit" disabled={pending}>
          {commandLocked ? "Retry exact review" : "Save review"}
        </button>
      </form>
    </section>
  );
}
