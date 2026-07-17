import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { config, proxy } from "@/proxy";

describe("teacher first-visit owner session", () => {
  it("leaves first owner bootstrap to the distributed backend boundary", () => {
    const response = proxy(new NextRequest("https://app.example/lab"));

    expect(response.cookies.get("cognisect_owner")).toBeUndefined();
  });

  it("preserves an existing owner capability", () => {
    const request = new NextRequest("https://app.example/case/id", {
      headers: { cookie: "cognisect_owner=existing-owner" },
    });
    const response = proxy(request);

    expect(response.cookies.get("cognisect_owner")).toBeUndefined();
  });

  it("matches only teacher surfaces and never learner or internal proxy paths", () => {
    expect(config.matcher).toEqual([
      "/",
      "/lab/:path*",
      "/case/:path*",
      "/report/:path*",
      "/runtime/:path*",
    ]);
    expect(config.matcher.join(" ")).not.toContain("respond");
    expect(config.matcher.join(" ")).not.toContain("api");
  });
});
