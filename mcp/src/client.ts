/**
 * Thin authenticated HTTP wrapper around the ViewMagnet REST API.
 *
 * Each tool calls one method on this client, which:
 * - attaches the PAT as a Bearer credential
 * - sets a request timeout (agents that hang look broken)
 * - normalizes the backend's error envelope into a single
 *   `ViewMagnetApiError` so tools can return a clean message to the
 *   agent instead of leaking implementation details
 *
 * The backend wraps errors in:
 *   { "error": { "code": "...", "message": "...", "details": {...} } }
 * so we lift `error.message` into the thrown error's `.message` and
 * keep the rest available on `.details` for tools that want to surface
 * structured info (e.g. quota_exceeded payloads).
 */
import type { RuntimeConfig } from "./config.js";

export class ViewMagnetApiError extends Error {
  override readonly name = "ViewMagnetApiError";
  readonly status: number;
  readonly code: string | null;
  readonly details: Record<string, unknown> | null;
  readonly requestId: string | null;

  constructor(
    status: number,
    message: string,
    code: string | null = null,
    details: Record<string, unknown> | null = null,
    requestId: string | null = null,
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export class ViewMagnetClient {
  constructor(private readonly cfg: RuntimeConfig) {}

  async get<T>(path: string, query?: Record<string, unknown>): Promise<T> {
    return this.request<T>("GET", path, undefined, query);
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("POST", path, body);
  }

  async delete<T>(path: string): Promise<T> {
    return this.request<T>("DELETE", path);
  }

  private async request<T>(
    method: "GET" | "POST" | "DELETE",
    path: string,
    body?: unknown,
    query?: Record<string, unknown>,
  ): Promise<T> {
    if (!this.cfg.patToken) {
      throw new ViewMagnetApiError(
        401,
        "No ViewMagnet API token configured. Generate one at " +
          "https://viewmagnet.com/dashboard/api-tokens and set VM_PAT_TOKEN " +
          "in your MCP server config.",
        "missing_token",
      );
    }

    const url = this.buildUrl(path, query);
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(),
      this.cfg.requestTimeoutMs,
    );

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers: {
          Authorization: `Bearer ${this.cfg.patToken}`,
          "Content-Type": "application/json",
          Accept: "application/json",
          "User-Agent": this.cfg.userAgent,
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      clearTimeout(timer);
      // `AbortError` surfaces as a DOMException on modern Node; fall
      // back to a name check so the message is helpful regardless of
      // which runtime is running us.
      if (err instanceof Error && err.name === "AbortError") {
        throw new ViewMagnetApiError(
          504,
          `ViewMagnet API did not respond within ${
            this.cfg.requestTimeoutMs
          }ms. The request was cancelled.`,
          "timeout",
        );
      }
      throw new ViewMagnetApiError(
        0,
        `Could not reach ViewMagnet API (${this.cfg.apiUrl}): ${
          err instanceof Error ? err.message : String(err)
        }`,
        "network_error",
      );
    } finally {
      clearTimeout(timer);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    const text = await response.text();
    const parsed = safeJsonParse(text);

    if (!response.ok) {
      throw normalizeError(response.status, parsed, text);
    }

    return parsed as T;
  }

  private buildUrl(path: string, query?: Record<string, unknown>): string {
    const trimmed = path.startsWith("/") ? path : `/${path}`;
    const base = `${this.cfg.apiUrl}${trimmed}`;
    if (!query) return base;
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue;
      qs.append(key, String(value));
    }
    const tail = qs.toString();
    return tail ? `${base}?${tail}` : base;
  }
}

function safeJsonParse(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

/**
 * Turn the backend's `{ error: { code, message, details, request_id }}`
 * envelope (or a plain `{ detail: "..." }` from FastAPI's default
 * handler) into a `ViewMagnetApiError` with a useful message.
 */
function normalizeError(status: number, parsed: unknown, raw: string): Error {
  if (parsed && typeof parsed === "object") {
    const obj = parsed as Record<string, unknown>;
    const envelope = obj.error;
    if (envelope && typeof envelope === "object") {
      const env = envelope as Record<string, unknown>;
      return new ViewMagnetApiError(
        status,
        typeof env.message === "string"
          ? env.message
          : `ViewMagnet API returned ${status}`,
        typeof env.code === "string" ? env.code : null,
        (env.details as Record<string, unknown> | undefined) ?? null,
        typeof env.request_id === "string" ? env.request_id : null,
      );
    }
    if (typeof obj.detail === "string") {
      return new ViewMagnetApiError(status, obj.detail);
    }
  }
  return new ViewMagnetApiError(
    status,
    raw ? raw.slice(0, 400) : `ViewMagnet API returned ${status}`,
  );
}
