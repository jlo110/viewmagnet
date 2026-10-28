/**
 * Global render notification surface (Week 8).
 *
 * Mounted once at the top of the dashboard layout so toasts fire even
 * when the user is on a page that isn't the render's source (e.g. they
 * trigger a project render, navigate to Distribution Hub, and the
 * "Render finished" toast still appears there).
 *
 * Implementation:
 *
 *   - Subscribes to the full live event store (``useRenderEventSnapshot``)
 *     so it sees every event, including terminal ones, without
 *     polling.
 *   - Diff-detects per-render status transitions, so a single
 *     completion toasts exactly once even if the event store re-emits
 *     the same event on remount.
 *   - Uses ``sonner`` toasts so the visual treatment matches the rest
 *     of the app.
 *
 * The notifier fires three kinds of toasts:
 *
 *   1. **Started** — first time we see a render in ``queued`` or
 *      ``rendering`` state during this tab session. Confirms the user
 *      that the click "took" even if they navigate away immediately.
 *   2. **Finished** — terminal ``done`` transition. Carries the
 *      download URL in the description.
 *   3. **Failed** — terminal ``failed`` transition with the error
 *      blurb.
 *
 * Dedupe strategy uses ``sessionStorage`` so a started toast doesn't
 * re-fire when the user navigates between dashboard pages (the
 * notifier remounts but the set of already-toasted renders persists
 * for the tab's lifetime).
 */
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import {
  useRenderEventSnapshot,
  type RenderProgressEvent,
} from "@/lib/renderProgress";

type RenderKey = string; // `${kind}:${render_id}`

const STARTED_SET_KEY = "render_notifier__started_toasts";
const TERMINAL_SET_KEY = "render_notifier__terminal_toasts";

function loadKeySet(storageKey: string): Set<RenderKey> {
  try {
    const raw = window.sessionStorage.getItem(storageKey);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed as RenderKey[]);
  } catch {
    return new Set();
  }
}

function persistKeySet(storageKey: string, set: Set<RenderKey>): void {
  try {
    window.sessionStorage.setItem(storageKey, JSON.stringify([...set]));
  } catch {
    // sessionStorage quota / disabled → dedup falls back to the ref
    // only. Acceptable: at worst we get an extra toast on navigation.
  }
}

export function RenderNotifier() {
  const snapshot = useRenderEventSnapshot();
  const startedToasted = useRef<Set<RenderKey>>(loadKeySet(STARTED_SET_KEY));
  const terminalToasted = useRef<Set<RenderKey>>(loadKeySet(TERMINAL_SET_KEY));

  useEffect(() => {
    let startedChanged = false;
    let terminalChanged = false;

    for (const event of snapshot) {
      const key: RenderKey = `${event.kind}:${event.render_id}`;
      const noun = event.kind === "project" ? "Project" : "Clip";

      // Terminal transitions — dedupe via a separate set so a render
      // toasted "started" still gets the "finished" toast later.
      if (event.status === "done" || event.status === "failed") {
        if (terminalToasted.current.has(key)) continue;
        terminalToasted.current.add(key);
        terminalChanged = true;
        // Clear the started flag so a retry of THIS render fires a
        // fresh "queued" toast next time. (Render ids are reused on
        // retry — same EditSession/StudioProject row.)
        if (startedToasted.current.delete(key)) startedChanged = true;
        if (event.status === "done") {
          toast.success(`${noun} render finished`, {
            description: event.download_url ?? undefined,
          });
        } else {
          toast.error(`${noun} render failed`, {
            description: event.error ?? "Open the editor and retry.",
          });
        }
        continue;
      }

      // In-flight start — fire exactly once per render per tab session.
      if (event.status === "queued" || event.status === "rendering") {
        if (startedToasted.current.has(key)) continue;
        startedToasted.current.add(key);
        startedChanged = true;
        toast(`${noun} render queued`, {
          description: "We'll let you know when it's ready.",
        });
      }
    }

    if (startedChanged) persistKeySet(STARTED_SET_KEY, startedToasted.current);
    if (terminalChanged) {
      persistKeySet(TERMINAL_SET_KEY, terminalToasted.current);
    }
  }, [snapshot]);

  return null;
}
