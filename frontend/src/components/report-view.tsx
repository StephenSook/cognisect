import type { components } from "@/lib/api/schema";
import { ReviewForm } from "@/components/review-form";

type Workflow = components["schemas"]["WorkflowResponse"];
type Audit = components["schemas"]["AuditResponse"];

export function ReportView({ workflow, audit }: { workflow: Workflow; audit: Audit }) {
  return (
    <article>
      <h1>Teacher report</h1>
      <dl>
        <dt>Workflow state</dt>
        <dd>{workflow.state}</dd>
        <dt>Version</dt>
        <dd>{workflow.version}</dd>
      </dl>

      <section aria-labelledby="report-evidence-heading">
        <h2 id="report-evidence-heading">Deterministic evidence</h2>
        {workflow.deterministic_evidence.length === 0 ? (
          <p>No deterministic evidence is persisted.</p>
        ) : (
          <ul>
            {workflow.deterministic_evidence.map((item) => (
              <li key={item.rank}>
                Rank {item.rank}: {item.status}
              </li>
            ))}
          </ul>
        )}
        <p>Generated proposal: {workflow.generated_proposal ?? "Not available"}</p>
        {workflow.edited_text ? <p>Teacher-edited text: {workflow.edited_text}</p> : null}
      </section>

      {workflow.state === "AWAITING_REVIEW" ? (
        <ReviewForm
          workflowId={workflow.workflow_id}
          version={workflow.version}
          generatedProposal={workflow.generated_proposal ?? null}
        />
      ) : (
        <section aria-labelledby="review-result-heading">
          <h2 id="review-result-heading">Persisted review result</h2>
          <p>{workflow.review_result?.decision ?? "No final review is persisted."}</p>
        </section>
      )}

      <section aria-labelledby="audit-heading">
        <h2 id="audit-heading">Append-only workflow audit</h2>
        <ol>
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
