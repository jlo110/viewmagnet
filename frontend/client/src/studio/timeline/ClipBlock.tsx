/**
 * ClipBlock — a draggable, resizable block on a timeline lane.
 *
 * Used by the source video lane (trim handles only) and the B-roll lanes
 * (drag the whole block + trim handles). Pointer math is hand-rolled
 * (pointerdown/pointermove/pointerup) so we have full control over snap-to-
 * frame behavior; no extra dep.
 *
 * Coordinate convention: ``startSeconds`` / ``endSeconds`` are clip-local
 * times (0 == clip.start_time). Position is computed via the timeline
 * controller's ``secondsToPx``.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { TimelineController } from "./useTimelineController";

export interface ClipBlockProps {
  controller: TimelineController;
  startSeconds: number;
  endSeconds: number;
  label?: string;
  selected?: boolean;
  /** Disable the body drag (used for the source video lane — only the
   *  trim handles should move). */
  draggable?: boolean;
  /** Show/hide individual handles. The source lane shows both; a fixed B-roll
   *  preview could turn off resize entirely. */
  resizableLeft?: boolean;
  resizableRight?: boolean;
  /** Minimum width in seconds — prevents collapsing a clip into a sliver. */
  minDurationSeconds?: number;
  /** Optional clamp window in seconds (lane-relative). Defaults to
   *  [0, controller.durationSeconds]. */
  minSeconds?: number;
  maxSeconds?: number;
  className?: string;
  /** Background color of the block body — pass a Tailwind class via
   *  ``className`` for variants; this is a hex fallback. */
  color?: string;
  onSelect?: () => void;
  onChange?: (next: { start: number; end: number }) => void;
  /** Fired once at the start of an interaction so the parent can snapshot
   *  state for undo. */
  onInteractionStart?: () => void;
  onDelete?: () => void;
}

type DragMode = "move" | "trim-left" | "trim-right" | null;

