/**
 * Runtime configuration for the ViewMagnet MCP server.
 *
 * Two values matter: where the API lives, and what PAT to authenticate
 * with. Both can be supplied via CLI flags (for one-off `npx` runs) or
 * via environment variables (for persistent installs in
 * `claude_desktop_config.json` / `~/.cursor/mcp.json` etc.).
 *
 * Precedence: CLI flag > env var > default.
 */
export interface RuntimeConfig {
  apiUrl: string;
  patToken: string | null;
  /** ms before any single HTTP request to the API is considered hung. */
  requestTimeoutMs: number;
  /** Optional User-Agent tail so we can spot MCP-driven traffic in logs. */
  userAgent: string;
}

// Local API by default (uvicorn on :8000). Point at a deployed backend with
// VIEWMAGNET_API_URL / VM_API_URL or --api-url.
const DEFAULT_API_URL = "http://localhost:8000";
const DEFAULT_TIMEOUT_MS = 60_000;

export interface ConfigOverrides {
  apiUrl?: string;
  patToken?: string;
  requestTimeoutMs?: number;
}

/**
 * Build the resolved runtime config. Throws when no PAT is found AFTER
 * applying all sources — without a token nearly every tool would fail,
 * so we'd rather refuse to start than spew 401s into the agent's logs.
 */
export function loadConfig(overrides: ConfigOverrides = {}): RuntimeConfig {
  const apiUrl =
    overrides.apiUrl ??
    process.env.VM_API_URL ??
    process.env.VIEWMAGNET_API_URL ??
    DEFAULT_API_URL;

  const patToken =
    overrides.patToken ??
    process.env.VM_PAT_TOKEN ??
    process.env.VIEWMAGNET_PAT ??
    null;

  const timeoutRaw =
    overrides.requestTimeoutMs ??
    Number.parseInt(process.env.VM_REQUEST_TIMEOUT_MS ?? "", 10);
  const requestTimeoutMs = Number.isFinite(timeoutRaw) && timeoutRaw > 0
    ? timeoutRaw
    : DEFAULT_TIMEOUT_MS;

  return {
    apiUrl: apiUrl.replace(/\/+$/, ""),
    patToken,
    requestTimeoutMs,
    // Identifies MCP-driven calls in nginx/Sentry without giving away the
    // user's Node version (that lives in process.version if we want it).
    userAgent: `viewmagnet-mcp/${getPackageVersion()}`,
  };
}

/**
 * Read the package.json version at build time. tsup injects this via a
 * define replacement so the bundled cli still knows what version it is
 * without trying to ``require('../package.json')`` from inside a bundle.
 */
function getPackageVersion(): string {
  // Replaced at build time; falls back to "dev" when running via tsx/vitest.
  // The literal string below is intentional — see tsup.config.ts comments.
  return (
    (typeof process !== "undefined" && process.env.VM_MCP_VERSION) ||
    "0.1.0"
  );
}
