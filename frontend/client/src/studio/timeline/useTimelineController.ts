/**
 * useTimelineController — bridges the Studio Timeline UI with the Remotion
 * <Player>.
 *
 * Provides:
 *   - `pixelsPerSecond` / pixel<->seconds<->frame conversion helpers based on
 *     the current container width and clip duration
 *   - `currentFrame` live from PlayerRef ("frameupdate" emitter)
 *   - `seekFrame(frame)` and `seekSeconds(seconds)` for clicks/drags
 *   - `snap(seconds)` that quantizes to frame boundaries unless shift is held
 *
 * Kept dependency-free (just useState/useEffect) so the timeline stays
 * snappy and we don't pull in another drag library.
 */
import { useCallback, useEffect, useState } from "react";
import type { PlayerRef } from "@remotion/player";

export interface TimelineController {
  /** Pixels per second mapping for placing things in the lane. */
  pixelsPerSecond: number;
  /** Current playhead frame in the clip's timebase (0 == clip.start_time). */
  currentFrame: number;
  /** Total duration in seconds (end_time - start_time). */
  durationSeconds: number;
  /** Output framerate (matches Remotion <Player> fps). */
  fps: number;
  /** True when the player is currently advancing frames. */
  isPlaying: boolean;
  /** Convert seconds within [0, durationSeconds] to a pixel x offset. */
  secondsToPx: (seconds: number) => number;
  /** Convert a pixel x offset back to seconds. */
  pxToSeconds: (px: number) => number;
  /** Seek the player; values outside the duration are clamped. */
  seekSeconds: (seconds: number) => void;
  seekFrame: (frame: number) => void;
  /** Snap a seconds value to the nearest frame boundary unless `freeform`. */
  snap: (seconds: number, freeform?: boolean) => number;
  /** Play/pause toggle (mirrors PlayerRef.toggle). */
  toggle: () => void;
  /** Nudge by one frame; useful for keyboard arrows. */
  nudgeFrames: (delta: number) => void;
}

export interface UseTimelineControllerArgs {
  playerRef: React.RefObject<PlayerRef | null>;
  /** Container width in pixels — passed in by the parent so the timeline
   *  reflows when the window resizes. Use a ResizeObserver in the parent. */
  containerWidthPx: number;
  /** clip.start_time and clip.end_time in source-video seconds. The timeline
   *  always renders in **clip-local time** (0..durationSeconds). */
  clipStartSeconds: number;
  clipEndSeconds: number;
  fps?: number;
  /** Multiplier applied to the natural fit-to-container pixelsPerSecond.
   *  zoom = 1 → the whole clip fits the visible container (default behavior).
   *  zoom > 1 → content is wider than the container, parent wraps in a
   *  horizontally scrolling div. Defaults to 1. */
  zoom?: number;
}

export function useTimelineController({
  playerRef,
  containerWidthPx,
  clipStartSeconds,
  clipEndSeconds,
  fps = 30,
  zoom = 1,
}: UseTimelineControllerArgs): TimelineController {
  const durationSeconds = Math.max(0.01, clipEndSeconds - clipStartSeconds);
  // basePixelsPerSecond fits the whole clip to the container; the zoom
  // multiplier scales it up so the same conversion math (secondsToPx, etc.)
  // automatically widens every block + tick mark with no other changes.
  const basePixelsPerSecond =
    containerWidthPx > 0 ? containerWidthPx / durationSeconds : 0;
  const pixelsPerSecond = basePixelsPerSecond * Math.max(0.1, zoom);

  const [currentFrame, setCurrentFrame] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  // Drive the playhead by polling the player every animation frame.
  //
  // Why not event subscription? `@remotion/player` assigns its imperative
  // handle inside the Player's own child effects, so `playerRef.current` is
  // frequently still null when this hook's effect first runs. A one-shot
  // `useEffect(() => { playerRef.current?.addEventListener(...) }, [])`
  // therefore silently misses every frameupdate event and the playhead
  // never moves — which is exactly the symptom we hit.
  //
  // A rAF loop tolerates a not-yet-ready ref (just skips that frame),
  // automatically self-throttles to the display refresh rate, and always
  // reflects the latest player state regardless of when the ref attached.
  useEffect(() => {
    let raf = 0;
    let cancelled = false;
    let lastFrame = -1;
    let lastPlaying: boolean | null = null;

    const tick = () => {
      if (cancelled) return;
      const player = playerRef.current;
      if (player) {
        try {
          const f = player.getCurrentFrame();
          if (f !== lastFrame) {
            lastFrame = f;
            setCurrentFrame(f);
          }
          const p = player.isPlaying();
          if (p !== lastPlaying) {
            lastPlaying = p;
            setIsPlaying(p);
          }
        } catch {
          // Player not initialized yet — silently retry on the next frame.
        }
      }
      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
    };
  }, [playerRef]);

  const secondsToPx = useCallback(
    (seconds: number) => Math.max(0, seconds * pixelsPerSecond),
    [pixelsPerSecond],
  );

  const pxToSeconds = useCallback(
    (px: number) => (pixelsPerSecond > 0 ? px / pixelsPerSecond : 0),
    [pixelsPerSecond],
  );

  const snap = useCallback(
    (seconds: number, freeform = false) => {
      if (freeform) return Math.max(0, Math.min(durationSeconds, seconds));
      const frame = Math.round(seconds * fps);
      const snapped = frame / fps;
      return Math.max(0, Math.min(durationSeconds, snapped));
    },
    [durationSeconds, fps],
  );

  const seekFrame = useCallback(
    (frame: number) => {
      const player = playerRef.current;
      if (!player) return;
      const maxFrame = Math.floor(durationSeconds * fps);
      const clamped = Math.max(0, Math.min(maxFrame, Math.round(frame)));
      player.seekTo(clamped);
      setCurrentFrame(clamped);
    },
    [playerRef, durationSeconds, fps],
  );

  const seekSeconds = useCallback(
    (seconds: number) => seekFrame(seconds * fps),
    [seekFrame, fps],
  );

  const toggle = useCallback(() => {
    const player = playerRef.current;
    if (!player) return;
    player.toggle();
  }, [playerRef]);

  const nudgeFrames = useCallback(
    (delta: number) => seekFrame(currentFrame + delta),
    [seekFrame, currentFrame],
  );

  return {
    pixelsPerSecond,
    currentFrame,
    durationSeconds,
    fps,
    isPlaying,
    secondsToPx,
    pxToSeconds,
    seekSeconds,
    seekFrame,
    snap,
    toggle,
    nudgeFrames,
  };
}
