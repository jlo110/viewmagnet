/**
 * useEditSession — loads a Studio edit session by clip key and gives the
 * caller a "spec + setSpec" pair that automatically debounce-persists changes
 * to the backend.
 *
 * Week 2 additions:
 *   - Coalesced undo/redo history. A drag gesture generates ONE history
 *     entry (not 60) thanks to ``beginInteraction`` + a 500ms coalescing
 *     window for non-interactive edits.
 *   - Live render progress polling. After `render()` fires, we poll
 *     /studio/render/{id}/status every 1500ms until the job is terminal
 *     and expose ``renderProgress`` so the UI can show a real progress bar.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  clearPendingCta,
  readPendingCta,
} from "@/lib/deepLinks";

import { getRenderStatus, getSession, renderSession as apiRender, saveSession } from "./api";
import {
  DEMO_END,
  DEMO_SOURCE_URL,
  DEMO_START,
  DEMO_TRANSCRIPT,
} from "./demoSource";
import {
  defaultSpec,
  type EditSession,
  type EditSpec,
  type RenderStatus,
  type SourceClip,
} from "./types";
import {
  recordRenderTrigger,
  useRenderProgressFor,
} from "@/lib/renderProgress";

const SAVE_DEBOUNCE_MS = 800;
const HISTORY_COALESCE_MS = 500;
const HISTORY_LIMIT = 50;
const POLL_INTERVAL_MS = 1500;

// URLs that were valid when a session was first saved but have since started
// returning 403, disappearing, or — in the case of the long W3C copy — not
// playing on Safari because the moov atom is at the end of the file. We
// rewrite them on load so existing sessions keep working without the user
// having to start over. The debounced auto-save then persists the fix back
// to the row.
//
// Every legacy entry here was authored with the original Big Buck Bunny
// demo transcript (which only ran ~6s). Since the source clip is being
// swapped out from under the user, we also swap the transcript so the
// captions actually match the audio.
const LEGACY_DEMO_URLS = new Set([
  "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
  "https://storage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
  "https://media.w3.org/2010/05/bunny/movie.mp4",
  "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_30MB.mp4",
  "https://videos.pexels.com/video-files/853889/853889-hd_1280_720_25fps.mp4",
]);

/**
 * Pull legacy sessions forward to the current demo clip. Replaces the
 * source URL, clamps the window, and (since the legacy clips all had a
 * short bunny transcript that no longer matches the audio) installs the
 * current demo transcript. Anything outside ``clip`` — captions style,
 * camera tracks, B-roll, brand — is preserved.
 */
function migrateLegacyUrls(spec: EditSpec): EditSpec {
  if (!LEGACY_DEMO_URLS.has(spec.clip.source_url)) return spec;
  return {
    ...spec,
    clip: {
      ...spec.clip,
      source_url: DEMO_SOURCE_URL,
      start_time: DEMO_START,
      end_time: DEMO_END,
      transcript: DEMO_TRANSCRIPT,
    },
  };
}

/**
 * Patch in the current demo transcript for sessions that are already on
 * the new demo URL but were saved with the prior (shorter, ~6s) transcript.
 * Only runs when the spec is unmistakably the demo session — same URL,
 * same window, and a transcript whose last word lands well before the
 * clip's end. We don't want to clobber a user who genuinely trimmed their
 * own narration.
 */
function migrateDemoTranscript(spec: EditSpec): EditSpec {
  if (spec.clip.source_url !== DEMO_SOURCE_URL) return spec;
  if (spec.clip.start_time !== DEMO_START || spec.clip.end_time !== DEMO_END) {
    return spec;
  }
  const words = spec.clip.transcript ?? [];
  if (words.length === 0) return spec;
  const lastEnd = words[words.length - 1]?.end ?? 0;
  // If the existing transcript already covers most of the clip, leave it
  // alone — the user may have hand-edited it.
  const clipDuration = DEMO_END - DEMO_START;
  if (lastEnd >= clipDuration - 2) return spec;
  return {
    ...spec,
    clip: { ...spec.clip, transcript: DEMO_TRANSCRIPT },
  };
}

export type SaveState = "idle" | "saving" | "saved" | "error";

export interface RenderProgress {
  status: RenderStatus["status"];
  percent: number | null;
  message: string | null;
  url: string | null;
  error: string | null;
}

