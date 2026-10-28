/**
 * Global soft-cap watcher (Week 8 hybrid Pro gating).
 *
 * The backend stamps ``X-Render-Softcap`` on free-plan render
 * enqueues that exceed the "polite" thresholds (currently: output
 * duration > 2 minutes). The render still proceeds; this watcher
 * surfaces the upgrade modal once per tab session per reason so the
 * user sees the upsell without being interrupted on every click.
 *
 * Dedupe keys live in ``sessionStorage`` so navigating between
 * dashboard pages doesn't re-open the modal repeatedly for the same
 * underlying render hit.
 */
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import {
  RENDER_SOFTCAP_HEADER_EVENT,
} from "@/lib/api";
import { useUpgrade } from "@/contexts/UpgradeContext";

const SHOWN_KEY = "render_softcap__shown_reasons";

function loadShown(): Set<string> {
  try {
    const raw = window.sessionStorage.getItem(SHOWN_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? new Set(parsed as string[]) : new Set();
  } catch {
    return new Set();
  }
}

function persistShown(set: Set<string>): void {
  try {
    window.sessionStorage.setItem(SHOWN_KEY, JSON.stringify([...set]));
  } catch {
    // sessionStorage disabled — at worst the user sees the modal
    // again on a future render in the same tab. Acceptable.
  }
}

export function RenderSoftcapWatcher() {
  const { openUpgrade } = useUpgrade();
  const shown = useRef<Set<string>>(loadShown());

  useEffect(() => {
    const handler = (ev: Event) => {
      const detail = (ev as CustomEvent<string>).detail;
      if (typeof detail !== "string" || detail.length === 0) return;
      const reasons = detail.split(",").map((r) => r.trim()).filter(Boolean);
      const fresh = reasons.filter((r) => !shown.current.has(r));
      if (fresh.length === 0) return;
      fresh.forEach((r) => shown.current.add(r));
      persistShown(shown.current);
      toast("Render started — heads up", {
        description:
          "Long renders are a Pro feature. We'll still finish this one.",
      });
      openUpgrade("render_softcap");
    };
    window.addEventListener(RENDER_SOFTCAP_HEADER_EVENT, handler);
    return () =>
      window.removeEventListener(RENDER_SOFTCAP_HEADER_EVENT, handler);
  }, [openUpgrade]);

  return null;
}
