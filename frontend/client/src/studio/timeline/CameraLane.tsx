/**
 * CameraLane — one timeline lane that visualizes ``spec.camera.tracks``.
 *
 * Each ``CameraCut`` becomes a ``ClipBlock`` tinted with the subject's
 * color (from cached tracking). Behaviors:
 *  - Drag the body to slide the cut in time (clamped to its neighbors).
 *  - Trim left/right to resize, with a minimum cut length so we don't
 *    rapid-flash between subjects.
 *  - Click to select; selection feeds into Studio's keyboard handler so
 *    Delete removes the cut.
 *  - When tracking is still computing we render a thin striped placeholder
 *    so users know the lane is alive but waiting.
 *
 * Mutations go through ``updateSpec`` so they slot into the existing
 * undo/auto-save pipeline alongside B-roll edits.
 */
import type { EditSpec, TrackingData } from "../types";
import { ClipBlock } from "./ClipBlock";
import type { TimelineController } from "./useTimelineController";

export interface CameraLaneProps {
  spec: EditSpec;
  tracking: TrackingData | null;
  trackingStatus: "idle" | "computing" | "done" | "failed";
  controller: TimelineController;
  selectedIndex: number | null;
  onSelectCut: (index: number | null) => void;
  updateSpec: (mutator: (draft: EditSpec) => void) => void;
  beginInteraction: () => void;
}

/** Minimum cut length in seconds — matches the backend auto-switch heuristic
 *  so user-dragged cuts can't be shorter than what the AI ever produces. */
const MIN_CUT_SECONDS = 0.3;

export function CameraLane({
  spec,
  tracking,
  trackingStatus,
  controller,
  selectedIndex,
  onSelectCut,
  updateSpec,
  beginInteraction,
}: CameraLaneProps) {
  // Defensive: an old session JSON loaded before the spec defaults were
  // backfilled server-side could be missing ``camera`` entirely. Treat as
  // empty so we render a passive lane instead of crashing the whole Studio.
  const cameraTracks = spec.camera?.tracks ?? [];
  const subjectsById = new Map(
    (tracking?.subjects ?? []).map((s) => [s.id, s]),
  );

  return (
    <>
      {/* "Loading" stripe while tracking is computing. Tailwind's
          repeating-linear-gradient via inline style for the diagonal stripes. */}
      {trackingStatus === "computing" && cameraTracks.length === 0 && (
        <div
          className="absolute inset-0 opacity-40"
          style={{
            background:
              "repeating-linear-gradient(45deg, transparent 0 6px, rgba(124,58,237,0.25) 6px 12px)",
            animation: "studio-stripe 1.2s linear infinite",
          }}
        />
      )}

      {cameraTracks.map((cut, idx) => {
        const subject = subjectsById.get(cut.subject_id);
        const color = subject?.color_hex ?? "#7c3aed";
        const label = subject ? subject.label : `Cam ${cut.subject_id + 1}`;
        const prev = cameraTracks[idx - 1];
        const next = cameraTracks[idx + 1];
        return (
          <ClipBlock
            key={idx}
            controller={controller}
            startSeconds={cut.start}
            endSeconds={cut.end}
            label={label}
            color={color}
            selected={selectedIndex === idx}
            minDurationSeconds={MIN_CUT_SECONDS}
            // Clamp into the gap between neighbors so dragging can't make
            // tracks overlap (would break the renderer's "first cut wins"
            // lookup).
            minSeconds={prev ? prev.end : 0}
            maxSeconds={next ? next.start : controller.durationSeconds}
            onSelect={() => onSelectCut(idx)}
            onInteractionStart={beginInteraction}
            onChange={({ start, end }) =>
              updateSpec((s) => {
                const target = s.camera.tracks[idx];
                if (!target) return;
                target.start = Math.max(0, start);
                target.end = Math.min(controller.durationSeconds, end);
              })
            }
            onDelete={() =>
              updateSpec((s) => {
                s.camera.tracks.splice(idx, 1);
                onSelectCut(null);
              })
            }
          />
        );
      })}
    </>
  );
}
