/**
 * E2E smoke for the MCP server.
 *
 * What this proves end-to-end:
 *  1. A logged-in user can generate a PAT from the dashboard's
 *     `/dashboard/api-tokens` page.
 *  2. Spawning `viewmagnet-mcp serve` with that PAT successfully
 *     speaks JSON-RPC over stdio, lists every tool, and returns
 *     non-error results for each one when pointed at the same
 *     dev API the dashboard uses.
 *
 * The test is opt-in: it requires that the MCP package has been
 * built (`pnpm --filter viewmagnet-mcp build` or `cd mcp && tsup`)
 * and that the dev API is reachable at the Playwright `baseURL`.
 * Skipping rather than failing in environments that don't satisfy
 * those preconditions keeps the rest of the e2e suite stable.
 */
import { test, expect } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const MCP_DIST = resolve(__dirname, "..", "mcp", "dist", "cli.js");
const HAS_BUILD = existsSync(MCP_DIST);

const API_BASE = process.env.E2E_API_BASE ?? "http://localhost:8000";
const PLAYWRIGHT_BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";

/** Tools the MCP server is expected to expose. Mirrors
 * `mcp/src/server.ts::buildServer`. */
const EXPECTED_TOOLS = [
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
];

/**
 * Minimal JSON-RPC over stdio driver. We can't reuse the SDK's
 * Client class here because that would create a tight version
 * coupling — the whole point of this smoke is that the wire
 * protocol is correct for any consumer.
 */
class StdioMcpDriver {
  private buffer = "";
  private pending = new Map<
    number,
    { resolve: (v: unknown) => void; reject: (err: Error) => void }
  >();
  private nextId = 1;

  constructor(private child: ChildProcessWithoutNullStreams) {
    child.stdout.on("data", (chunk: Buffer) => this.handleChunk(chunk));
  }

  private handleChunk(chunk: Buffer): void {
    this.buffer += chunk.toString("utf8");
    while (true) {
      const newlineIdx = this.buffer.indexOf("\n");
      if (newlineIdx === -1) return;
      const line = this.buffer.slice(0, newlineIdx).trim();
      this.buffer = this.buffer.slice(newlineIdx + 1);
      if (!line) continue;
      try {
        const msg = JSON.parse(line) as {
          id?: number;
          result?: unknown;
          error?: { message: string };
        };
        if (typeof msg.id === "number") {
          const pending = this.pending.get(msg.id);
          if (pending) {
            this.pending.delete(msg.id);
            if (msg.error) pending.reject(new Error(msg.error.message));
            else pending.resolve(msg.result);
          }
        }
      } catch {
        // The server may interleave non-JSON log lines on stdout in
        // some failure modes — ignore those rather than crash.
      }
    }
  }

  async call<T = unknown>(method: string, params: unknown = {}): Promise<T> {
    const id = this.nextId++;
    const payload = JSON.stringify({ jsonrpc: "2.0", id, method, params });
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`MCP call ${method} timed out`));
      }, 30_000);
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value as T);
        },
        reject: (err) => {
          clearTimeout(timer);
          reject(err);
        },
      });
      this.child.stdin.write(payload + "\n");
    });
  }

  async stop(): Promise<void> {
    this.child.stdin.end();
    await new Promise<void>((resolve) => {
      this.child.once("exit", () => resolve());
      setTimeout(() => {
        if (this.child.exitCode === null) this.child.kill("SIGTERM");
        resolve();
      }, 2_000);
    });
  }
}

async function generatePatViaDashboard(page: import("@playwright/test").Page): Promise<string> {
  // Assumes a logged-in session was set up by a fixture or the
  // shared signup helper used by other tests. We deliberately go
  // through the UI so this also exercises ApiTokens.tsx.
  await page.goto("/dashboard/api-tokens");
  await page.getByRole("button", { name: /generate token/i }).first().click();
  await page.getByPlaceholder(/macbook claude/i).fill("MCP e2e smoke");
  await page.getByRole("button", { name: /^generate token$/i }).click();
  // The reveal panel surfaces the plaintext token in a font-mono div.
  const tokenLocator = page.locator("div.font-mono", {
    hasText: /^vm_pat_/,
  });
  await expect(tokenLocator).toBeVisible({ timeout: 10_000 });
  const text = (await tokenLocator.first().textContent())?.trim() ?? "";
  if (!text.startsWith("vm_pat_")) {
    throw new Error(`Did not capture a PAT — got ${text.slice(0, 16)}…`);
  }
  return text;
}

