/**
 * Tool-registration smoke tests.
 *
 * We don't mount a real MCP transport; instead we build the server,
 * pull the tools out via the SDK's internal registry, then invoke
 * each callback directly. This catches:
 *
 * - missing tool registrations
 * - wrong HTTP method / path
 * - schema definitions that don't match what the tool callback uses
 *
 * For body assertions we still talk to the in-process mock API from
 * client.test.ts so any wiring error shows up as a 404 or a mismatched
 * captured body.
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import { buildServer } from "../src/server.js";
import { loadConfig } from "../src/config.js";

interface Captured {
  method: string;
  path: string;
  body: string;
}

let server: Server;
let port = 0;
const captured: Captured[] = [];
const responses: { status: number; body: unknown }[] = [];

beforeAll(async () => {
  server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      captured.push({
        method: req.method ?? "",
        path: req.url ?? "",
        body: Buffer.concat(chunks).toString("utf8"),
      });
      const queued = responses.shift() ?? { status: 200, body: {} };
      res.statusCode = queued.status;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(queued.body));
    });
  });
  await new Promise<void>((resolve) =>
    server.listen(0, "127.0.0.1", () => resolve()),
  );
  port = (server.address() as AddressInfo).port;
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

function freshServer() {
  responses.length = 0;
  captured.length = 0;
  return buildServer(
    loadConfig({
      apiUrl: `http://127.0.0.1:${port}`,
      patToken: "vm_pat_deadbeef_" + "a".repeat(32),
    }),
  );
}

interface RegisteredTool {
  description?: string;
  handler: (
    args: Record<string, unknown>,
  ) => Promise<{ content: { type: string; text: string }[] }>;
}

/**
 * The SDK stores registered tools on `McpServer._registeredTools` —
 * a plain object keyed by tool name. Each value carries `description`
 * and `handler` (the wrapped invoker that does Zod parsing + executes
 * our callback). Reaching into a private field is the only way to
 * drive tool execution without booting a real client+transport.
 * A regression in this layout is itself worth catching here, so we
 * keep the access narrow rather than hiding it behind any().
 */
function getTools(
  srv: ReturnType<typeof freshServer>,
): Map<string, RegisteredTool> {
  const tools = (srv as unknown as { _registeredTools: unknown })
    ._registeredTools;
  if (tools instanceof Map) {
    return tools as Map<string, RegisteredTool>;
  }
  if (tools && typeof tools === "object") {
    return new Map(
      Object.entries(tools as Record<string, RegisteredTool>),
    );
  }
  throw new Error(
    "Could not find registered tools on McpServer — the SDK internal layout has changed.",
  );
}

describe("MCP tool registry", () => {
  it("registers all 10 v1 tools with viewmagnet_ prefix", () => {
    const tools = getTools(freshServer());
    const names = [...tools.keys()].sort();
    expect(names).toEqual(
      [
        "viewmagnet_analyze_pacing",
        "viewmagnet_analyze_video",
        "viewmagnet_detect_highlights",
        "viewmagnet_generate_script",
        "viewmagnet_generate_titles",
        "viewmagnet_get_outcomes",
        "viewmagnet_list_frameworks",
        "viewmagnet_list_hook_types",
        "viewmagnet_score_hook",
        "viewmagnet_score_title",
      ].sort(),
    );
  });

  it("every tool has a non-trivial description (agent-facing copy)", () => {
    const tools = getTools(freshServer());
    for (const [name, tool] of tools) {
      expect(tool.description, `${name} description`).toBeTruthy();
      expect(tool.description!.length, `${name} description length`).toBeGreaterThan(40);
    }
  });
});

