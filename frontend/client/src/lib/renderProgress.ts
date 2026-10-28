/**
 * Live render-progress transport (Week 8).
 *
 * Subscribes to ``/ws/renders`` for sub-second per-render updates from
 * the backend's Redis pub/sub channel. Falls back to polling the
 * existing per-render status endpoints when:
 *   - the WebSocket can't open (auth fails / proxy strips upgrade headers)
 *   - the server closes with our "no realtime" code (4408) because
 *     Redis is unavailable
 *   - the connection drops repeatedly (3+ reconnects in 30s)
 *
 * Surface mirrors the existing polling consumers (Studio editor +
 * Project page) so adopting the hook is a drop-in replacement.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import {
  getStoredToken,
  getStudioProjectRenderStatus,
  type StudioProjectRenderStatus,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type RenderKind = "session" | "project";
export type RenderStatus =
  | "idle"
  | "queued"
  | "rendering"
  | "done"
  | "failed";

/** Mirror of the backend's
 *  ``src.queue.progress.publish_progress`` event payload. The WS
 *  endpoint forwards these verbatim. */
export interface RenderProgressEvent {
  kind: RenderKind;
  render_id: number;
  status: RenderStatus;
  percent: number | null;
  message: string | null;
  download_url: string | null;
  error: string | null;
}

/** Key shape used by the in-memory event store so a session and a
 *  project with the same numeric id never collide. */
type EventKey = `${RenderKind}:${number}`;

const keyOf = (kind: RenderKind, id: number): EventKey => `${kind}:${id}`;

// ---------------------------------------------------------------------------
// Transport: a single global WebSocket per browser tab.
// ---------------------------------------------------------------------------

class RenderProgressTransport {
  private socket: WebSocket | null = null;
  private events: Map<EventKey, RenderProgressEvent> = new Map();
  private listeners: Set<() => void> = new Set();
  /** Set when the server closes with 4408 (no realtime), or when 3+
   *  reconnect attempts fail. Consumers check this to fall back to
   *  polling instead of waiting for events that never arrive. */
  private hasGivenUpOnWs = false;
  private reconnectAttempts = 0;
  private reconnectTimer: number | null = null;
  private starting = false;

  // --- public API ------------------------------------------------------

  /** Subscribe to event-store changes; returns an unsubscribe fn. */
  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    this.ensureConnected();
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Get the most recent event for a single render, if any. */
  get(kind: RenderKind, id: number): RenderProgressEvent | undefined {
    return this.events.get(keyOf(kind, id));
  }

  /** Snapshot of every event seen so far. Used by the Renders page
   *  to show the live "in-flight" list without polling. */
  snapshot(): RenderProgressEvent[] {
    return Array.from(this.events.values());
  }

  /** True iff the live-progress channel is unavailable and the UI
   *  should poll instead. */
  shouldPoll(): boolean {
    return this.hasGivenUpOnWs;
  }

  /** Allow external pollers to push an event into the store so
   *  ``useRenderProgressFor`` can read from a single source. */
  ingest(event: RenderProgressEvent): void {
    this.events.set(keyOf(event.kind, event.render_id), event);
    this.notify();
  }

  // --- internals -------------------------------------------------------

  private ensureConnected(): void {
    if (this.socket || this.starting || this.hasGivenUpOnWs) return;
    const token = getStoredToken();
    if (!token) {
      // No token → no socket. We do NOT flag "give up" because the
      // user could log in later; the next subscribe() call will
      // re-attempt the handshake.
      return;
    }
    this.starting = true;
    try {
      const url = this.buildWsUrl(token);
      const socket = new WebSocket(url);
      this.socket = socket;

      socket.addEventListener("open", () => {
        this.starting = false;
        this.reconnectAttempts = 0;
      });

      socket.addEventListener("message", (msg) => {
        try {
          const event: RenderProgressEvent = JSON.parse(msg.data);
          this.events.set(keyOf(event.kind, event.render_id), event);
          this.notify();
        } catch {
          // Garbage frames shouldn't sink the channel; just drop.
        }
      });

      socket.addEventListener("close", (event) => {
        this.starting = false;
        this.socket = null;
        // 4408 = backend told us Redis is unavailable; stop trying.
        // 4401 = unauthenticated; the token is bad, don't reconnect.
        if (event.code === 4408 || event.code === 4401) {
          this.hasGivenUpOnWs = true;
          this.notify();
          return;
        }
        // Normal close from server-side timeout → reconnect with
        // exponential backoff capped at 30s. After 3 failures we
        // give up and let consumers fall back to polling.
        this.reconnectAttempts += 1;
        if (this.reconnectAttempts >= 3) {
          this.hasGivenUpOnWs = true;
          this.notify();
          return;
        }
        const delay = Math.min(30_000, 1_000 * 2 ** this.reconnectAttempts);
        this.reconnectTimer = window.setTimeout(() => {
          this.reconnectTimer = null;
          this.ensureConnected();
        }, delay);
      });

      socket.addEventListener("error", () => {
        // ``close`` fires next; let it handle reconnect logic so we
        // don't double-schedule a reconnect.
      });
    } catch {
      this.starting = false;
      this.hasGivenUpOnWs = true;
      this.notify();
    }
  }

