import { describe, expect, it, vi } from "vitest";

import { forwardBackendRequest, resolveBackendUrl } from "@/lib/backend-proxy";

describe("same-origin backend proxy", () => {
  it("bootstraps an owner without forwarding the first educational mutation", async () => {
    const upstream = vi.fn();
    const response = await forwardBackendRequest({
      request: new Request("http://frontend.test/api/backend/v1/cases", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "stable-create-key",
        },
        body: '{"observed_work":"de-identified"}',
      }),
      path: ["v1", "cases"],
      backendUrl: "http://backend.test",
      fetchImplementation: upstream,
    });

    expect(response.status).toBe(428);
    expect(response.headers.get("set-cookie")).toMatch(
      /^cognisect_owner=[0-9a-f]{64};.*HttpOnly.*SameSite=Lax/i,
    );
    expect(upstream).not.toHaveBeenCalled();
  });

  it("forwards only the teacher request contract and owner cookie", async () => {
    const upstream = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      expect(init?.method).toBe("POST");
      const headers = new Headers(init?.headers);
      expect(Object.fromEntries(headers)).toEqual({
        "content-type": "application/json",
        cookie: "cognisect_owner=owner-capability",
        "idempotency-key": "stable-create-key",
      });
      expect(new TextDecoder().decode(init?.body as ArrayBuffer)).toBe(
        '{"observed_work":"de-identified"}',
      );
      return new Response('{"workflow_id":"workflow-1"}', {
        status: 201,
        headers: {
          "Cache-Control": "no-store, private",
          "Content-Type": "application/json",
          "Referrer-Policy": "no-referrer",
          "Set-Cookie": "cognisect_owner=new-owner; HttpOnly; SameSite=Lax",
          "X-Internal-Debug": "must-not-leak",
        },
      });
    });
    const request = new Request("http://frontend.test/api/backend/v1/cases", {
      method: "POST",
      body: '{"observed_work":"de-identified"}',
      headers: {
        Authorization: "must-not-forward",
        Cookie: "cognisect_owner=owner-capability; unrelated=private",
        "Content-Type": "application/json",
        "Idempotency-Key": "stable-create-key",
        "X-Teacher-Note": "must-not-forward",
      },
    });

    const response = await forwardBackendRequest({
      request,
      path: ["v1", "cases"],
      backendUrl: "http://backend.test",
      fetchImplementation: upstream,
    });

    expect(upstream).toHaveBeenCalledOnce();
    expect(upstream.mock.calls[0]?.[0]).toBe("http://backend.test/v1/cases");
    expect(response.status).toBe(201);
    expect(Object.fromEntries(response.headers)).toEqual({
      "cache-control": "no-store, private",
      "content-type": "application/json",
      "referrer-policy": "no-referrer",
      "set-cookie": "cognisect_owner=new-owner; HttpOnly; SameSite=Lax",
    });
  });

  it("does not attach the teacher owner capability to learner requests", async () => {
    const upstream = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      expect(new Headers(init?.headers).has("cookie")).toBe(false);
      return Response.json({ problem: { a: -2, b: -7 } });
    });
    const request = new Request("http://frontend.test/api/backend/v1/respond/raw-token", {
      headers: { Cookie: "cognisect_owner=owner-capability" },
    });

    await forwardBackendRequest({
      request,
      path: ["v1", "respond", "raw-token"],
      backendUrl: "http://backend.test",
      fetchImplementation: upstream,
    });

    expect(upstream).toHaveBeenCalledOnce();
  });

  it("rejects methods outside the public backend surface without dispatch", async () => {
    const upstream = vi.fn();
    const response = await forwardBackendRequest({
      request: new Request("http://frontend.test/api/backend/v1/cases", {
        method: "PUT",
      }),
      path: ["v1", "cases"],
      backendUrl: "http://backend.test",
      fetchImplementation: upstream,
    });

    expect(response.status).toBe(405);
    expect(upstream).not.toHaveBeenCalled();
  });

  it.each([
    ["GET", ["internal", "model-calls"]],
    ["POST", ["version"]],
    ["GET", ["v1", "workflows", "not-a-uuid"]],
    ["GET", ["v1", "respond", "raw-token", "extra"]],
    ["GET", ["v1", "respond", ".."]],
  ])("rejects a non-public %s backend path without dispatch", async (method, path) => {
    const upstream = vi.fn();
    const response = await forwardBackendRequest({
      request: new Request(`http://frontend.test/api/backend/${path.join("/")}`, {
        method,
      }),
      path,
      backendUrl: "http://backend.test",
      fetchImplementation: upstream,
    });

    expect(response.status).toBe(404);
    expect(upstream).not.toHaveBeenCalled();
    if (path[0] === "v1" && path[1] === "respond") {
      expect(response.headers.get("cache-control")).toBe("no-store, private");
      expect(response.headers.get("referrer-policy")).toBe("no-referrer");
    }
  });

  it("fails closed on a missing or local production backend URL", () => {
    expect(() => resolveBackendUrl(undefined, "production")).toThrow(
      "COGNISECT_BACKEND_URL",
    );
    expect(() => resolveBackendUrl("http://127.0.0.1:8000", "production")).toThrow(
      "COGNISECT_BACKEND_URL",
    );
    expect(resolveBackendUrl(undefined, "test")).toBe("http://127.0.0.1:8000");
    expect(resolveBackendUrl("https://backend.example", "production")).toBe(
      "https://backend.example",
    );
  });

  it("allows loopback HTTP in production only behind the exact test transport gate", () => {
    expect(
      resolveBackendUrl("http://127.0.0.1:8000", "production", "test"),
    ).toBe("http://127.0.0.1:8000");
    expect(() =>
      resolveBackendUrl("http://127.0.0.1:8000", "production", "testing"),
    ).toThrow("COGNISECT_BACKEND_URL");
    expect(() =>
      resolveBackendUrl("http://backend.example", "production", "test"),
    ).toThrow("COGNISECT_BACKEND_URL");
    expect(() => resolveBackendUrl(undefined, "production", "test")).toThrow(
      "COGNISECT_BACKEND_URL",
    );
  });
});
