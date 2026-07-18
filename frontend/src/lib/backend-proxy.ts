import { createHmac } from "node:crypto";
import { isIP } from "node:net";

const ALLOWED_METHODS = new Set(["DELETE", "GET", "POST"]);
const RESPONSE_HEADERS = [
  "cache-control",
  "content-disposition",
  "content-type",
  "referrer-policy",
  "retry-after",
  "set-cookie",
] as const;
const OWNER_COOKIE = "cognisect_owner";
const MAX_PROXY_BODY_BYTES = 32_768;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type ProxyInput = {
  request: Request;
  path: string[];
  backendUrl: string;
  fetchImplementation?: typeof fetch;
  proxySigningSecret?: string;
};

const PROXY_BUCKET_CONTEXT = "cognisect:proxy-client-bucket:v1";
const PROXY_REQUEST_CONTEXT = "cognisect:proxy-request:v1";
const PROXY_BUCKET_HEADER = "x-cognisect-client-bucket";
const PROXY_TIMESTAMP_HEADER = "x-cognisect-proxy-timestamp";
const PROXY_SIGNATURE_HEADER = "x-cognisect-proxy-signature";

function ownerCookie(cookieHeader: string | null): string | null {
  if (cookieHeader === null) return null;
  const match = cookieHeader
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${OWNER_COOKIE}=`));
  return match ?? null;
}

function isLearnerPath(path: string[]): boolean {
  return path[0] === "v1" && path[1] === "respond";
}

function isAllowedPath(method: string, path: string[]): boolean {
  if (method === "GET" && (path.join("/") === "health" || path.join("/") === "version")) {
    return true;
  }
  if (path[0] !== "v1") return false;
  if (path.length === 2 && path[1] === "cases") return method === "POST";
  if (path[1] === "respond" && path.length === 3 && path[2]) {
    return method === "GET" || method === "POST";
  }
  if (path[1] === "cases" && path.length === 4 && path[3] === "analysis") {
    return method === "POST" && UUID_PATTERN.test(path[2] ?? "");
  }
  if (path[1] !== "workflows" || !UUID_PATTERN.test(path[2] ?? "")) return false;
  if (path.length === 3) return method === "GET" || method === "DELETE";
  if (path.length !== 4) return false;
  const action = path[3];
  return (
    ((action === "audit" || action === "receipt") && method === "GET") ||
    ((action === "probe-approval" || action === "review") && method === "POST")
  );
}

function rejectedPath(path: string[]): Response {
  const headers = new Headers();
  if (isLearnerPath(path)) {
    headers.set("cache-control", "no-store, private");
    headers.set("referrer-policy", "no-referrer");
  }
  return Response.json({ detail: "resource not found" }, { status: 404, headers });
}

function oversizedBody(path: string[]): Response {
  const headers = new Headers({ "content-type": "application/json" });
  if (isLearnerPath(path)) {
    headers.set("cache-control", "no-store, private");
    headers.set("referrer-policy", "no-referrer");
  }
  return Response.json({ detail: "request body too large" }, { status: 413, headers });
}

export function resolveBackendUrl(
  configuredUrl: string | undefined,
  nodeEnvironment: string | undefined,
  frontendEnvironment?: string,
): string {
  const value = configuredUrl ?? "http://127.0.0.1:8000";
  if (nodeEnvironment !== "production") return value;
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("COGNISECT_BACKEND_URL must be an absolute production URL");
  }
  const isLoopback = ["127.0.0.1", "::1", "localhost"].includes(parsed.hostname);
  const isProductionTransport = parsed.protocol === "https:" && !isLoopback;
  const isTestTransport =
    frontendEnvironment === "test" && parsed.protocol === "http:" && isLoopback;
  if (configuredUrl === undefined || (!isProductionTransport && !isTestTransport)) {
    throw new Error("COGNISECT_BACKEND_URL must be explicit and HTTPS in production");
  }
  return value;
}

export function resolveProxySigningSecret(
  configuredSecret: string | undefined,
  nodeEnvironment: string | undefined,
): string | undefined {
  if (configuredSecret === undefined && nodeEnvironment !== "production") return undefined;
  if (
    configuredSecret === undefined ||
    !/^[A-Za-z0-9_-]{32,128}$/.test(configuredSecret) ||
    /replace-with|placeholder|change-?me/i.test(configuredSecret)
  ) {
    throw new Error(
      "COGNISECT_PROXY_SIGNING_SECRET must be 32-128 base64url ASCII characters in production",
    );
  }
  return configuredSecret;
}

function invalidProxyIdentity(): Response {
  return Response.json({ detail: "invalid proxy identity" }, { status: 400 });
}

function attachSignedProxyIdentity(
  request: Request,
  requestHeaders: Headers,
  method: string,
  canonicalPath: string,
  proxySigningSecret: string,
): boolean {
  const clientIp = request.headers.get("x-vercel-forwarded-for")?.trim();
  if (clientIp === undefined || isIP(clientIp) === 0) return false;
  const bucket = createHmac("sha256", proxySigningSecret)
    .update(`${PROXY_BUCKET_CONTEXT}\0${clientIp}`)
    .digest("hex");
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const signature = createHmac("sha256", proxySigningSecret)
    .update([PROXY_REQUEST_CONTEXT, timestamp, method, canonicalPath, bucket].join("\n"))
    .digest("hex");
  requestHeaders.set(PROXY_BUCKET_HEADER, bucket);
  requestHeaders.set(PROXY_TIMESTAMP_HEADER, timestamp);
  requestHeaders.set(PROXY_SIGNATURE_HEADER, signature);
  return true;
}

export async function forwardBackendRequest({
  request,
  path,
  backendUrl,
  fetchImplementation = fetch,
  proxySigningSecret,
}: ProxyInput): Promise<Response> {
  if (!ALLOWED_METHODS.has(request.method)) {
    return new Response(null, { status: 405, headers: { Allow: "DELETE, GET, POST" } });
  }
  if (
    path.length === 0 ||
    path.some((segment) => !segment || segment === "." || segment === "..") ||
    !isAllowedPath(request.method, path)
  )
    return rejectedPath(path);

  const cookie = ownerCookie(request.headers.get("cookie"));
  const requestHeaders = new Headers();
  const contentType = request.headers.get("content-type");
  const idempotencyKey = request.headers.get("idempotency-key");
  if (contentType !== null) requestHeaders.set("content-type", contentType);
  if (idempotencyKey !== null) requestHeaders.set("idempotency-key", idempotencyKey);
  if (cookie !== null && !isLearnerPath(path)) requestHeaders.set("cookie", cookie);

  const canonicalPath = `/${path.map((segment) => encodeURIComponent(segment)).join("/")}`;
  if (
    request.method === "POST" &&
    path.join("/") === "v1/cases" &&
    proxySigningSecret !== undefined &&
    !attachSignedProxyIdentity(
      request,
      requestHeaders,
      request.method,
      canonicalPath,
      proxySigningSecret,
    )
  ) {
    return invalidProxyIdentity();
  }

  let body: ArrayBuffer | undefined;
  if (request.method === "POST") {
    const declaredLength = Number(request.headers.get("content-length"));
    if (Number.isFinite(declaredLength) && declaredLength > MAX_PROXY_BODY_BYTES)
      return oversizedBody(path);
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_PROXY_BODY_BYTES) return oversizedBody(path);
  }

  const base = backendUrl.replace(/\/$/, "");
  const upstream = await fetchImplementation(
    `${base}${canonicalPath}`,
    {
      method: request.method,
      headers: requestHeaders,
      body,
      redirect: "manual",
    },
  );
  const responseHeaders = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) responseHeaders.set(name, value);
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}
