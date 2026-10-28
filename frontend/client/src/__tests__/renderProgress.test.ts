/**
 * Tests for lib/renderProgress.ts
 *
 * Covers:
 *   - RenderProgressTransport: event ingestion, snapshot, subscription,
 *     get(), shouldPoll(), keyOf collision avoidance (session vs project).
 *   - recordRenderTrigger: pushes correct event shape.
 *   - asRenderBudgetExceeded: 402 error envelope parsing (both shapes).
 *   - keyOf namespacing: session:1 and project:1 are distinct keys.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  _transportForTests,
  recordRenderTrigger,
  asRenderBudgetExceeded,
  type RenderProgressEvent,
} from "../lib/renderProgress";

// We manipulate the singleton transport directly via the test escape hatch.
const transport = _transportForTests;

// Reset transport state between tests via the public API only
// (ingest clears nothing, so we prime fresh events each test).

beforeEach(() => {
  // Clear internal maps via direct access if possible, otherwise use the
  // test-escape-hatch reference.
  // @ts-expect-error — private field access for testing
  transport.events.clear();
  // @ts-expect-error
  transport.hasGivenUpOnWs = false;
  // @ts-expect-error
  transport.reconnectAttempts = 0;
});

// ---------------------------------------------------------------------------
// keyOf namespacing
// ---------------------------------------------------------------------------

describe("transport event store", () => {
  it("stores and retrieves a session event", () => {
    const event: RenderProgressEvent = {
      kind: "session",
      render_id: 1,
      status: "rendering",
      percent: 42,
      message: "Encoding",
      download_url: null,
      error: null,
    };
    transport.ingest(event);
    const stored = transport.get("session", 1);
    expect(stored).toBeDefined();
    expect(stored?.percent).toBe(42);
  });

  it("session:1 and project:1 are stored independently", () => {
    const sessionEvent: RenderProgressEvent = {
      kind: "session", render_id: 1, status: "done",
      percent: 100, message: null, download_url: "https://cdn/video.mp4", error: null,
    };
    const projectEvent: RenderProgressEvent = {
      kind: "project", render_id: 1, status: "rendering",
      percent: 50, message: null, download_url: null, error: null,
    };
    transport.ingest(sessionEvent);
    transport.ingest(projectEvent);

    expect(transport.get("session", 1)?.status).toBe("done");
    expect(transport.get("project", 1)?.status).toBe("rendering");
  });

  it("later ingest overwrites earlier event for same key", () => {
    const e1: RenderProgressEvent = { kind: "project", render_id: 5, status: "queued", percent: 0, message: null, download_url: null, error: null };
    const e2: RenderProgressEvent = { kind: "project", render_id: 5, status: "done", percent: 100, message: null, download_url: "https://x/v.mp4", error: null };
    transport.ingest(e1);
    transport.ingest(e2);
    expect(transport.get("project", 5)?.status).toBe("done");
  });

  it("snapshot includes all ingested events", () => {
    transport.ingest({ kind: "session", render_id: 10, status: "queued", percent: 0, message: null, download_url: null, error: null });
    transport.ingest({ kind: "project", render_id: 20, status: "rendering", percent: 30, message: null, download_url: null, error: null });
    const snap = transport.snapshot();
    expect(snap.length).toBeGreaterThanOrEqual(2);
  });

  it("get returns undefined for unknown key", () => {
    expect(transport.get("session", 999)).toBeUndefined();
  });

  it("notifies subscribers on ingest", () => {
    const listener = vi.fn();
    const unsub = transport.subscribe(listener);
    transport.ingest({ kind: "session", render_id: 7, status: "done", percent: 100, message: null, download_url: null, error: null });
    expect(listener).toHaveBeenCalled();
    unsub();
  });

  it("unsubscribed listener is not called after unsub", () => {
    const listener = vi.fn();
    const unsub = transport.subscribe(listener);
    unsub();
    listener.mockClear();
    transport.ingest({ kind: "session", render_id: 8, status: "done", percent: 100, message: null, download_url: null, error: null });
    expect(listener).not.toHaveBeenCalled();
  });

  it("shouldPoll returns false initially", () => {
    expect(transport.shouldPoll()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// recordRenderTrigger
// ---------------------------------------------------------------------------

describe("recordRenderTrigger", () => {
  it("pushes a queued event with percent 0", () => {
    recordRenderTrigger("project", 42);
    const ev = transport.get("project", 42);
    expect(ev?.status).toBe("queued");
    expect(ev?.percent).toBe(0);
    expect(ev?.message).toBe("Queued");
  });

  it("accepts custom status", () => {
    recordRenderTrigger("session", 99, "rendering");
    expect(transport.get("session", 99)?.status).toBe("rendering");
  });
});

// ---------------------------------------------------------------------------
// asRenderBudgetExceeded
// ---------------------------------------------------------------------------

describe("asRenderBudgetExceeded", () => {
  const detail = {
    error: "render_budget_exceeded",
    message: "You have used all 30 minutes",
    minutes_used: 30,
    minutes_limit: 30,
    minutes_remaining: 0,
    projected_minutes: 1.5,
  };

  it("returns null for non-402 errors", () => {
    const err = { response: { status: 403, data: {} } };
    expect(asRenderBudgetExceeded(err)).toBeNull();
  });

  it("returns null for non-error objects", () => {
    expect(asRenderBudgetExceeded(null)).toBeNull();
    expect(asRenderBudgetExceeded("string")).toBeNull();
  });

  it("parses legacy detail shape", () => {
    const err = { response: { status: 402, data: { detail } } };
    const result = asRenderBudgetExceeded(err);
    expect(result).not.toBeNull();
    expect(result?.error).toBe("render_budget_exceeded");
    expect(result?.minutes_remaining).toBe(0);
  });

  it("parses wrapped envelope shape", () => {
    const err = {
      response: {
        status: 402,
        data: { error: { code: "payment_required", details: detail } },
      },
    };
    const result = asRenderBudgetExceeded(err);
    expect(result).not.toBeNull();
    expect(result?.projected_minutes).toBe(1.5);
  });

  it("prefers wrapped envelope over legacy shape", () => {
    const err = {
      response: {
        status: 402,
        data: {
          detail: { ...detail, minutes_remaining: 99 },
          error: { code: "payment_required", details: { ...detail, minutes_remaining: 0 } },
        },
      },
    };
    const result = asRenderBudgetExceeded(err);
    expect(result?.minutes_remaining).toBe(0);
  });

  it("returns null when 402 but error field is not render_budget_exceeded", () => {
    const err = { response: { status: 402, data: { detail: { error: "other_error" } } } };
    expect(asRenderBudgetExceeded(err)).toBeNull();
  });
});
