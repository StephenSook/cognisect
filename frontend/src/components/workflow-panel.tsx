"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { components } from "@/lib/api/schema";
import { createBrowserApiClient } from "@/lib/api/browser-client";
import { EvidenceTopology } from "@/components/evidence-topology";
import { LearnerQr } from "@/components/learner-qr";
import { ProbeDecisionForm } from "@/components/probe-decision-form";

type Workflow = components["schemas"]["WorkflowResponse"];
type DecisionResult = components["schemas"]["LearnerTokenResponse"];
const TERMINAL_STATES = new Set(["APPROVED", "EDITED", "REJECTED", "ABSTAINED", "FAILED"]);

function topologyStages(workflow: Workflow) {
  const responseRecorded = workflow.deterministic_evidence.length > 0;
  const probeDeclined =
    workflow.state === "ABSTAINED" &&
    workflow.review_result === null &&
    !responseRecorded;
  const teacherStage = workflow.state === "PROBE_READY"
    ? "Awaiting teacher"
    : probeDeclined
      ? "Abstained"
      : "Approved for release";
  const learnerStage = responseRecorded
    ? "Response recorded"
    : workflow.state === "AWAITING_RESPONSE"
      ? "Awaiting response"
      : "Not released";
  const evidenceStatuses = [...new Set(workflow.deterministic_evidence.map((item) => item.status))];
  return {
    probeDeclined,
    teacherStage,
    learnerStage,
    updateStage: evidenceStatuses.length > 0
      ? evidenceStatuses.join(" / ")
      : probeDeclined
        ? "No update · abstained"
        : "Pending response",
  };
}

export function WorkflowPanel({ initialWorkflow }: { initialWorkflow: Workflow }) {
  const [workflow, setWorkflow] = useState(initialWorkflow);
  const [learnerLink, setLearnerLink] = useState<string | null>(
    initialWorkflow.learner_response_url,
  );
  const [copyStatus, setCopyStatus] = useState("");
  const [pollStatus, setPollStatus] = useState("");
  const stages = topologyStages(workflow);

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
          setLearnerLink(result.data.learner_response_url);
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
    <article className="workbench workflow-workbench">
      <header className="workbench-heading">
        <div>
          <p className="eyebrow eyebrow--ink">Teacher workbench</p>
          <h1>Case workflow</h1>
          <p>Review model-mapped alternatives before releasing compiled evidence.</p>
        </div>
        <span className="state-badge" data-state={workflow.state}>
          <span aria-hidden="true" /> {workflow.state.replaceAll("_", " ")}
        </span>
      </header>
      <dl className="metadata-strip">
        <div>
          <dt>Version</dt>
          <dd>{String(workflow.version).padStart(2, "0")}</dd>
        </div>
        <div>
          <dt>Source tier</dt>
          <dd>{workflow.source_tier.replaceAll("_", " ")}</dd>
        </div>
        <div>
          <dt>Registry</dt>
          <dd>{workflow.registry_version}</dd>
        </div>
        <div>
          <dt>Compiler</dt>
          <dd>{workflow.compiler_version}</dd>
        </div>
      </dl>

      <section className="workbench-card hypotheses-card" aria-labelledby="hypotheses-heading">
        <p className="card-index mono">MODEL OUTPUT / CONSTRAINED</p>
        <h2 id="hypotheses-heading">Accepted hypotheses</h2>
        <ol className="hypothesis-list">
          {workflow.accepted_hypotheses.map((hypothesis) => (
            <li key={hypothesis.rank}>
              <span className="hypothesis-rank mono">
                {String(hypothesis.rank).padStart(2, "0")}
              </span>
              <span>
                <strong>{hypothesis.description}</strong>
                <small>{hypothesis.template_id}</small>
              </span>
            </li>
          ))}
        </ol>
      </section>

      {workflow.compiled_probe === null ? null : (
        <section className="compiler-stage" aria-labelledby="probe-heading">
          <p className="card-index mono">DETERMINISTIC OUTPUT / PERSISTED</p>
          <h2 id="probe-heading">Compiled probe</h2>
          <p className="compiler-intro">
            The smallest ranked problem found in the bounded search where represented rules
            disagree.
          </p>
          <EvidenceTopology
            label="Persisted compiler trace"
            statusLabel={`${workflow.compiler_version} · verified`}
            probeLabel={`${workflow.compiled_probe.problem.a} − (${workflow.compiled_probe.problem.b})`}
            teacherStage={stages.teacherStage}
            learnerStage={stages.learnerStage}
            updateStage={stages.updateStage}
            hypotheses={workflow.accepted_hypotheses.map((hypothesis) => ({
              rank: hypothesis.rank,
              label: hypothesis.description,
              prediction:
                workflow.compiled_probe?.predictions.find(
                  (prediction) => prediction.rank === hypothesis.rank,
                )?.prediction ?? null,
            }))}
          />
          <div className="hash-readout">
            <span>Specification hash</span>
            <code>{workflow.compiled_probe.specification_hash}</code>
          </div>
        </section>
      )}

      {workflow.deterministic_evidence.length === 0 ? null : (
        <section className="workbench-card" aria-labelledby="evidence-heading">
          <p className="card-index mono">EXACT UPDATE / LEARNER RESPONSE</p>
          <h2 id="evidence-heading">Deterministic evidence</h2>
          <ul className="evidence-list">
            {workflow.deterministic_evidence.map((item) => (
              <li key={item.rank}>
                <span>Hypothesis {String(item.rank).padStart(2, "0")}</span>
                <strong data-evidence={item.status}>{item.status}</strong>
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
      {stages.probeDeclined ? (
        <p className="workflow-outcome" role="status">
          The teacher declined this probe. The workflow abstained and no learner link was created.
        </p>
      ) : null}
      {learnerLink === null ? null : (
        <section className="workbench-card learner-link-card" aria-labelledby="learner-link-heading">
          <p className="card-index mono">OPAQUE CAPABILITY / 24H</p>
          <h2 id="learner-link-heading">Learner link</h2>
          <p>Copy this one-time transport into a separate learner browser.</p>
          <label htmlFor="learner-link">Learner response link</label>
          <input className="mono" id="learner-link" value={learnerLink} readOnly />
          <button type="button" onClick={() => void copyLearnerLink()}>
            Copy learner link
          </button>
          <p role="status" aria-live="polite">
            {copyStatus}
          </p>
          <LearnerQr key={learnerLink} learnerLink={learnerLink} />
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
