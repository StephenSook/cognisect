"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import type { components } from "@/lib/api/schema";
import { createBrowserApiClient } from "@/lib/api/browser-client";
import { CompilerProofLens } from "@/components/compiler-proof-lens";
import { CounterfactualPreview } from "@/components/counterfactual-preview";
import { EvidenceTopology } from "@/components/evidence-topology";
import { JudgeTour } from "@/components/judge-tour";
import { LearnerQr } from "@/components/learner-qr";
import { ProbeDecisionForm } from "@/components/probe-decision-form";
import { workflowPresentation } from "@/lib/workflow-presentation";

type Workflow = components["schemas"]["WorkflowResponse"];
type DecisionResult = components["schemas"]["LearnerTokenResponse"];
const TERMINAL_STATES = new Set(["APPROVED", "EDITED", "REJECTED", "ABSTAINED", "FAILED"]);
const POLL_DELAYS = [2_000, 4_000, 8_000, 15_000] as const;

export function WorkflowPanel({ initialWorkflow }: { initialWorkflow: Workflow }) {
  const workflowId = initialWorkflow.workflow_id;
  const [workflow, setWorkflow] = useState(initialWorkflow);
  const workflowRef = useRef(initialWorkflow);
  const [learnerLink, setLearnerLink] = useState<string | null>(
    initialWorkflow.learner_response_url,
  );
  const [copyStatus, setCopyStatus] = useState("");
  const [pollStatus, setPollStatus] = useState("");
  const stages = workflowPresentation(workflow);

  const applyWorkflowSnapshot = useCallback(
    (nextWorkflow: Workflow, nextLearnerLink = nextWorkflow.learner_response_url) => {
      if (nextWorkflow.version < workflowRef.current.version) return false;
      workflowRef.current = nextWorkflow;
      setWorkflow(nextWorkflow);
      setLearnerLink(nextLearnerLink);
      return true;
    },
    [],
  );

  useEffect(() => {
    if (TERMINAL_STATES.has(workflowRef.current.state)) return;
    let cancelled = false;
    let timer: number | undefined;
    let controller: AbortController | undefined;
    let delayIndex = 0;

    const schedule = () => {
      timer = window.setTimeout(() => void poll(), POLL_DELAYS[delayIndex]);
    };

    const poll = async () => {
      if (TERMINAL_STATES.has(workflowRef.current.state)) return;
      controller = new AbortController();
      const previous = workflowRef.current;
      try {
        const result = await createBrowserApiClient().GET(
          "/v1/workflows/{workflow_id}",
          {
            params: { path: { workflow_id: workflowId } },
            cache: "no-store",
            signal: controller.signal,
          },
        );
        if (cancelled) return;
        if (result.data === undefined) {
          setPollStatus("Workflow refresh is temporarily unavailable.");
          delayIndex = Math.min(delayIndex + 1, POLL_DELAYS.length - 1);
        } else {
          const accepted = applyWorkflowSnapshot(result.data);
          const current = workflowRef.current;
          const changed =
            accepted &&
            (current.version !== previous.version || current.state !== previous.state);
          setPollStatus("");
          if (TERMINAL_STATES.has(current.state)) return;
          delayIndex = changed ? 0 : Math.min(delayIndex + 1, POLL_DELAYS.length - 1);
        }
      } catch {
        if (cancelled) return;
        setPollStatus("Workflow refresh is temporarily unavailable.");
        delayIndex = Math.min(delayIndex + 1, POLL_DELAYS.length - 1);
      } finally {
        if (!cancelled && !TERMINAL_STATES.has(workflowRef.current.state)) schedule();
      }
    };
    schedule();
    return () => {
      cancelled = true;
      controller?.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [applyWorkflowSnapshot, workflowId]);

  function recordDecision(result: DecisionResult) {
    return applyWorkflowSnapshot(result.workflow, result.response_url);
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

      <JudgeTour currentStage={stages.judgeStage} />

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
            Persisted compiler counts reveal how one deterministic probe emerged from the frozen
            domain.
          </p>
          <CompilerProofLens
            compiledProbe={workflow.compiled_probe}
            hypotheses={workflow.accepted_hypotheses}
            custodyGate={workflow.state === "PROBE_READY" ? (
              <ProbeDecisionForm
                workflowId={workflow.workflow_id}
                version={workflow.version}
                onDecision={recordDecision}
              />
            ) : undefined}
          />
          <div className="compiler-secondary">
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
            <CounterfactualPreview
              hypotheses={workflow.accepted_hypotheses}
              predictions={workflow.compiled_probe.predictions}
            />
            <div className="hash-readout">
              <span>Specification hash</span>
              <code>{workflow.compiled_probe.specification_hash}</code>
            </div>
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

      {stages.abstentionMessage === null ? null : (
        <p className="workflow-outcome" role="status">
          {stages.abstentionMessage}
        </p>
      )}
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
