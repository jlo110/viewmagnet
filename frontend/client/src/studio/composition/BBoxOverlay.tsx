/**
 * BBoxOverlay — debug-style colored rectangles for every detected subject at
 * the current playhead frame. Mainly a UX affordance for the user to "click
 * a face to switch the camera to that person" without scrubbing the timeline.
 *
 * Each rect dispatches a ``studio:camera-insert-cut`` window CustomEvent on
 * click, payload ``{ subjectId, t }``. Studio.tsx listens and rolls the
 * change into a single undo-able interaction via the existing
 * ``beginInteraction`` pattern (mirrors how Week 3's caption-split shortcut
 * is wired).
 *
 * Visibility is toggled by ``spec.camera.bbox_overlay_enabled`` from the
 * Camera panel — we still render the component (for hook stability) but
 * return null when disabled.
 */
import { useCallback } from "react";

import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

import type { TrackingData } from "../types";

export interface BBoxOverlayProps {
  tracking: TrackingData | null;
  enabled: boolean;
}

/** Sample-radius (seconds) when picking the nearest detection frame to the
 *  current playhead. With detection_interval=5 at 30fps, samples are 0.17s
 *  apart, so a half-window of ~0.25s reliably catches one. */
const DETECTION_RADIUS_S = 0.25;

export function BBoxOverlay({ tracking, enabled }: BBoxOverlayProps) {
  const { width, height, fps } = useVideoConfig();
  const frame = useCurrentFrame();

  // Hook-order safety: even when disabled we run the hook above; only the
  // memoized handler depends on tracking so this is cheap.
  const handleSubjectClick = useCallback(
    (subjectId: number, t: number) => {
      if (typeof window === "undefined") return;
      window.dispatchEvent(
        new CustomEvent("studio:camera-insert-cut", {
          detail: { subjectId, t },
        }),
      );
    },
    [],
  );

  if (!enabled || !tracking || tracking.subjects.length === 0) return null;

  const t = frame / fps;

  // Source pixel → canvas pixel mapping. The source video is rendered with
  // either CameraCropLayer's transform or computeCropStyle's cover; for the
  // overlay we approximate the visible viewport by assuming the source is
  // scaled to "cover" the canvas, which is correct when no Camera tracks
  // are active (and close enough when they are — overlay positions feel
  // right because the crop window only translates horizontally).
  const sx = tracking.frame_w;
  const sy = tracking.frame_h;
  // cover scale: max(canvasW/sourceW, canvasH/sourceH)
  const coverScale = Math.max(width / sx, height / sy);
  const renderedW = sx * coverScale;
  const renderedH = sy * coverScale;
  const offsetX = (width - renderedW) / 2;
  const offsetY = (height - renderedH) / 2;

  return (
    <AbsoluteFill style={{ pointerEvents: "none", overflow: "hidden" }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        style={{
          position: "absolute",
          inset: 0,
          pointerEvents: "none",
          // Belt-and-braces: an SVG with width/height set does NOT clip
          // its content by default. Anyone whose source bbox lands outside
          // the cover-cropped visible region would otherwise render in the
          // player chrome.
          overflow: "hidden",
        }}
      >
        {tracking.subjects.map((subject) => {
          const sample = nearestSample(subject.frames, t, DETECTION_RADIUS_S);
          if (!sample) return null;
          const x = sample.x * coverScale + offsetX;
          const y = sample.y * coverScale + offsetY;
          const w = sample.w * coverScale;
          const h = sample.h * coverScale;
          // Skip subjects whose center falls outside the visible canvas —
          // cover-cropping removes part of the source on the long axis,
          // so anyone in that strip simply isn't on screen.
          const cx = x + w / 2;
          const cy = y + h / 2;
          if (cx < 0 || cx > width || cy < 0 || cy > height) return null;
          const label = subject.id + 1;
          return (
            <g
              key={subject.id}
              style={{ pointerEvents: "auto", cursor: "pointer" }}
              onClick={() => handleSubjectClick(subject.id, t)}
            >
              <rect
                x={x}
                y={y}
                width={w}
                height={h}
                fill="none"
                stroke={subject.color_hex}
                strokeWidth={3}
                rx={6}
              />
              {/* Numbered badge in the top-left corner of the bbox. */}
              <g transform={`translate(${x}, ${y - 4})`}>
                <rect
                  x={0}
                  y={-26}
                  width={28}
                  height={26}
                  fill={subject.color_hex}
                  rx={4}
                />
                <text
                  x={14}
                  y={-7}
                  textAnchor="middle"
                  fontFamily="system-ui, sans-serif"
                  fontWeight={700}
                  fontSize={16}
                  fill="#0b0d12"
                >
                  {label}
                </text>
              </g>
            </g>
          );
        })}
      </svg>
    </AbsoluteFill>
  );
}

/** Pick the detection sample closest to ``t``; return null when nothing is
 *  within ``radius`` seconds (subject not detected near current frame). */
function nearestSample(
  frames: Array<{ t: number; x: number; y: number; w: number; h: number; conf: number }>,
  t: number,
  radius: number,
) {
  if (frames.length === 0) return null;
  let best = frames[0];
  let bestDist = Math.abs(best.t - t);
  for (let i = 1; i < frames.length; i++) {
    const d = Math.abs(frames[i].t - t);
    if (d < bestDist) {
      best = frames[i];
      bestDist = d;
    }
  }
  return bestDist <= radius ? best : null;
}
