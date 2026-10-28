/**
 * ViewMagnetClient — auth header injection, error envelope parsing,
 * timeout behaviour. Uses a tiny in-process Node HTTP server so we
 * don't depend on `fetch`-mocking libraries.
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import { ViewMagnetClient, ViewMagnetApiError } from "../src/client.js";
import { loadConfig } from "../src/config.js";

interface CapturedRequest {
  method: string;
  path: string;
  headers: Record<string, string | string[] | undefined>;
  body: string;
}

interface MockResponse {
  status: number;
  body: unknown;
}

class MockApi {
  server!: Server;
  port = 0;
  next: MockResponse[] = [];
  captured: CapturedRequest[] = [];
  // Override to introduce a hang for the timeout test.
  delayMs = 0;

  async start(): Promise<void> {
    this.server = createServer((req, res) => {
      const chunks: Buffer[] = [];
      req.on("data", (c) => chunks.push(c));
      req.on("end", () => {
        const body = Buffer.concat(chunks).toString("utf8");
        this.captured.push({
          method: req.method ?? "",
          path: req.url ?? "",
          headers: req.headers,
          body,
        });
        const queued = this.next.shift() ?? {
          status: 200,
          body: { ok: true },
        };
        const respond = () => {
          res.statusCode = queued.status;
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(queued.body));
        };
        if (this.delayMs > 0) {
          setTimeout(respond, this.delayMs);
        } else {
          respond();
        }
      });
    });
    await new Promise<void>((resolve) =>
      this.server.listen(0, "127.0.0.1", () => resolve()),
    );
    this.port = (this.server.address() as AddressInfo).port;
  }

  async stop(): Promise<void> {
    await new Promise<void>((resolve) => this.server.close(() => resolve()));
  }

  enqueue(resp: MockResponse): void {
    this.next.push(resp);
  }

  reset(): void {
    this.next = [];
    this.captured = [];
    this.delayMs = 0;
  }
}

let api: MockApi;

beforeAll(async () => {
  api = new MockApi();
  await api.start();
});

afterAll(async () => {
  await api.stop();
});

function makeClient(overrides: { patToken?: string; timeoutMs?: number } = {}) {
  return new ViewMagnetClient(
    loadConfig({
      apiUrl: `http://127.0.0.1:${api.port}`,
      patToken: overrides.patToken ?? "vm_pat_deadbeef_" + "a".repeat(32),
      requestTimeoutMs: overrides.timeoutMs,
    }),
  );
}

describe("ViewMagnetClient", () => {
  it("sends Authorization: Bearer <pat> on every request", async () => {
    api.reset();
    api.enqueue({ status: 200, body: { ok: true } });
    const client = makeClient();
    await client.get("/anything");
    expect(api.captured).toHaveLength(1);
    expect(api.captured[0].headers["authorization"]).toBe(
      "Bearer vm_pat_deadbeef_" + "a".repeat(32),
    );
    expect(api.captured[0].headers["user-agent"]).toMatch(/^viewmagnet-mcp\//);
  });

  it("serializes POST bodies as JSON", async () => {
    api.reset();
    api.enqueue({ status: 200, body: { ok: true } });
    const client = makeClient();
    await client.post("/x", { url: "https://y.com", channel_id: "UC123" });
    expect(api.captured[0].body).toBe(
      JSON.stringify({ url: "https://y.com", channel_id: "UC123" }),
    );
    expect(api.captured[0].method).toBe("POST");
  });

  it("appends query params on GET", async () => {
    api.reset();
    api.enqueue({ status: 200, body: { ok: true } });
    const client = makeClient();
    await client.get("/items", { limit: 50, sort: "newest" });
    expect(api.captured[0].path).toContain("limit=50");
    expect(api.captured[0].path).toContain("sort=newest");
  });

  it("returns parsed JSON on success", async () => {
    api.reset();
    api.enqueue({ status: 200, body: { score: 87, tier: "Viral" } });
    const client = makeClient();
    const data = await client.get<{ score: number; tier: string }>("/analyze");
    expect(data).toEqual({ score: 87, tier: "Viral" });
  });

  it("throws ViewMagnetApiError with envelope fields on 4xx", async () => {
    api.reset();
    api.enqueue({
      status: 400,
      body: {
        error: {
          code: "bad_request",
          message: "Invalid URL",
          details: { field: "url" },
          request_id: "req_abc123",
        },
      },
    });
    const client = makeClient();
    try {
      await client.post("/analyze", { url: "" });
      expect.fail("expected throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ViewMagnetApiError);
      const e = err as ViewMagnetApiError;
      expect(e.status).toBe(400);
      expect(e.message).toBe("Invalid URL");
      expect(e.code).toBe("bad_request");
      expect(e.requestId).toBe("req_abc123");
      expect(e.details).toEqual({ field: "url" });
    }
  });

  it("falls back to plain `detail` field when no envelope present", async () => {
    api.reset();
    api.enqueue({ status: 422, body: { detail: "Validation failed" } });
    const client = makeClient();
    try {
      await client.post("/x", {});
      expect.fail("expected throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ViewMagnetApiError);
      expect((err as ViewMagnetApiError).message).toBe("Validation failed");
      expect((err as ViewMagnetApiError).status).toBe(422);
    }
  });

  it("refuses to call without a token", async () => {
    api.reset();
    const client = makeClient({ patToken: undefined });
    // makeClient defaults to a real-looking token; build a fresh one
    // without the override.
    const tokenlessClient = new ViewMagnetClient(
      loadConfig({ apiUrl: `http://127.0.0.1:${api.port}` }),
    );
    await expect(tokenlessClient.get("/x")).rejects.toThrow(
      /No ViewMagnet API token/,
    );
    expect(api.captured).toHaveLength(0);
    void client;
  });

  it("times out when the API hangs longer than requestTimeoutMs", async () => {
    api.reset();
    api.delayMs = 250;
    api.enqueue({ status: 200, body: { ok: true } });
    const client = makeClient({ timeoutMs: 50 });
    try {
      await client.get("/slow");
      expect.fail("expected timeout");
    } catch (err) {
      expect(err).toBeInstanceOf(ViewMagnetApiError);
      const e = err as ViewMagnetApiError;
      expect(e.code).toBe("timeout");
      expect(e.status).toBe(504);
    }
  });
});
