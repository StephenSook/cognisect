import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ReportView } from "@/components/report-view";
import { createServerApiClient } from "@/lib/api/server-client";

export const metadata: Metadata = { title: "Teacher report" };
export const dynamic = "force-dynamic";

export default async function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const client = await createServerApiClient();
  const [workflow, audit] = await Promise.all([
    client.GET("/v1/workflows/{workflow_id}", {
      params: { path: { workflow_id: id } },
      cache: "no-store",
    }),
    client.GET("/v1/workflows/{workflow_id}/audit", {
      params: { path: { workflow_id: id } },
      cache: "no-store",
    }),
  ]);
  if (workflow.response.status === 404 || audit.response.status === 404) notFound();
  if (workflow.data === undefined || audit.data === undefined) {
    throw new Error("report readback unavailable");
  }
  return <ReportView workflow={workflow.data} audit={audit.data} />;
}
