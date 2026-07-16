import createClient from "openapi-fetch";

import type { paths } from "@/lib/api/schema";

export function createApiClient(
  baseUrl = "/api/backend",
  fetchImplementation: typeof fetch = fetch,
  headers?: HeadersInit,
) {
  return createClient<paths>({
    baseUrl,
    credentials: "same-origin",
    fetch: fetchImplementation,
    headers,
  });
}
