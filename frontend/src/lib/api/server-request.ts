const OWNER_COOKIE = "cognisect_owner";

export function resolveFrontendUrl(
  configuredUrl: string | undefined,
  nodeEnvironment: string | undefined,
  frontendEnvironment?: string,
): string {
  const value = configuredUrl ?? "http://127.0.0.1:3000";
  if (nodeEnvironment !== "production") return value;
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("COGNISECT_APP_URL must be an absolute production URL");
  }
  const isLoopback = ["127.0.0.1", "::1", "localhost"].includes(parsed.hostname);
  const isProductionTransport = parsed.protocol === "https:" && !isLoopback;
  const isTestTransport =
    frontendEnvironment === "test" && parsed.protocol === "http:" && isLoopback;
  if (configuredUrl === undefined || (!isProductionTransport && !isTestTransport)) {
    throw new Error("COGNISECT_APP_URL must be explicit and HTTPS in production");
  }
  return value;
}

export function ownerCookieHeader(cookieHeader: string | null): HeadersInit {
  if (cookieHeader === null) return {};
  const ownerCookie = cookieHeader
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${OWNER_COOKIE}=`));
  return ownerCookie === undefined ? {} : { cookie: ownerCookie };
}
