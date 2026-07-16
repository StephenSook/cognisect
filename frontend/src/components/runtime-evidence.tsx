import type { components } from "@/lib/api/schema";

type Version = components["schemas"]["VersionResponse"];
type Workflow = components["schemas"]["WorkflowResponse"];

export function RuntimeEvidence({
  version,
  workflow,
}: {
  version: Version;
  workflow?: Workflow;
}) {
  return (
    <article>
      <h1>Runtime evidence</h1>
      <p>
        This page reports only metadata returned by the public API. No live-model status is
        claimed.
      </p>
      <h2>Served versions</h2>
      <dl>
        <dt>Application</dt>
        <dd>{version.version}</dd>
        <dt>Workflow schema</dt>
        <dd>{version.schema_version}</dd>
        <dt>Rule registry</dt>
        <dd>{version.registry_version}</dd>
        <dt>Compiler</dt>
        <dd>{version.compiler_version}</dd>
      </dl>
      <h2>Route policy</h2>
      <ul>
        <li>Browser API calls use the same-origin /api/backend proxy.</li>
        <li>Teacher workflow reads require the opaque owner cookie.</li>
        <li>Learner response routes receive no teacher owner cookie.</li>
      </ul>
      {workflow === undefined ? (
        <p>No owned workflow was selected for persisted runtime metadata.</p>
      ) : (
        <section aria-labelledby="workflow-runtime-heading">
          <h2 id="workflow-runtime-heading">Persisted workflow metadata</h2>
          <dl>
            <dt>Source tier</dt>
            <dd>{workflow.source_tier}</dd>
            <dt>Model snapshot</dt>
            <dd>{workflow.model_snapshot ?? "Not recorded"}</dd>
            <dt>Model request ID</dt>
            <dd>{workflow.model_request_id ?? "Not recorded"}</dd>
            <dt>Prompt version</dt>
            <dd>{workflow.prompt_version}</dd>
          </dl>
        </section>
      )}
    </article>
  );
}
