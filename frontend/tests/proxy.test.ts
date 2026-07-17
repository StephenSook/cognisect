import { createHmac } from "node:crypto";

import { describe, expect, it, vi } from "vitest";

import { forwardBackendRequest, resolveBackendUrl } from "@/lib/backend-proxy";

describe("same-origin backend proxy", () => {
  it("forwards initial bootstrap with an authenticated privacy-safe Vercel client bucket", async () => {
    const proxySecret = "p".repeat(32);
    const publicClientIp = "198.51.100.87";
    const expectedBucket = createHmac("sha256", proxySecret)
      .update(`cognisect:proxy-client-bucket:v1\0${publicClientIp}`)
      .digest("hex");
    const upstream = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      const timestamp = headers.get("x-cognisect-proxy-timestamp");
      expect(timestamp).toMatch(/^\d{10}$/);
      expect(headers.get("x-cognisect-client-bucket")).toBe(expectedBucket);
      expect(headers.has("x-vercel-forwarded-for")).toBe(false);
      const expectedSignature = createHmac("sha256", proxySecret)
        .update(
          [
            "cognisect:proxy-request:v1",
            timestamp,
            "POST",
            "/v1/cases",
            expectedBucket,
          ].join("\n"),
        )
        .digest("hex");
      expect(headers.get("x-cognisect-proxy-signature")).toBe(expectedSignature);
      return Response.json(
        { detail: "owner session initialized; retry the exact command" },
        {
          status: 428,
          headers: {
            "Cache-Control": "no-store, private",
            "Set-Cookie": "cognisect_owner=backend-owner; HttpOnly; SameSite=Lax",
          },
        },
      );
    });
    const response = await forwardBackendRequest({
      request: new Request("http://frontend.test/api/backend/v1/cases", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "stable-create-key",
          "X-Vercel-Forwarded-For": publicClientIp,
        },
        body: '{"observed_work":"de-identified"}',
      }),
      path: ["v1", "cases"],
      backendUrl: "http://backend.test",
      fetchImplementation: upstream,
      proxySigningSecret: proxySecret,
    });

    expect(response.status).toBe(428);
    expect(response.headers.get("set-cookie")).toBe(
      "cognisect_owner=backend-owner; HttpOnly; SameSite=Lax",
    );
    expect(upstream).toHaveBeenCalledOnce();
  });

  it("fails closed when signed case forwarding lacks Vercel client identity", async () => {
    const upstream = vi.fn();
    const response = await forwardBackendRequest({
      request: new Request("http://frontend.test/api/backend/v1/cases", {
        method: "POST",
        headers: { "Idempotency-Key": "missing-platform-identity" },
        body: "{}",
      }),
      path: ["v1", "cases"],
      backendUrl: "http://backend.test",
      fetchImplementation: upstream,
      proxySigningSecret: "p".repeat(32),
    });

    expect(response.status).toBe(400);
    expect(response.json()).resolves.toEqual({ detail: "invalid proxy identity" });
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

  it("forwards owner-authorized receipt downloads and their exact filename", async () => {
    const workflowId = "00000000-0000-4000-8000-000000000001";
    const filename = `cognisect-evidence-${workflowId}.json`;
    const upstream = vi.fn(async () =>
      new Response('{"receipt_version":"evidence_receipt.v1"}', {
        headers: { "Content-Disposition": `attachment; filename="${filename}"` },
      }),
    );
    const response = await forwardBackendRequest({
      request: new Request(
        `http://frontend.test/api/backend/v1/workflows/${workflowId}/receipt`,
        { headers: { Cookie: "cognisect_owner=owner-capability" } },
      ),
      path: ["v1", "workflows", workflowId, "receipt"],
      backendUrl: "http://backend.test",
      fetchImplementation: upstream,
    });

    expect(upstream).toHaveBeenCalledOnce();
    expect(response.headers.get("content-disposition")).toBe(
      `attachment; filename="${filename}"`,
    );
  });

  it("propagates only the privacy-safe Retry-After header on upstream 429", async () => {
    const response = await forwardBackendRequest({
      request: new Request("http://frontend.test/api/backend/v1/cases", {
        method: "POST",
        headers: {
          Cookie: "cognisect_owner=owner-capability",
          "Idempotency-Key": "rate-limited-create",
        },
        body: "{}",
      }),
      path: ["v1", "cases"],
      backendUrl: "http://backend.test",
      fetchImplementation: vi.fn(async () =>
        Response.json(
          { detail: "rate limit exceeded" },
          {
            status: 429,
            headers: { "Retry-After": "37", "X-Internal-Debug": "private" },
          },
        ),
      ),
    });

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("37");
    expect(response.headers.has("x-internal-debug")).toBe(false);
  });

  it("rejects oversized raw bodies before forwarding and preserves learner privacy", async () => {
    const upstream = vi.fn();
    const oversized = "x".repeat(32_769);
    const teacher = await forwardBackendRequest({
      request: new Request("http://frontend.test/api/backend/v1/cases", {
        method: "POST",
        headers: {
          Cookie: "cognisect_owner=owner-capability",
          "Content-Type": "application/json",
          "Idempotency-Key": "oversized-teacher-body",
        },
        body: oversized,
      }),
      path: ["v1", "cases"],
      backendUrl: "http://backend.test",
      fetchImplementation: upstream,
    });
    const learner = await forwardBackendRequest({
      request: new Request("http://frontend.test/api/backend/v1/respond/raw-token", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "oversized-learner-body",
        },
        body: oversized,
      }),
      path: ["v1", "respond", "raw-token"],
      backendUrl: "http://backend.test",
      fetchImplementation: upstream,
    });

    expect(teacher.status).toBe(413);
    expect(learner.status).toBe(413);
    expect(learner.headers.get("cache-control")).toBe("no-store, private");
    expect(learner.headers.get("referrer-policy")).toBe("no-referrer");
    expect(upstream).not.toHaveBeenCalled();
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

  it("requires an explicit bounded proxy signing secret in production", async () => {
    const proxyModule = await import("@/lib/backend-proxy");
    const resolver = Reflect.get(proxyModule, "resolveProxySigningSecret");
    expect(typeof resolver).toBe("function");
    expect(() => resolver(undefined, "production")).toThrow(
      "COGNISECT_PROXY_SIGNING_SECRET",
    );
    expect(() => resolver("short", "production")).toThrow(
      "COGNISECT_PROXY_SIGNING_SECRET",
    );
    expect(resolver("p".repeat(32), "production")).toBe("p".repeat(32));
    expect(resolver(undefined, "development")).toBeUndefined();
  });
});
