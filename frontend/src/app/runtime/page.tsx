import type { Metadata } from "next";

import type { components } from "@/lib/api/schema";
import { createServerApiClient } from "@/lib/api/server-client";
import { RuntimeEvidence } from "@/components/runtime-evidence";

type Workflow = components["schemas"]["WorkflowResponse"];
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const metadata: Metadata = { title: "Runtime evidence" };
export const dynamic = "force-dynamic";

export default async function RuntimePage({
  searchParams,
}: {
  searchParams: Promise<{ workflow_id?: string }>;
}) {
  const { workflow_id: workflowId } = await searchParams;
  const client = await createServerApiClient();
  const version = await client.GET("/version", { cache: "no-store" });
  if (version.data === undefined) throw new Error("version evidence unavailable");

  let workflow: Workflow | undefined;
  let workflowUnavailable = false;
  if (workflowId !== undefined && UUID_PATTERN.test(workflowId)) {
    const result = await client.GET("/v1/workflows/{workflow_id}", {
      params: { path: { workflow_id: workflowId } },
      cache: "no-store",
    });
    if (result.response.status === 404) workflowUnavailable = true;
    else if (result.data === undefined) throw new Error("workflow metadata unavailable");
    else workflow = result.data;
  }

  return (
    <>
      <form method="get">
        <label htmlFor="runtime-workflow-id">Owned workflow ID (optional)</label>
        <input id="runtime-workflow-id" name="workflow_id" />
        <button type="submit">Load persisted metadata</button>
      </form>
      {workflowId !== undefined && !UUID_PATTERN.test(workflowId) ? (
        <p role="alert">Enter a valid workflow ID.</p>
      ) : null}
      {workflowUnavailable ? (
        <p role="alert">Owned workflow metadata is unavailable.</p>
      ) : null}
      <RuntimeEvidence version={version.data} workflow={workflow} />
    </>
  );
}
