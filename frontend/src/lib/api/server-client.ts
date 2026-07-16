import { headers } from "next/headers";

import { createApiClient } from "@/lib/api/client";
import { ownerCookieHeader, resolveFrontendUrl } from "@/lib/api/server-request";

export async function createServerApiClient() {
  const requestHeaders = await headers();
  const appUrl = resolveFrontendUrl(
    process.env.COGNISECT_APP_URL,
    process.env.NODE_ENV,
    process.env.COGNISECT_FRONTEND_ENV,
  );
  return createApiClient(
    `${appUrl.replace(/\/$/, "")}/api/backend`,
    fetch,
    ownerCookieHeader(requestHeaders.get("cookie")),
  );
}
