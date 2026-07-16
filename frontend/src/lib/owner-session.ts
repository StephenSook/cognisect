export const OWNER_COOKIE_NAME = "cognisect_owner";
const DEFAULT_RETENTION_DAYS = 30;

export function generateOwnerSecret(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function ownerRetentionSeconds(configuredDays?: string): number {
  const days = configuredDays === undefined ? DEFAULT_RETENTION_DAYS : Number(configuredDays);
  if (!Number.isInteger(days) || days < 1 || days > 365) {
    throw new Error("COGNISECT_RETENTION_DAYS must be an integer from 1 through 365");
  }
  return days * 86_400;
}

export function serializeOwnerCookie(
  secret: string,
  { secure, maxAge }: { secure: boolean; maxAge: number },
): string {
  const attributes = [
    `${OWNER_COOKIE_NAME}=${secret}`,
    "Path=/",
    `Max-Age=${maxAge}`,
    "HttpOnly",
    "SameSite=Lax",
  ];
  if (secure) attributes.push("Secure");
  return attributes.join("; ");
}
