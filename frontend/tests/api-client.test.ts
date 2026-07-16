import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "@/lib/api/client";
import { ownerCookieHeader, resolveFrontendUrl } from "@/lib/api/server-request";

describe("generated API client wrapper", () => {
  it("uses the same-origin proxy with generated response types", async () => {
    const fetchImplementation = vi
      .fn<(request: Request) => Promise<Response>>()
      .mockResolvedValue(
        Response.json({
        version: "0.1.0",
        schema_version: "workflow.v1",
        registry_version: "rule_registry.v1",
        compiler_version: "counterexample_compiler.v1",
        }),
      );
    const client = createApiClient(
      "http://frontend.test/api/backend",
      fetchImplementation as typeof fetch,
    );

    const { data, error, response } = await client.GET("/version");

    expect(error).toBeUndefined();
    expect(response.status).toBe(200);
    expect(data?.registry_version).toBe("rule_registry.v1");
    expect(fetchImplementation).toHaveBeenCalledOnce();
    expect((fetchImplementation.mock.calls[0]?.[0] as Request).url).toBe(
      "http://frontend.test/api/backend/version",
    );
  });
});

describe("authenticated server request boundary", () => {
  it("uses an explicit trusted production origin and forwards only the owner cookie", () => {
    expect(() => resolveFrontendUrl(undefined, "production")).toThrow(
      "COGNISECT_APP_URL",
    );
    expect(() => resolveFrontendUrl("http://127.0.0.1:3000", "production")).toThrow(
      "COGNISECT_APP_URL",
    );
    expect(resolveFrontendUrl("https://app.example", "production")).toBe(
      "https://app.example",
    );
    expect(
      ownerCookieHeader("unrelated=private; cognisect_owner=owner-capability; theme=dark"),
    ).toEqual({ cookie: "cognisect_owner=owner-capability" });
    expect(ownerCookieHeader("unrelated=private")).toEqual({});
  });

  it("allows a production loopback origin only behind the exact test transport gate", () => {
    expect(
      resolveFrontendUrl("http://127.0.0.1:3100", "production", "test"),
    ).toBe("http://127.0.0.1:3100");
    expect(() =>
      resolveFrontendUrl("http://127.0.0.1:3100", "production", "testing"),
    ).toThrow("COGNISECT_APP_URL");
    expect(() =>
      resolveFrontendUrl("http://app.example", "production", "test"),
    ).toThrow("COGNISECT_APP_URL");
    expect(() => resolveFrontendUrl(undefined, "production", "test")).toThrow(
      "COGNISECT_APP_URL",
    );
  });
});
