import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { WorkflowPanel } from "@/components/workflow-panel";
import { createServerApiClient } from "@/lib/api/server-client";

export const metadata: Metadata = { title: "Case workflow" };
export const dynamic = "force-dynamic";

export default async function CasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await (await createServerApiClient()).GET(
    "/v1/workflows/{workflow_id}",
    { params: { path: { workflow_id: id } }, cache: "no-store" },
  );
  if (result.response.status === 404) notFound();
  if (result.data === undefined) throw new Error("workflow readback unavailable");
  return <WorkflowPanel initialWorkflow={result.data} />;
}
