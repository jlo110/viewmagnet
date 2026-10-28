/**
 * AutoZoomLayer — wraps a child subtree (the base video) and applies a
 * per-frame ``transform: scale(z)`` pulse around each
 * ``spec.auto_zoom.timestamps[i]``.
 *
 * Mirrors the ffmpeg side in ``src/features/studio/render.py
 * _build_auto_zoom_filter``: same 200ms ease-in / 400ms hold / 400ms
 * ease-out smoothstep pulse so the preview matches the rendered MP4 frame
 * for frame.
 *
 * Sits between the base video and the B-roll overlay layer so B-roll stays
 * full-frame even while the underlying video is zoomed — matching the
 * render pipeline which only scales the [main] branch.
 */
import { useCurrentFrame, useVideoConfig } from "remotion";

import type { AutoZoom } from "../types";

const EASE_IN = 0.2;
const HOLD = 0.4;
const EASE_OUT = 0.4;

interface AutoZoomLayerProps {
  autoZoom: AutoZoom | undefined | null;
  children: React.ReactNode;
}

export function AutoZoomLayer({ autoZoom, children }: AutoZoomLayerProps) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const z = computeZoom(frame / fps, autoZoom);

  // Skip the wrapper entirely when zoom is unity — pure pass-through so
  // we don't introduce a needless extra positioning context (Remotion's
  // base-video layer expects to fill its parent and tolerate it being
  // either a div OR AbsoluteFill).
  if (z <= 1.0001) {
    return <>{children}</>;
  }

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        transform: `scale(${z.toFixed(4)})`,
        transformOrigin: "center center",
        // willChange tells the compositor we're animating transform so it
        // keeps the layer on the GPU — avoids janky reflows during the
        // ease window.
        willChange: "transform",
      }}
    >
      {children}
    </div>
  );
}

/**
 * Compute z(t) = 1 + sum-of-pulses(t).
 *
 * Pulses are non-overlapping (the auto-zoom endpoint enforces >= 3s gap
 * between timestamps), so summing is equivalent to "active pulse"
 * selection — no need to clamp.
 */
export function computeZoom(
  tSec: number,
  autoZoom: AutoZoom | undefined | null,
): number {
  if (!autoZoom || !autoZoom.enabled) return 1.0;
  const ts = autoZoom.timestamps;
  if (!ts || ts.length === 0) return 1.0;
  const max = Math.max(1.0, Math.min(2.0, autoZoom.max_scale));
  if (max <= 1.0001) return 1.0;
  const bump = max - 1.0;

  let sum = 0;
  for (const t of ts) {
    const tIn0 = Math.max(0, t - EASE_IN);
    const tPeak = t;
    const tHoldEnd = t + HOLD;
    const tEnd = t + HOLD + EASE_OUT;
    if (tSec < tIn0 || tSec >= tEnd) continue;
    if (tSec < tPeak) {
      const p = (tSec - tIn0) / EASE_IN;
      sum += bump * smoothstep(p);
    } else if (tSec < tHoldEnd) {
      sum += bump;
    } else {
      const p = (tSec - tHoldEnd) / EASE_OUT;
      sum += bump * (1 - smoothstep(p));
    }
  }
  return 1.0 + sum;
}

function smoothstep(p: number): number {
  const x = Math.max(0, Math.min(1, p));
  return 3 * x * x - 2 * x * x * x;
}