export function ClipBlock({
  controller,
  startSeconds,
  endSeconds,
  label,
  selected = false,
  draggable = true,
  resizableLeft = true,
  resizableRight = true,
  minDurationSeconds = 0.1,
  minSeconds,
  maxSeconds,
  className,
  color = "#7c3aed",
  onSelect,
  onChange,
  onInteractionStart,
  onDelete,
}: ClipBlockProps) {
  const clampMin = minSeconds ?? 0;
  const clampMax = maxSeconds ?? controller.durationSeconds;

  const [drag, setDrag] = useState<{
    mode: DragMode;
    pointerStartX: number;
    origStart: number;
    origEnd: number;
  } | null>(null);

  const left = controller.secondsToPx(Math.max(0, startSeconds));
  const width = Math.max(
    2,
    controller.secondsToPx(endSeconds) - controller.secondsToPx(startSeconds),
  );

  // We must read the latest props inside the global pointermove handler, so
  // mirror them in a ref to avoid stale-closure bugs.
  const propsRef = useRef({
    onChange,
    controller,
    minDurationSeconds,
    clampMin,
    clampMax,
  });
  propsRef.current = {
    onChange,
    controller,
    minDurationSeconds,
    clampMin,
    clampMax,
  };

  const startDrag = useCallback(
    (mode: Exclude<DragMode, null>, e: React.PointerEvent) => {
      e.stopPropagation();
      e.preventDefault();
      (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
      onInteractionStart?.();
      onSelect?.();
      setDrag({
        mode,
        pointerStartX: e.clientX,
        origStart: startSeconds,
        origEnd: endSeconds,
      });
    },
    [startSeconds, endSeconds, onInteractionStart, onSelect],
  );

  // Global pointermove + pointerup so the user can drag outside the block
  // without losing the gesture (essential when shrinking near the edge).
  useEffect(() => {
    if (!drag) return;
    const handleMove = (e: PointerEvent) => {
      const { controller: c, minDurationSeconds: minDur, clampMin: minS, clampMax: maxS, onChange: cb } =
        propsRef.current;
      const dxPx = e.clientX - drag.pointerStartX;
      const dxSec = c.pxToSeconds(dxPx);
      const freeform = e.shiftKey;

      let nextStart = drag.origStart;
      let nextEnd = drag.origEnd;

      if (drag.mode === "move") {
        const dur = drag.origEnd - drag.origStart;
        nextStart = c.snap(drag.origStart + dxSec, freeform);
        nextEnd = nextStart + dur;
        // Clamp the whole block to [minS, maxS]
        if (nextStart < minS) {
          nextStart = minS;
          nextEnd = minS + dur;
        }
        if (nextEnd > maxS) {
          nextEnd = maxS;
          nextStart = maxS - dur;
        }
      } else if (drag.mode === "trim-left") {
        nextStart = c.snap(drag.origStart + dxSec, freeform);
        nextStart = Math.max(minS, Math.min(drag.origEnd - minDur, nextStart));
      } else if (drag.mode === "trim-right") {
        nextEnd = c.snap(drag.origEnd + dxSec, freeform);
        nextEnd = Math.min(maxS, Math.max(drag.origStart + minDur, nextEnd));
      }

      cb?.({ start: nextStart, end: nextEnd });
    };
    const handleUp = () => setDrag(null);

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("pointercancel", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("pointercancel", handleUp);
    };
  }, [drag]);

  return (
    <div
      className={`absolute top-0 bottom-0 rounded-md border ${
        selected
          ? "border-violet-400 ring-2 ring-violet-500/50"
          : "border-zinc-700 hover:border-zinc-500"
      } ${className ?? ""}`}
      style={{
        left,
        width,
        background: color,
        cursor: draggable ? "grab" : "default",
        touchAction: "none",
      }}
      onPointerDown={(e) => {
        if (draggable) startDrag("move", e);
        else onSelect?.();
      }}
      onKeyDown={(e) => {
        if ((e.key === "Delete" || e.key === "Backspace") && onDelete) {
          e.preventDefault();
          onDelete();
        }
      }}
      tabIndex={0}
      role="button"
      aria-label={label ?? "clip"}
    >
      {/* Body label */}
      <div className="pointer-events-none flex h-full items-center justify-between gap-2 px-2 text-[10px] font-medium text-white/90">
        <span className="truncate">{label}</span>
        <span className="opacity-60 tabular-nums">
          {(endSeconds - startSeconds).toFixed(1)}s
        </span>
      </div>

      {/* Left trim handle — visible at rest (white grip strip) so users
          discover that clips are resizable without having to hover-hunt
          for the hit zone. Brightens on hover and lights up when grabbed. */}
      {resizableLeft && (
        <div
          className="group/handle absolute left-0 top-0 bottom-0 z-10 flex w-2.5 cursor-ew-resize items-center justify-center"
          onPointerDown={(e) => startDrag("trim-left", e)}
          style={{ touchAction: "none" }}
          title="Drag to trim the start"
        >
          <div className="h-3/5 w-[3px] rounded-full bg-white/70 shadow-[0_0_0_1px_rgba(0,0,0,0.4)] transition-colors group-hover/handle:bg-white" />
        </div>
      )}

      {/* Right trim handle — symmetric counterpart to the left handle. */}
      {resizableRight && (
        <div
          className="group/handle absolute right-0 top-0 bottom-0 z-10 flex w-2.5 cursor-ew-resize items-center justify-center"
          onPointerDown={(e) => startDrag("trim-right", e)}
          style={{ touchAction: "none" }}
          title="Drag to trim the end"
        >
          <div className="h-3/5 w-[3px] rounded-full bg-white/70 shadow-[0_0_0_1px_rgba(0,0,0,0.4)] transition-colors group-hover/handle:bg-white" />
        </div>
      )}
    </div>
  );
}
