/**
 * Global render-queue surge watcher (Week 8 P3 polish).
 *
 * When an enqueue lands during a backed-up worker spell, the API
 * stamps ``X-Render-Queue-Surge`` ("busy" | "slammed") + the matching
 * ``X-Render-Queue-Wait-Seconds`` integer. The axios interceptor in
 * ``@/lib/api`` fans those headers out as a custom DOM event; this
 * watcher subscribes and shows a single toast describing the
 * expected wait, so a user who just clicked Render isn't left
 * wondering whether their progress bar is broken.
 *
 * Why a global watcher (vs an inline toast on each Render button):
 *
 *   - Render can be triggered from Studio, StudioProject, Drafts,
 *     and the Renders re-run button — duplicating the "queue is
 *     busy" UX across all four would inevitably drift.
 *   - The toast is informational and never blocks the render itself
 *     (the API does NOT short-circuit when the queue is deep); the
 *     watcher's only job is to tell the user honestly.
 *
 * Dedupe contract:
 *
 *   - One toast per surge ``level`` per 60s window per tab. We
 *     remember the last shown level + timestamp in module-local
 *     state so a burst of enqueues (e.g. a user firing off three
 *     renders in a row) doesn't yell three times.
 */
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import {
  RENDER_SURGE_HEADER_EVENT,
  type RenderSurgeHeaderDetail,
} from "@/lib/api";

const REPEAT_WINDOW_MS = 60_000;

function formatWait(seconds: number): string {
  if (seconds < 60) return `~${Math.max(10, seconds)} seconds`;
  const minutes = Math.round(seconds / 60);
  return minutes === 1 ? "~1 minute" : `~${minutes} minutes`;
}

export function RenderSurgeWatcher() {
  // Track the last surge we toasted so a burst doesn't spam. We use
  // a ref (not state) because we never need to re-render in response
  // to changes — the toast itself is the side effect.
  const lastShown = useRef<{ level: string; at: number } | null>(null);

  useEffect(() => {
    const handler = (ev: Event) => {
      const detail = (ev as CustomEvent<RenderSurgeHeaderDetail>).detail;
      if (!detail || (detail.level !== "busy" && detail.level !== "slammed")) {
        return;
      }
      const now = Date.now();
      const last = lastShown.current;
      if (
        last &&
        last.level === detail.level &&
        now - last.at < REPEAT_WINDOW_MS
      ) {
        return;
      }
      lastShown.current = { level: detail.level, at: now };

      const wait = formatWait(detail.estimatedWaitSeconds);
      if (detail.level === "slammed") {
        toast.warning("Renders are backed up", {
          description: `We're slammed right now — your render will start in ${wait}.`,
          duration: 8000,
        });
      } else {
        toast("Queue is busier than usual", {
          description: `Your render should start in ${wait}.`,
          duration: 6000,
        });
      }
    };
    window.addEventListener(RENDER_SURGE_HEADER_EVENT, handler);
    return () =>
      window.removeEventListener(RENDER_SURGE_HEADER_EVENT, handler);
  }, []);

  return null;
}
