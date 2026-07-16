"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { components } from "@/lib/api/schema";
import { createBrowserApiClient } from "@/lib/api/browser-client";
import { ProbeDecisionForm } from "@/components/probe-decision-form";

type Workflow = components["schemas"]["WorkflowResponse"];
type DecisionResult = components["schemas"]["LearnerTokenResponse"];
const TERMINAL_STATES = new Set(["APPROVED", "EDITED", "REJECTED", "ABSTAINED", "FAILED"]);

export function WorkflowPanel({ initialWorkflow }: { initialWorkflow: Workflow }) {
  const [workflow, setWorkflow] = useState(initialWorkflow);
  const [learnerLink, setLearnerLink] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState("");
  const [pollStatus, setPollStatus] = useState("");

  useEffect(() => {
    if (TERMINAL_STATES.has(workflow.state)) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const result = await createBrowserApiClient().GET(
          "/v1/workflows/{workflow_id}",
          {
            params: { path: { workflow_id: workflow.workflow_id } },
            cache: "no-store",
          },
        );
        if (result.data === undefined) {
          setPollStatus("Workflow refresh is temporarily unavailable.");
        } else {
          setWorkflow(result.data);
          setPollStatus("");
        }
      } catch {
        setPollStatus("Workflow refresh is temporarily unavailable.");
      } finally {
        if (!cancelled) timer = window.setTimeout(() => void poll(), 2_000);
      }
    };
    timer = window.setTimeout(() => void poll(), 2_000);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [workflow.state, workflow.workflow_id]);

  function recordDecision(result: DecisionResult) {
    setWorkflow(result.workflow);
    if (result.response_url !== null) setLearnerLink(result.response_url);
  }

  async function copyLearnerLink() {
    if (learnerLink === null) return;
    if (navigator.clipboard === undefined) {
      setCopyStatus(
        "Clipboard copy is unavailable. Select the learner link and copy it manually.",
      );
      return;
    }
    try {
      await navigator.clipboard.writeText(learnerLink);
      setCopyStatus("Learner link copied.");
    } catch {
      setCopyStatus(
        "Clipboard copy is unavailable. Select the learner link and copy it manually.",
      );
    }
  }

  return (
    <article>
      <h1>Case workflow</h1>
      <dl>
        <dt>State</dt>
        <dd>{workflow.state}</dd>
        <dt>Version</dt>
        <dd>{workflow.version}</dd>
        <dt>Source tier</dt>
        <dd>{workflow.source_tier}</dd>
      </dl>

      <section aria-labelledby="hypotheses-heading">
        <h2 id="hypotheses-heading">Accepted hypotheses</h2>
        <ol>
          {workflow.accepted_hypotheses.map((hypothesis) => (
            <li key={hypothesis.rank}>
              Rank {hypothesis.rank}: {hypothesis.description} ({hypothesis.template_id})
            </li>
          ))}
        </ol>
      </section>

      {workflow.compiled_probe === null ? null : (
        <section aria-labelledby="probe-heading">
          <h2 id="probe-heading">Compiled probe</h2>
          <p>
            {workflow.compiled_probe.problem.a} − ({workflow.compiled_probe.problem.b})
          </p>
          <p>Specification hash: {workflow.compiled_probe.specification_hash}</p>
          <h3>Stored predictions</h3>
          <ul>
            {workflow.compiled_probe.predictions.map((prediction) => (
              <li key={prediction.rank}>
                Rank {prediction.rank}: {prediction.prediction}
              </li>
            ))}
          </ul>
        </section>
      )}

      {workflow.deterministic_evidence.length === 0 ? null : (
        <section aria-labelledby="evidence-heading">
          <h2 id="evidence-heading">Deterministic evidence</h2>
          <ul>
            {workflow.deterministic_evidence.map((item) => (
              <li key={item.rank}>
                Rank {item.rank}: {item.status}
              </li>
            ))}
          </ul>
        </section>
      )}

      {workflow.state === "PROBE_READY" ? (
        <ProbeDecisionForm
          workflowId={workflow.workflow_id}
          version={workflow.version}
          onDecision={recordDecision}
        />
      ) : null}
      {learnerLink === null ? null : (
        <section aria-labelledby="learner-link-heading">
          <h2 id="learner-link-heading">Learner link</h2>
          <label htmlFor="learner-link">Learner response link</label>
          <input id="learner-link" value={learnerLink} readOnly />
          <button type="button" onClick={() => void copyLearnerLink()}>
            Copy learner link
          </button>
          <p role="status" aria-live="polite">
            {copyStatus}
          </p>
        </section>
      )}
      {workflow.state === "AWAITING_REVIEW" ? (
        <p>
          <Link href={`/report/${workflow.workflow_id}`}>Open teacher report</Link>
        </p>
      ) : null}
      <p role="status" aria-live="polite">
        {pollStatus}
      </p>
    </article>
  );
}