  private buildWsUrl(token: string): string {
    // VITE_API_URL is typically an HTTP(S) URL; mirror it to ws(s).
    // In dev (relative ``/api``) we build the URL off window.location.
    const apiBase = import.meta.env.VITE_API_URL || "/api";
    let httpBase: string;
    if (apiBase.startsWith("http")) {
      httpBase = apiBase;
    } else {
      httpBase = `${window.location.origin}${apiBase}`;
    }
    const wsBase = httpBase.replace(/^http/, "ws").replace(/\/$/, "");
    return `${wsBase}/ws/renders?token=${encodeURIComponent(token)}`;
  }

  private notify(): void {
    this.listeners.forEach((fn) => fn());
  }
}

// One transport per tab (module-level singleton). Avoids opening N
// sockets when N components subscribe to the same channel.
const transport = new RenderProgressTransport();

// ---------------------------------------------------------------------------
// React hooks
// ---------------------------------------------------------------------------

/** Subscribe to live events for a single render. Returns the latest
 *  event for it (or ``undefined`` if none yet) and re-renders the
 *  component when new events arrive.
 *
 *  When the WebSocket transport gave up (no Redis / bad token / 3
 *  failed reconnects), the hook automatically polls
 *  ``/studio/projects/:id/render/status`` every 2s and feeds the
 *  result into the same store. Single-clip polling is the caller's
 *  responsibility (the existing Studio polling code already does it). */
export function useRenderProgressFor(
  kind: RenderKind,
  renderId: number | null,
): RenderProgressEvent | undefined {
  const [event, setEvent] = useState<RenderProgressEvent | undefined>(() =>
    renderId !== null ? transport.get(kind, renderId) : undefined,
  );

  useEffect(() => {
    if (renderId === null) return;
    const sync = () => setEvent(transport.get(kind, renderId));
    const unsub = transport.subscribe(sync);
    sync();
    return unsub;
  }, [kind, renderId]);

  // Polling fallback for projects when the WS gave up. Skip the
  // poll entirely once the render is terminal — the row is done and
  // future ticks would hammer the API for an unchanged answer.
  const isTerminal = event?.status === "done" || event?.status === "failed";
  useEffect(() => {
    if (renderId === null || kind !== "project") return;
    if (!transport.shouldPoll()) return;
    if (isTerminal) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const status: StudioProjectRenderStatus =
          await getStudioProjectRenderStatus(renderId);
        if (cancelled) return;
        transport.ingest({
          kind: "project",
          render_id: renderId,
          status: status.status,
          percent: status.progress ?? null,
          message: status.progress_message ?? null,
          download_url: status.last_render_url ?? null,
          error: null,
        });
      } catch {
        // Ignore — next tick will retry.
      }
    };
    tick();
    const handle = window.setInterval(tick, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [kind, renderId, isTerminal]);

  return event;
}

/** Subscribe to every active render across the user (in-flight list
 *  for the Renders page sidebar count + dashboard surface). */
export function useAllRenderProgress(): RenderProgressEvent[] {
  const [snapshot, setSnapshot] = useState<RenderProgressEvent[]>(() =>
    transport.snapshot(),
  );
  useEffect(() => {
    const sync = () => setSnapshot(transport.snapshot());
    const unsub = transport.subscribe(sync);
    sync();
    return unsub;
  }, []);
  return useMemo(
    () => snapshot.filter((e) => e.status === "queued" || e.status === "rendering"),
    [snapshot],
  );
}

