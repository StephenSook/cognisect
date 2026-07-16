import { createApiClient } from "@/lib/api/client";

export function createBrowserApiClient() {
  return createApiClient(`${window.location.origin}/api/backend`);
}
