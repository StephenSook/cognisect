import type { components } from "@/lib/api/schema";
import { EvidenceReceiptButton } from "@/components/evidence-receipt-button";
import { JudgeTour } from "@/components/judge-tour";
import { ReviewForm } from "@/components/review-form";
import { workflowPresentation } from "@/lib/workflow-presentation";

type Workflow = components["schemas"]["WorkflowResponse"];
type Audit = components["schemas"]["AuditResponse"];

export function ReportView({ workflow, audit }: { workflow: Workflow; audit: Audit }) {
  const presentation = workflowPresentation(workflow);
  return (
    <article className="workbench report-workbench">
      <header className="workbench-heading">
        <div>
          <p className="eyebrow eyebrow--ink">Persisted audit note</p>
          <h1>Teacher report</h1>
          <p>Deterministic evidence remains separate from the teacher&apos;s final judgment.</p>
        </div>
        <span className="state-badge" data-state={workflow.state}>
          <span aria-hidden="true" /> {workflow.state.replaceAll("_", " ")}
        </span>
      </header>
      <dl className="metadata-strip">
        <div><dt>Workflow state</dt><dd>{workflow.state}</dd></div>
        <div><dt>Version</dt><dd>{workflow.version}</dd></div>
        <div><dt>Schema</dt><dd>{workflow.schema_version}</dd></div>
      </dl>
      <JudgeTour currentStage={presentation.judgeStage} />

      <section className="workbench-card" aria-labelledby="report-evidence-heading">
        <p className="card-index mono">LEARNER ANSWER / EXACT MATCH</p>
        <h2 id="report-evidence-heading">Deterministic evidence</h2>
        {workflow.deterministic_evidence.length === 0 ? (
          <p>No deterministic evidence is persisted.</p>
        ) : (
          <ul className="evidence-list">
            {workflow.deterministic_evidence.map((item) => (
              <li key={item.rank}>
                <span>Hypothesis {String(item.rank).padStart(2, "0")}</span>
                <strong data-evidence={item.status}>{item.status}</strong>
              </li>
            ))}
          </ul>
        )}
        <p className="proposal-copy"><strong>Generated proposal</strong>{workflow.generated_proposal ?? "Not available"}</p>
        {workflow.learner_rationale !== null ? (
          <p className="proposal-copy">
            <strong>Review-only learner rationale</strong>{workflow.learner_rationale}
          </p>
        ) : null}
      </section>

      {workflow.state === "AWAITING_REVIEW" ? (
        <ReviewForm
          workflowId={workflow.workflow_id}
          version={workflow.version}
          generatedProposal={workflow.generated_proposal ?? null}
        />
      ) : workflow.review_result !== null ? (
        <section className="workbench-card final-decision" aria-labelledby="review-result-heading">
          <p className="card-index mono">SECOND TEACHER GATE / PERSISTED</p>
          <h2 id="review-result-heading">Persisted final teacher decision</h2>
          <p><strong>Decision</strong>{workflow.review_result.decision}</p>
          {workflow.review_result.note ? (
            <p><strong>Teacher note</strong>{workflow.review_result.note}</p>
          ) : null}
          {workflow.review_result.edited_text ? (
            <p><strong>Teacher-edited proposal</strong>{workflow.review_result.edited_text}</p>
          ) : null}
        </section>
      ) : workflow.state === "ABSTAINED" ? (
        <section className="workbench-card" aria-labelledby="abstention-outcome-heading">
          <p className="card-index mono">WORKFLOW ABSTENTION / OWNER READBACK</p>
          <h2 id="abstention-outcome-heading">Abstention outcome</h2>
          <p>{presentation.abstentionMessage}</p>
        </section>
      ) : null}

      <section className="workbench-card receipt-stage" aria-labelledby="receipt-stage-heading">
        <p className="card-index mono">OWNER AUTHORIZED / PRIVACY SAFE</p>
        <h2 id="receipt-stage-heading">Evidence receipt</h2>
        <p>The download begins only when the owner activates the real receipt endpoint.</p>
        <EvidenceReceiptButton workflowId={workflow.workflow_id} />
      </section>

      <section className="audit-stage" aria-labelledby="audit-heading">
        <p className="card-index mono">APPEND ONLY / READBACK</p>
        <h2 id="audit-heading">Append-only workflow audit</h2>
        <ol className="audit-list">
          {audit.events.map((event) => (
            <li key={event.sequence}>
              {event.from_state ?? "START"} → {event.to_state}, version {event.version}, {" "}
              {event.occurred_at}
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}
