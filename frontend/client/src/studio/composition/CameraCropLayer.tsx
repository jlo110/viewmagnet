/**
 * CameraCropLayer — preview-side analog of the ffmpeg piecewise crop= filter
 * we emit in src/features/studio/render.py:_build_camera_crop_filter.
 *
 * Renders the source video at native size and applies a per-frame
 * translate/scale that mimics ``crop=W:H:'x_expr':0,scale=outW:outH``.
 * Looks at the active CameraCut for the current frame, samples that
 * subject's smoothed_crop_x at the current source-frame index, and applies
 * the resulting offset. With ``easePan`` we smoothstep between the previous
 * and next subject's curves across a ±100ms window centered on the cut
 * boundary (same math as the renderer).
 *
 * Critical: the math here MUST match the ffmpeg path 1:1, otherwise users
 * see one thing in preview and a different thing in the final render — the
 * worst possible studio UX.
 */
import {
  AbsoluteFill,
  OffthreadVideo,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import type { CameraCut, EditSpec, TrackingData } from "../types";

export interface CameraCropLayerProps {
  spec: EditSpec;
  tracking: TrackingData;
  videoUrl: string;
  startFromFrame: number;
  endAtFrame: number;
}

/** Ease-pan blend window (seconds on each side of the cut boundary). */
const EASE_HALF_WIDTH = 0.1;

/** How densely we sample (per-frame, since useCurrentFrame is integer). */

export function CameraCropLayer({
  spec,
  tracking,
  videoUrl,
  startFromFrame,
  endAtFrame,
}: CameraCropLayerProps) {
  const { width: canvasW, height: canvasH, fps: playerFps } = useVideoConfig();
  const frame = useCurrentFrame();

  // Clip-local time in seconds. Player's frame clock starts at the trimmed
  // clip's t=0 (matches tracking.frames[].t encoding from compute_tracking).
  const t = frame / playerFps;

  const cropX = computeCropX({
    t,
    cuts: spec.camera.tracks,
    easePan: spec.camera.ease_pan,
    tracking,
    canvasW,
    canvasH,
  });

  if (cropX == null) {
    // No subjects matched, no active cut — fall back to a centered cover.
    return (
      <AbsoluteFill style={{ overflow: "hidden" }}>
        <OffthreadVideo
          src={videoUrl}
          startFrom={startFromFrame}
          endAt={endAtFrame}
          muted={false}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            objectPosition: "center",
          }}
        />
      </AbsoluteFill>
    );
  }

  // Crop window dimensions in source-pixel space: crop_w matches the canvas
  // aspect ratio at full source height. We scale the source so crop_h →
  // canvasH and translate so crop_x → 0.
  const sourceH = tracking.frame_h;
  const sourceW = tracking.frame_w;
  const aspect = canvasW / canvasH;
  let cropW = Math.round(sourceH * aspect);
  if (cropW > sourceW) cropW = sourceW;
  const scale = canvasH / sourceH;
  const tx = -cropX * scale;

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <OffthreadVideo
        src={videoUrl}
        startFrom={startFromFrame}
        endAt={endAtFrame}
        muted={false}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: `${sourceW * scale}px`,
          height: `${sourceH * scale}px`,
          transform: `translate(${tx.toFixed(2)}px, 0)`,
          transformOrigin: "top left",
        }}
      />
    </AbsoluteFill>
  );
}

interface ComputeCropArgs {
  t: number;
  cuts: CameraCut[];
  easePan: boolean;
  tracking: TrackingData;
  canvasW: number;
  canvasH: number;
}

/**
 * Returns the crop_x (source pixels, top-left of the crop window) for the
 * given time, or null if no cut is active and there are no subjects to fall
 * back to.
 *
 * Pure function so the same logic powers both the Remotion preview and a
 * potential unit test (no React hooks inside).
 */
function computeCropX(args: ComputeCropArgs): number | null {
  const { t, cuts, easePan, tracking, canvasW, canvasH } = args;
  const subjects = tracking.subjects;
  if (subjects.length === 0) return null;

  const aspect = canvasW / canvasH;
  let cropW = Math.round(tracking.frame_h * aspect);
  if (cropW > tracking.frame_w) cropW = tracking.frame_w;
  const centerFallback = Math.max(0, Math.floor((tracking.frame_w - cropW) / 2));

  const activeIdx = findActiveCutIndex(cuts, t);
  if (activeIdx === -1) return centerFallback;

  const active = cuts[activeIdx];
  const baseX = sampleSubjectX(active.subject_id, t, tracking, cropW);

  // Ease-pan: smoothstep blend within ±100ms of the boundary into the next
  // cut. We blend the OUTGOING subject's curve into the INCOMING subject's
  // curve; matches the renderer's _build_camera_crop_filter logic.
  if (easePan && activeIdx + 1 < cuts.length) {
    const boundary = cuts[activeIdx].end;
    const next = cuts[activeIdx + 1];
    if (
      next.subject_id !== active.subject_id &&
      t >= boundary - EASE_HALF_WIDTH &&
      t <= boundary + EASE_HALF_WIDTH
    ) {
      const p = clamp(
        (t - (boundary - EASE_HALF_WIDTH)) / (2 * EASE_HALF_WIDTH),
        0,
        1,
      );
      const w = 3 * p * p - 2 * p * p * p;
      const nextX = sampleSubjectX(next.subject_id, t, tracking, cropW);
      return Math.round(baseX + (nextX - baseX) * w);
    }
  }

  return baseX;
}

function findActiveCutIndex(cuts: CameraCut[], t: number): number {
  for (let i = 0; i < cuts.length; i++) {
    if (t >= cuts[i].start && t < cuts[i].end) return i;
  }
  return -1;
}

function sampleSubjectX(
  subjectId: number,
  t: number,
  tracking: TrackingData,
  cropW: number,
): number {
  const subj = tracking.subjects.find((s) => s.id === subjectId);
  if (!subj || subj.smoothed_crop_x.length === 0) {
    return Math.max(0, Math.floor((tracking.frame_w - cropW) / 2));
  }
  // smoothed_crop_x is indexed by source-frame number in the cached segment.
  const idx = Math.max(
    0,
    Math.min(subj.smoothed_crop_x.length - 1, Math.round(t * tracking.fps)),
  );
  const cx = subj.smoothed_crop_x[idx];
  // Clamp into the legal range (in case smoothing pushed past edges).
  return Math.max(0, Math.min(tracking.frame_w - cropW, Math.round(cx)));
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}
