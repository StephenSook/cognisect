import { forwardBackendRequest, resolveBackendUrl } from "@/lib/backend-proxy";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

async function proxyRequest(request: Request, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  return forwardBackendRequest({
    request,
    path,
    backendUrl: resolveBackendUrl(
      process.env.COGNISECT_BACKEND_URL,
      process.env.NODE_ENV,
      process.env.COGNISECT_FRONTEND_ENV,
    ),
    secureOwnerCookie: process.env.NODE_ENV === "production",
  });
}

export const DELETE = proxyRequest;
export const GET = proxyRequest;
export const POST = proxyRequest;