describe("tool → API wiring", () => {
  it("viewmagnet_analyze_video POSTs to /analyze", async () => {
    const srv = freshServer();
    responses.push({ status: 200, body: { video_id: "vid", prediction_score: 88 } });
    const tool = getTools(srv).get("viewmagnet_analyze_video")!;
    const res = await tool.handler({
      url: "https://youtu.be/dQw4w9WgXcQ",
    });
    expect(captured[0].method).toBe("POST");
    expect(captured[0].path).toBe("/analyze");
    expect(JSON.parse(captured[0].body)).toMatchObject({
      url: "https://youtu.be/dQw4w9WgXcQ",
    });
    expect(JSON.parse(res.content[0].text)).toMatchObject({
      video_id: "vid",
      prediction_score: 88,
    });
  });

  it("viewmagnet_list_frameworks GETs /scripts/frameworks", async () => {
    const srv = freshServer();
    responses.push({ status: 200, body: { frameworks: [{ key: "delta_shift" }] } });
    const tool = getTools(srv).get("viewmagnet_list_frameworks")!;
    await tool.handler({});
    expect(captured[0].method).toBe("GET");
    expect(captured[0].path).toBe("/scripts/frameworks");
  });

  it("viewmagnet_generate_script POSTs framework body with defaults", async () => {
    const srv = freshServer();
    responses.push({ status: 200, body: { framework: "delta_shift", full_script: "..." } });
    const tool = getTools(srv).get("viewmagnet_generate_script")!;
    await tool.handler({
      topic: "Why your morning routine is wrong",
      framework: "delta_shift",
    });
    expect(captured[0].path).toBe("/scripts/generate-framework");
    expect(JSON.parse(captured[0].body)).toEqual({
      topic: "Why your morning routine is wrong",
      framework: "delta_shift",
      target_duration: 60,
    });
  });

  it("viewmagnet_score_hook POSTs /hooks/score with the hook text", async () => {
    const srv = freshServer();
    responses.push({ status: 200, body: { overall_score: 72 } });
    const tool = getTools(srv).get("viewmagnet_score_hook")!;
    await tool.handler({ hook: "Most diets are designed to fail. Here's why." });
    expect(captured[0].path).toBe("/hooks/score");
    expect(JSON.parse(captured[0].body)).toEqual({
      hook: "Most diets are designed to fail. Here's why.",
    });
  });

  it("viewmagnet_list_hook_types GETs /hooks/types", async () => {
    const srv = freshServer();
    responses.push({ status: 200, body: { hook_types: [] } });
    const tool = getTools(srv).get("viewmagnet_list_hook_types")!;
    await tool.handler({});
    expect(captured[0].method).toBe("GET");
    expect(captured[0].path).toBe("/hooks/types");
  });

  it("viewmagnet_detect_highlights POSTs /shorts/detect-highlights", async () => {
    const srv = freshServer();
    responses.push({ status: 200, body: { highlights: [] } });
    const tool = getTools(srv).get("viewmagnet_detect_highlights")!;
    await tool.handler({
      video_url: "https://youtu.be/dQw4w9WgXcQ",
      max_highlights: 3,
    });
    expect(captured[0].path).toBe("/shorts/detect-highlights");
    const body = JSON.parse(captured[0].body) as Record<string, unknown>;
    expect(body.video_url).toBe("https://youtu.be/dQw4w9WgXcQ");
    expect(body.max_highlights).toBe(3);
  });

  it("viewmagnet_detect_highlights rejects calls with neither URL nor transcript", async () => {
    const srv = freshServer();
    const tool = getTools(srv).get("viewmagnet_detect_highlights")!;
    await expect(tool.handler({})).rejects.toThrow(/video_url.*transcript/);
  });

  it("viewmagnet_analyze_pacing POSTs /pacing/analyze", async () => {
    const srv = freshServer();
    responses.push({ status: 200, body: { grade: "B+" } });
    const tool = getTools(srv).get("viewmagnet_analyze_pacing")!;
    await tool.handler({ video_url: "https://youtu.be/dQw4w9WgXcQ" });
    expect(captured[0].path).toBe("/pacing/analyze");
    expect(JSON.parse(captured[0].body)).toEqual({
      video_url: "https://youtu.be/dQw4w9WgXcQ",
    });
  });

  it("viewmagnet_score_title POSTs /titles/score with query params", async () => {
    const srv = freshServer();
    responses.push({ status: 200, body: { score: 81 } });
    const tool = getTools(srv).get("viewmagnet_score_title")!;
    await tool.handler({ title: "5 mistakes wrecking your retention", niche: "creator" });
    expect(captured[0].path).toContain("/titles/score?");
    expect(captured[0].path).toContain("title=5%20mistakes");
    expect(captured[0].path).toContain("niche=creator");
  });

  it("viewmagnet_generate_titles POSTs /titles/generate", async () => {
    const srv = freshServer();
    responses.push({ status: 200, body: [] });
    const tool = getTools(srv).get("viewmagnet_generate_titles")!;
    await tool.handler({
      topic: "morning routines",
      niche: "fitness",
      count: 8,
    });
    expect(captured[0].path).toBe("/titles/generate");
    expect(JSON.parse(captured[0].body)).toMatchObject({
      topic: "morning routines",
      niche: "fitness",
      count: 8,
    });
  });

  it("viewmagnet_get_outcomes GETs /distribution/outcomes with limit", async () => {
    const srv = freshServer();
    responses.push({ status: 200, body: { outcomes: [], recommendation_effectiveness: [] } });
    const tool = getTools(srv).get("viewmagnet_get_outcomes")!;
    await tool.handler({ limit: 25 });
    expect(captured[0].method).toBe("GET");
    expect(captured[0].path).toContain("/distribution/outcomes");
    expect(captured[0].path).toContain("limit=25");
  });
});
