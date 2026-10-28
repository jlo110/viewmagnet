/**
 * Shared tool helpers.
 *
 * Every ViewMagnet tool returns its result as a single JSON-stringified
 * text block. We prefer JSON-as-text over the SDK's structured
 * `resource` content type because:
 *
 * 1. Agents reading JSON-as-text reason about it more reliably (the
 *    raw shape is right there in the assistant's context).
 * 2. It keeps tool implementations dead simple — no schema versioning
 *    for resource URIs, no out-of-band fetch dance.
 * 3. The MCP UIs (Claude Desktop, Cursor) render text-mode tool output
 *    in a collapsed block so the user can expand it on demand without
 *    the agent having to summarize.
 *
 * Errors thrown from a tool callback are caught by the SDK and surfaced
 * to the agent as an `isError: true` content block, so we don't have to
 * format them specially — just let `ViewMagnetApiError` propagate.
 */
import type { ViewMagnetClient } from "../client.js";

export interface ToolDeps {
  client: ViewMagnetClient;
}

/**
 * MCP tool callback return shape. We include the `[k: string]: unknown`
 * index signature because the SDK's tool-callback overload expects an
 * indexable result (it carries a `_meta` slot we don't populate). The
 * `as const` plus the explicit `content` literal narrow it back to
 * something useful at call sites.
 */
export type ToolTextResult = {
  content: { type: "text"; text: string }[];
  isError?: boolean;
  [k: string]: unknown;
};

/** Stable JSON-as-text rendering. Pretty-printed with 2 spaces so a
 * human reading the agent's transcript can scan it. */
export function asJsonText(payload: unknown): ToolTextResult {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(payload, null, 2),
      },
    ],
  };
}
