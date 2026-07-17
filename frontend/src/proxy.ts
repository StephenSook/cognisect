import { NextRequest, NextResponse } from "next/server";

export function proxy(_request: NextRequest) {
  void _request;
  return NextResponse.next();
}

export const config = {
  matcher: ["/", "/lab/:path*", "/case/:path*", "/report/:path*", "/runtime/:path*"],
};