/** Subscribe to the FULL event store, including terminal events.
 *  Used by the global ``<RenderNotifier />`` to detect transitions
 *  (queued → done, rendering → failed, …) so it can toast once per
 *  transition regardless of which page the user is currently on. */
export function useRenderEventSnapshot(): RenderProgressEvent[] {
  const [snapshot, setSnapshot] = useState<RenderProgressEvent[]>(() =>
    transport.snapshot(),
  );
  useEffect(() => {
    const sync = () => setSnapshot(transport.snapshot());
    const unsub = transport.subscribe(sync);
    sync();
    return unsub;
  }, []);
  return snapshot;
}

/** Manually push an event into the store. Used by render-trigger
 *  buttons so the UI updates immediately on enqueue, before the
 *  worker's first publish lands. */
export function recordRenderTrigger(
  kind: RenderKind,
  renderId: number,
  status: RenderStatus = "queued",
): void {
  transport.ingest({
    kind,
    render_id: renderId,
    status,
    percent: 0,
    message: status === "queued" ? "Queued" : null,
    download_url: null,
    error: null,
  });
}

/** True when the WebSocket transport is healthy (live updates),
 *  false when we've fallen back to polling (Redis down / token bad
 *  / 3+ reconnect failures). Exposed so the UI can show a small
 *  "Live" vs "Polling" indicator next to the progress bar so users
 *  understand why their updates feel slower in degraded mode.
 *
 *  The transport's give-up state is set asynchronously (on a
 *  ``close`` event), so we subscribe to the same change-stream the
 *  event hooks use to pick up the transition without a poll. */
export function useIsLive(): boolean {
  const [isLive, setIsLive] = useState<boolean>(() => !transport.shouldPoll());
  useEffect(() => {
    const sync = () => setIsLive(!transport.shouldPoll());
    const unsub = transport.subscribe(sync);
    sync();
    return unsub;
  }, []);
  return isLive;
}

// Test-only escape hatch — let unit tests drive the transport
// without a real WebSocket.
export const _transportForTests = transport;

// ---------------------------------------------------------------------------
// 402 render_budget_exceeded helper
// ---------------------------------------------------------------------------

/** Payload the API returns inside ``detail`` when the render-minute
 *  budget pre-check rejects a render. Mirrored from
 *  ``src/api/routers/studio.py`` + ``src/api/routers/projects.py``. */
export interface RenderBudgetExceededDetail {
  error: "render_budget_exceeded";
  message: string;
  minutes_used: number;
  minutes_limit: number;
  minutes_remaining: number;
  projected_minutes: number;
}

/** Pull a structured budget-exceeded payload off an axios-style error.
 *  Returns ``null`` when the error is anything else, so callers can
 *  fall through to their generic error handler with one branch.
 *
 *  Tolerates both shapes of the error envelope the backend may
 *  emit:
 *    - Legacy: ``{ detail: { error: "render_budget_exceeded", ... } }``
 *    - Wrapped (current): ``{ error: { code: "payment_required",
 *        details: { error: "render_budget_exceeded", ... } } }``
 */
export function asRenderBudgetExceeded(
  err: unknown,
): RenderBudgetExceededDetail | null {
  if (!err || typeof err !== "object") return null;
  const response = (err as { response?: { status?: number; data?: unknown } })
    .response;
  if (!response || response.status !== 402) return null;
  const data = response.data as
    | { detail?: unknown; error?: { details?: unknown } }
    | undefined;
  // Prefer the wrapped envelope (current production shape).
  const wrappedDetails = data?.error?.details as
    | { error?: string }
    | undefined;
  if (
    wrappedDetails &&
    wrappedDetails.error === "render_budget_exceeded"
  ) {
    return wrappedDetails as RenderBudgetExceededDetail;
  }
  // Fall back to the unwrapped legacy shape.
  const detail = data?.detail as { error?: string } | undefined;
  if (detail && detail.error === "render_budget_exceeded") {
    return detail as RenderBudgetExceededDetail;
  }
  return null;
}
