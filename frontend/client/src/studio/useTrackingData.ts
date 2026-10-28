/**
 * useTrackingData — React hook that loads + auto-refreshes the multi-subject
 * tracking payload for a Studio session.
 *
 * Behavior:
 * - On mount (and whenever ``clipKey`` or ``n`` changes), fetch /tracking.
 * - If the backend returns ``status: "computing"`` (HTTP 503), retry every
 *   ``retry_after`` seconds (default 2s) until ``status: "done"``.
 * - Returns ``{ data, status, error, progress, refresh }`` so the Camera
 *   panel can show a live progress badge and re-trigger after a clip trim.
 *
 * Parallel to WaveformLane's peaks-fetching loop but extracted here because
 * three different pieces of UI (BBoxOverlay in the preview, CameraLane in
 * the timeline, CameraPanel in the sidebar) all need the same data — and
 * we want them to share a single in-flight request.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { getTracking } from "./api";
import type { TrackingData, TrackingStatus } from "./types";

export type TrackingHookStatus = "idle" | "computing" | "done" | "failed";

export interface UseTrackingDataResult {
  data: TrackingData | null;
  status: TrackingHookStatus;
  error: string | null;
  progress: number | null;
  progressMessage: string | null;
  /** Manually force a fresh fetch (e.g. after the user trims the clip). */
  refresh: () => void;
}

export function useTrackingData(
  clipKey: string | null | undefined,
  n: number = 4,
): UseTrackingDataResult {
  const [data, setData] = useState<TrackingData | null>(null);
  const [status, setStatus] = useState<TrackingHookStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [progressMessage, setProgressMessage] = useState<string | null>(null);

  // Increment this to force the effect below to re-run from the top.
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // Track whether the most recent effect has been cleaned up so a slow
  // response from a stale clipKey can't overwrite the new key's state.
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    if (!clipKey) {
      setData(null);
      setStatus("idle");
      setError(null);
      return;
    }

    let timeoutId: number | null = null;

    async function poll() {
      try {
        const result = await getTracking(clipKey!, n);
        if (cancelledRef.current) return;
        if (result.status === "done") {
          const { status: _s, ...payload } = result;
          setData(payload as TrackingData);
          setStatus("done");
          setError(null);
          setProgress(100);
          setProgressMessage(null);
          return;
        }
        // computing | idle | failed → retry until done or failed-and-give-up.
        const s = result as TrackingStatus;
        if (s.status === "failed") {
          setStatus("failed");
          setError(s.progress_message ?? "Tracking failed");
          setProgress(s.progress ?? null);
          setProgressMessage(s.progress_message ?? null);
          return;
        }
        setStatus("computing");
        setError(null);
        setProgress(s.progress ?? null);
        setProgressMessage(s.progress_message ?? "Queued");
        const wait = Math.max(1, Math.min(10, s.retry_after ?? 2));
        timeoutId = window.setTimeout(poll, wait * 1000);
      } catch (err) {
        if (cancelledRef.current) return;
        const message =
          err instanceof Error ? err.message : "Failed to fetch tracking";
        setStatus("failed");
        setError(message);
      }
    }

    poll();

    return () => {
      cancelledRef.current = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [clipKey, n, tick]);

  return { data, status, error, progress, progressMessage, refresh };
}