export interface UseEditSession {
  loading: boolean;
  error: string | null;
  session: EditSession | null;
  spec: EditSpec | null;
  setSpec: (next: EditSpec) => void;
  updateSpec: (mutator: (draft: EditSpec) => void) => void;
  saveState: SaveState;
  render: () => Promise<RenderStatus | null>;
  rendering: boolean;
  renderUrl: string | null;
  renderError: string | null;
  renderProgress: RenderProgress;
  /** Snapshot the current spec for undo. Call once at the start of a drag
   *  or any other multi-tick interaction. */
  beginInteraction: () => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

interface UseEditSessionArgs {
  clipKey: string;
  fallbackClip: SourceClip | null;
  fallbackTitle?: string;
}

interface HistoryRef {
  past: EditSpec[];
  future: EditSpec[];
  lastPushAt: number;
  /** True while inside a beginInteraction()..pointerup window. We push
   *  exactly one snapshot per interaction regardless of how many updateSpec
   *  calls happen inside it. */
  interacting: boolean;
}

export function useEditSession({
  clipKey,
  fallbackClip,
  fallbackTitle,
}: UseEditSessionArgs): UseEditSession {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<EditSession | null>(null);
  const [spec, setSpec] = useState<EditSpec | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [rendering, setRendering] = useState(false);
  const [renderUrl, setRenderUrl] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [renderProgress, setRenderProgress] = useState<RenderProgress>({
    status: "idle",
    percent: null,
    message: null,
    url: null,
    error: null,
  });
  const [historyTick, setHistoryTick] = useState(0); // triggers canUndo/canRedo recompute

  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedJson = useRef<string | null>(null);
  const initialLoadDone = useRef(false);
  const history = useRef<HistoryRef>({
    past: [],
    future: [],
    lastPushAt: 0,
    interacting: false,
  });
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollingSessionId = useRef<number | null>(null);

  // ---- Week 8: WebSocket render events --------------------------------
  // Subscribe to live events for the current session id. The 1.5s
  // polling above stays as a safety net for environments where Redis /
  // WS aren't available (the hook gives up after 3 reconnect failures
  // and the existing polling continues to drive progress).
  const liveSessionId = session?.id ?? null;
  const liveEvent = useRenderProgressFor("session", liveSessionId);
  useEffect(() => {
    if (!liveEvent) return;
    setRenderProgress({
      status: liveEvent.status,
      percent: liveEvent.percent ?? null,
      message: liveEvent.message ?? null,
      url: liveEvent.download_url ?? null,
      error: liveEvent.error ?? null,
    });
    if (liveEvent.download_url) setRenderUrl(liveEvent.download_url);
    if (liveEvent.status === "done") {
      setRendering(false);
    } else if (liveEvent.status === "failed") {
      setRendering(false);
      setRenderError(liveEvent.error ?? "Render failed");
    }
  }, [
    liveEvent?.status,
    liveEvent?.percent,
    liveEvent?.message,
    liveEvent?.download_url,
    liveEvent?.error,
  ]);

  // --- initial load --------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    initialLoadDone.current = false;
    history.current = { past: [], future: [], lastPushAt: 0, interacting: false };

    (async () => {
      try {
        const existing = await getSession(clipKey);
        if (cancelled) return;

        if (existing) {
          const migrated = migrateDemoTranscript(migrateLegacyUrls(existing.spec));
          setSession(existing);
          setSpec(migrated);
          setRenderUrl(existing.last_render_url ?? null);
          setRenderError(existing.last_render_error ?? null);
          setRenderProgress({
            status: existing.last_render_status,
            percent: null,
            message: null,
            url: existing.last_render_url ?? null,
            error: existing.last_render_error ?? null,
          });
          // If we rewrote a URL, mark the OLD json as "last saved" so the
          // debounced effect detects a diff and persists the migration.
          lastSavedJson.current = JSON.stringify(existing.spec);
        } else if (fallbackClip) {
          const seed = defaultSpec(fallbackClip);
          setSession(null);
          setSpec(seed);
          lastSavedJson.current = JSON.stringify(seed);
        } else {
          setError("No session and no fallback clip provided");
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load session");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          initialLoadDone.current = true;
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [clipKey, fallbackClip]);

  // --- debounced auto-save ------------------------------------------------
  useEffect(() => {
    if (!spec || !initialLoadDone.current) return;
    const json = JSON.stringify(spec);
    if (json === lastSavedJson.current) return;

    setSaveState("saving");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      // Week 10: pull the pending CTA envelope (if any) right before
      // the save so the FIRST autosave after a deep-link entry
      // ships the originating recommendation. The backend's first-
      // attribution-wins behavior makes it harmless to keep sending
      // until the row has a stored provenance, but we proactively
      // clear once the save succeeds so subsequent debounce ticks
      // don't reload the same envelope.
      const ctaPayload = readPendingCta(clipKey);
      try {
        const saved = await saveSession(clipKey, spec, fallbackTitle, {
          ctaProvenance: ctaPayload,
        });
        lastSavedJson.current = JSON.stringify(saved.spec);
        setSession(saved);
        setSaveState("saved");
        // Successful save with a CTA payload → drop the pending key
        // so a re-edit later doesn't re-attribute against a stale
        // recommendation.
        if (ctaPayload) {
          clearPendingCta(clipKey);
        }
      } catch (err) {
        console.error("[studio] save failed", err);
        setSaveState("error");
      }
    }, SAVE_DEBOUNCE_MS);

    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [spec, clipKey, fallbackTitle]);

  // --- history bookkeeping ------------------------------------------------
  const pushHistory = useCallback((snapshot: EditSpec) => {
    const h = history.current;
    h.past.push(snapshot);
    if (h.past.length > HISTORY_LIMIT) h.past.shift();
    h.future = [];
    h.lastPushAt = Date.now();
    setHistoryTick((t) => t + 1);
  }, []);

  const beginInteraction = useCallback(() => {
    const h = history.current;
    if (h.interacting) return;
    if (!spec) return;
    h.interacting = true;
    pushHistory(JSON.parse(JSON.stringify(spec)));

    // End the interaction on the next pointerup so subsequent updateSpec
    // calls outside this gesture push their own (coalesced) entries.
    const end = () => {
      h.interacting = false;
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  }, [spec, pushHistory]);

  // --- updater that mutates a deep clone (so React sees a new object) ----
  const updateSpec = useCallback(
    (mutator: (draft: EditSpec) => void) => {
      setSpec((prev) => {
        if (!prev) return prev;
        const next: EditSpec = JSON.parse(JSON.stringify(prev));
        mutator(next);

        // Push to history unless we're inside a beginInteraction() window
        // (drag gesture) or within the coalescing time after a previous push.
        const h = history.current;
        const now = Date.now();
        if (!h.interacting && now - h.lastPushAt > HISTORY_COALESCE_MS) {
          h.past.push(prev);
          if (h.past.length > HISTORY_LIMIT) h.past.shift();
          h.future = [];
          h.lastPushAt = now;
          setHistoryTick((t) => t + 1);
        } else if (!h.interacting) {
          // Within coalesce window — just bump the timestamp so a long
          // chain of edits resets the clock.
          h.lastPushAt = now;
        }
        return next;
      });
    },
    [],
  );

  const undo = useCallback(() => {
    const h = history.current;
    if (h.past.length === 0) return;
    setSpec((current) => {
      if (!current) return current;
      const prev = h.past.pop()!;
      h.future.push(current);
      if (h.future.length > HISTORY_LIMIT) h.future.shift();
      setHistoryTick((t) => t + 1);
      return prev;
    });
  }, []);

  const redo = useCallback(() => {
    const h = history.current;
    if (h.future.length === 0) return;
    setSpec((current) => {
      if (!current) return current;
      const next = h.future.pop()!;
      h.past.push(current);
      if (h.past.length > HISTORY_LIMIT) h.past.shift();
      setHistoryTick((t) => t + 1);
      return next;
    });
  }, []);

  // --- render -------------------------------------------------------------
  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
    pollingSessionId.current = null;
  }, []);

  const startPolling = useCallback(
    (sessionId: number) => {
      stopPolling();
      pollingSessionId.current = sessionId;
      pollTimer.current = setInterval(async () => {
        if (pollingSessionId.current !== sessionId) return;
        try {
          const status = await getRenderStatus(sessionId);
          setRenderProgress({
            status: status.status,
            percent: status.progress ?? null,
            message: status.progress_message ?? null,
            url: status.last_render_url ?? null,
            error: null,
          });
          if (status.last_render_url) setRenderUrl(status.last_render_url);
          if (status.status === "done") {
            setRendering(false);
            stopPolling();
          } else if (status.status === "failed") {
            setRendering(false);
            setRenderError("Render failed — check the API logs for details.");
            stopPolling();
          }
        } catch (err) {
          console.warn("[studio] poll failed", err);
        }
      }, POLL_INTERVAL_MS);
    },
    [stopPolling],
  );

  useEffect(() => {
    // Clean up the interval on unmount or clipKey change.
    return () => stopPolling();
  }, [clipKey, stopPolling]);

  const render = useCallback(async () => {
    if (!spec) return null;
    setRendering(true);
    setRenderError(null);
    setRenderProgress({
      status: "queued",
      percent: 0,
      message: "Queued",
      url: null,
      error: null,
    });
    try {
      const status = await apiRender(clipKey, spec, fallbackTitle);
      if (status.last_render_url) setRenderUrl(status.last_render_url);

      setRenderProgress({
        status: status.status,
        percent: status.progress ?? null,
        message: status.progress_message ?? null,
        url: status.last_render_url ?? null,
        error: null,
      });

      // Seed the global render-progress store so any other tab /
      // component (e.g. the Renders tab list) sees this render
      // immediately, before the worker publishes its first event.
      if (status.session_id != null) {
        recordRenderTrigger("session", status.session_id, status.status);
      }

      if (status.status === "failed") {
        setRenderError("Render failed — check the API logs for details.");
        setRendering(false);
      } else if (status.status === "done") {
        // Synchronous fallback path — already finished, no need to poll.
        setRendering(false);
      } else if (status.session_id != null) {
        // Queued/rendering — poll until terminal. WS events (if
        // Redis is reachable) usually arrive first and short-circuit
        // the polling cadence; polling remains the safety net.
        startPolling(status.session_id);
      }
      return status;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Render request failed";
      setRenderError(msg);
      setRendering(false);
      return null;
    }
  }, [clipKey, spec, fallbackTitle, startPolling]);

  return {
    loading,
    error,
    session,
    spec,
    setSpec,
    updateSpec,
    saveState,
    render,
    rendering,
    renderUrl,
    renderError,
    renderProgress,
    beginInteraction,
    undo,
    redo,
    // historyTick forces canUndo/canRedo to recompute on each push/undo/redo
    canUndo: historyTick >= 0 && history.current.past.length > 0,
    canRedo: historyTick >= 0 && history.current.future.length > 0,
  };
}
