import { NextRequest, NextResponse } from "next/server";

import {
  generateOwnerSecret,
  OWNER_COOKIE_NAME,
  ownerRetentionSeconds,
} from "@/lib/owner-session";

export function proxy(request: NextRequest) {
  if (request.cookies.has(OWNER_COOKIE_NAME)) return NextResponse.next();

  const response = NextResponse.next();
  response.cookies.set({
    name: OWNER_COOKIE_NAME,
    value: generateOwnerSecret(),
    httpOnly: true,
    sameSite: "lax",
    secure: request.nextUrl.protocol === "https:" || process.env.NODE_ENV === "production",
    path: "/",
    maxAge: ownerRetentionSeconds(process.env.COGNISECT_RETENTION_DAYS),
  });
  return response;
}

export const config = {
  matcher: ["/", "/lab/:path*", "/case/:path*", "/report/:path*", "/runtime/:path*"],
};
