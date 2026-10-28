/**
 * BackgroundLoopLayer (Week 6 Phase 2) — renders ``spec.background_loop``
 * underneath the main video in the preview.
 *
 * Behavior mirrors the ffmpeg-side ``-stream_loop -1 [-ss <offset>] -i ...``
 * input planned for the unified renderer (Phase 3): the layer mounts an
 * ``OffthreadVideo`` with ``loop`` so playback wraps seamlessly, applies
 * the ``loop_start_offset_seconds`` as an initial seek, and respects the
 * spec's ``volume`` for the background's own audio (default silent).
 *
 * Visually, it fills its parent — the LayoutComposition (Phase 3) will
 * mount this inside a region <div> sized to the BG rect. For Phase 2 we
 * mount it as a full-canvas underlay inside ``StudioComposition``; once
 * a non-single Layout is picked the LayoutComposition wraps both this
 * and the main video in correctly-sized regions instead.
 */
import { useRef, useEffect } from "react";

import { proxyVideoUrl } from "../sourceUrl";
import type { BackgroundLoop } from "../types";

/** Resolve a spec BackgroundLoop into a playable URL.
 *
 *  Resolution order (so we never crash an old saved spec that's missing
 *  one of the fields):
 *    1. ``clip_url`` if the BackgroundsPanel stored one alongside the
 *       catalog_id (the new behavior — see Studio.tsx onPick handler).
 *    2. ``catalogUrlMap[catalog_id]`` as a back-compat fallback for older
 *       saved sessions that only persisted ``catalog_id``.
 *    3. Pexels-source loops always live in ``clip_url``.
 *
 *  Returning ``null`` falls through to the gradient placeholder so the
 *  composition still renders something instead of a blank black region. */
function resolveBackgroundUrl(
  bg: BackgroundLoop,
  catalogUrlMap: Record<string, string>,
): string | null {
  if (bg.clip_url) return bg.clip_url;
  if (bg.source === "catalog" && bg.catalog_id) {
    return catalogUrlMap[bg.catalog_id] ?? null;
  }
  return null;
}

export interface BackgroundLoopLayerProps {
  backgroundLoop: BackgroundLoop | null | undefined;
  /** Map of ``catalog_id`` → ``download_url`` populated by the Studio
   *  page after fetching ``GET /studio/backgrounds``. Optional — when
   *  empty, catalog-sourced loops render the gradient placeholder. */
  catalogUrlMap?: Record<string, string>;
  /** Composition FPS (passed through for Remotion's ``startFrom`` math). */
  fps: number;
}

export function BackgroundLoopLayer({
  backgroundLoop,
  catalogUrlMap = {},
}: BackgroundLoopLayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  // Apply the ``loop_start_offset_seconds`` after mount + on every src
  // change. Using a native <video loop muted autoplay> rather than
  // Remotion's <OffthreadVideo> because the latter doesn't expose a
  // ``loop`` prop in this Remotion 4.x — the preview-only nature of this
  // layer (we never export from Remotion; ffmpeg owns the final render)
  // makes the native element a perfectly fine fit.
  const url = backgroundLoop
    ? resolveBackgroundUrl(backgroundLoop, catalogUrlMap)
    : null;
  const offsetSeconds = backgroundLoop?.loop_start_offset_seconds ?? 0;
  const volume = Math.max(0, Math.min(1, backgroundLoop?.volume ?? 0));

  useEffect(() => {
    const v = videoRef.current;
    if (!v || !url) return;
    if (offsetSeconds > 0.01 && v.currentTime < offsetSeconds - 0.5) {
      v.currentTime = offsetSeconds;
    }
    v.volume = volume;
    // Always (re-)kick playback when the URL changes, in case autoplay
    // was blocked before user interaction.
    void v.play().catch(() => {
      // ignore — browser will resume after the user clicks Play
    });
  }, [url, offsetSeconds, volume]);

  if (!backgroundLoop) return null;

  // Fallback when the URL isn't available yet (seed script hasn't run,
  // Pexels link expired, etc.): paint a soft gradient so the layout
  // region isn't pitch-black.
  if (!url) {
    return (
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(135deg, rgba(80,80,120,0.6), rgba(20,20,40,0.9))",
        }}
      />
    );
  }

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <video
        ref={videoRef}
        src={proxyVideoUrl(url)}
        loop
        muted={volume <= 0.001}
        autoPlay
        playsInline
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
        }}
      />
    </div>
  );
}
