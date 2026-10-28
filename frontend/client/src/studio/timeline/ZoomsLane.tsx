/**
 * ZoomsLane — visualizes ``spec.auto_zoom.timestamps`` as a row of tick
 * markers on the timeline.
 *
 * Each timestamp gets a small "pulse" rectangle keyed to the same 200ms
 * ramp-in / 400ms hold / 400ms ramp-out window the renderer uses, so the
 * visual width on the lane matches the on-screen zoom duration.
 *
 * Click a marker to select it (Studio's Delete/Backspace handler removes
 * the selected timestamp from spec.auto_zoom.timestamps). Dragging is NOT
 * supported — auto-zoom moments are content-driven; if the user wants
 * something different they re-run Detect or delete and add at a specific
 * time via the playhead-anchored "+" affordance in the Effects panel.
 */
import type { EditSpec } from "../types";
import type { TimelineController } from "./useTimelineController";

export interface ZoomsLaneProps {
  spec: EditSpec;
  controller: TimelineController;
  selectedIndex: number | null;
  onSelectZoom: (index: number | null) => void;
}

// Pulse window must match _build_auto_zoom_filter in render.py.
const PULSE_TOTAL = 0.2 + 0.4 + 0.4; // 1.0s

export function ZoomsLane({
  spec,
  controller,
  selectedIndex,
  onSelectZoom,
}: ZoomsLaneProps) {
  const zoom = spec.auto_zoom;
  const timestamps = zoom?.timestamps ?? [];

  if (timestamps.length === 0) {
    return (
      <div className="absolute inset-0 flex items-center px-2 text-[10px] opacity-30">
        {zoom?.enabled ? "No zooms detected yet. Hit 'Detect zooms'." : "Auto-zoom off"}
      </div>
    );
  }

  return (
    <>
      {timestamps.map((t, i) => {
        const x = controller.secondsToPx(t - 0.2); // align to ease-in start
        const width = Math.max(
          6,
          controller.secondsToPx(PULSE_TOTAL),
        );
        const isSelected = selectedIndex === i;
        return (
          <button
            key={`${i}-${t}`}
            onClick={(e) => {
              e.stopPropagation();
              onSelectZoom(isSelected ? null : i);
            }}
            className="absolute top-1/2 -translate-y-1/2 rounded-md transition-colors"
            style={{
              left: x,
              width,
              height: 22,
              background: isSelected
                ? "linear-gradient(90deg, rgba(244,114,182,0.7), rgba(244,114,182,1), rgba(244,114,182,0.7))"
                : "linear-gradient(90deg, rgba(244,114,182,0.15), rgba(244,114,182,0.55), rgba(244,114,182,0.15))",
              border: `1px solid ${isSelected ? "#f472b6" : "rgba(244,114,182,0.5)"}`,
              boxShadow: isSelected
                ? "0 0 0 2px rgba(244,114,182,0.4)"
                : undefined,
            }}
            title={`Zoom @ ${t.toFixed(2)}s${
              zoom?.max_scale ? ` (${zoom.max_scale.toFixed(2)}x)` : ""
            }`}
          >
            <span className="block text-center text-[9px] font-medium tabular-nums leading-[20px] text-white drop-shadow">
              {t.toFixed(1)}s
            </span>
          </button>
        );
      })}
    </>
  );
}
