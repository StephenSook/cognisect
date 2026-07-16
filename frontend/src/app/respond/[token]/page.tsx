import type { Metadata } from "next";

import { LearnerResponseForm } from "@/components/learner-response-form";
import { createServerApiClient } from "@/lib/api/server-client";

export const metadata: Metadata = { title: "Learner response" };
export const dynamic = "force-dynamic";

export default async function LearnerPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const result = await (await createServerApiClient()).GET("/v1/respond/{token}", {
    params: { path: { token } },
    cache: "no-store",
  });
  if (result.data !== undefined) return <LearnerResponseForm token={token} probe={result.data} />;
  const message =
    result.response.status === 410
      ? "This learner link has expired."
      : "This learner link is invalid or unavailable.";
  return (
    <article>
      <h1>Learner response unavailable</h1>
      <p role="alert">{message}</p>
    </article>
  );
}