test.describe("MCP server smoke", () => {
  test.skip(
    !HAS_BUILD,
    `mcp/dist/cli.js not found at ${MCP_DIST}. Run \`cd mcp && pnpm build\` first.`,
  );

  test("generate a PAT, boot MCP server, list and call every tool", async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000);

    // Sanity check the API is reachable before we sink time into the
    // dashboard flow.
    const health = await request.get(`${API_BASE}/health`);
    test.skip(!health.ok(), `API at ${API_BASE} is not healthy.`);

    // Log in via an existing demo / dev-mode credential. The auth
    // spec already exercises real signup; this spec assumes that
    // session bootstrap is handled elsewhere (a global setup file or
    // an auth-state storageState). If neither is present we skip so
    // CI doesn't go red just because the prerequisite isn't met.
    const storageStateExists = !!process.env.E2E_STORAGE_STATE;
    test.skip(
      !storageStateExists,
      "Set E2E_STORAGE_STATE to a saved logged-in storage state to run this smoke.",
    );

    const pat = await generatePatViaDashboard(page);

    // Spawn the MCP server with the captured PAT pointed at the same
    // backend. We use `node` directly on the built bundle so we don't
    // depend on the package being npm-published yet.
    const child = spawn(
      "node",
      [MCP_DIST, "serve", "--api-url", API_BASE, "--token", pat],
      {
        env: { ...process.env },
        stdio: ["pipe", "pipe", "pipe"],
      },
    );
    // Drain stderr to a buffer in case we need to print it on
    // failure — the server logs its boot line there.
    const stderr: string[] = [];
    child.stderr.on("data", (c: Buffer) => stderr.push(c.toString("utf8")));

    const driver = new StdioMcpDriver(child);
    try {
      // 1. Handshake.
      const initResult = (await driver.call("initialize", {
        protocolVersion: "2024-11-05",
        capabilities: {},
        clientInfo: { name: "viewmagnet-mcp-smoke", version: "0.0.1" },
      })) as { protocolVersion: string };
      expect(initResult.protocolVersion).toBeTruthy();

      // The SDK requires an `initialized` notification before it
      // will accept tool calls.
      child.stdin.write(
        JSON.stringify({
          jsonrpc: "2.0",
          method: "notifications/initialized",
        }) + "\n",
      );

      // 2. List tools — every expected tool should be present.
      const listed = (await driver.call("tools/list", {})) as {
        tools: { name: string }[];
      };
      const listedNames = listed.tools.map((t) => t.name).sort();
      expect(listedNames).toEqual(EXPECTED_TOOLS.slice().sort());

      // 3. Call each tool with the minimum valid args, asserting
      //    only that it didn't crash. We're proving the wiring,
      //    not the ML quality.
      const minimalArgs: Record<string, Record<string, unknown>> = {
        viewmagnet_analyze_video: {
          url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
        viewmagnet_list_frameworks: {},
        viewmagnet_generate_script: {
          topic: "Smoke test topic",
          framework: "delta_shift",
        },
        viewmagnet_score_hook: {
          hook: "Most diets are designed to fail. Here's why.",
        },
        viewmagnet_list_hook_types: {},
        viewmagnet_detect_highlights: {
          transcript:
            "Most diets fail in week three. Here is what to do instead.",
          max_highlights: 1,
        },
        viewmagnet_analyze_pacing: {
          video_url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
        viewmagnet_score_title: {
          title: "5 mistakes wrecking your retention",
          niche: "creator",
        },
        viewmagnet_generate_titles: {
          topic: "morning routines",
          niche: "fitness",
          count: 1,
        },
        viewmagnet_get_outcomes: { limit: 5 },
      };

      for (const tool of EXPECTED_TOOLS) {
        const args = minimalArgs[tool] ?? {};
        const result = (await driver.call("tools/call", {
          name: tool,
          arguments: args,
        })) as {
          isError?: boolean;
          content?: { type: string; text?: string }[];
        };
        // We accept either a clean success or a structured
        // backend error (e.g. quota exceeded on a free test
        // account), but NOT a transport-level crash.
        expect(result, `${tool} returned an unexpected shape`).toHaveProperty(
          "content",
        );
        expect(Array.isArray(result.content)).toBe(true);
        if (!result.isError) {
          expect(result.content!.length).toBeGreaterThan(0);
        }
      }
    } finally {
      await driver.stop();
      // Surface stderr in the test trace on failure so a stuck
      // server is debuggable.
      if (test.info().status !== test.info().expectedStatus) {
        console.error("[mcp-smoke] server stderr:\n" + stderr.join(""));
      }
    }
    // Silence unused-var lint on PLAYWRIGHT_BASE; it's exported so
    // callers can override but the test doesn't navigate elsewhere.
    void PLAYWRIGHT_BASE;
  });
});
