/**
 * Timeline — Spikes-style multi-lane editor strip mounted at the bottom of
 * the Studio.
 *
 *   ┌─ Ruler (clickable to seek) ─────────────────────────────────────────┐
 *   ├─ Source video lane (waveform background, trim handles on top) ─────┤
 *   ├─ Captions lane (click word → seek, dbl-click → edit, split/merge) ─┤
 *   ├─ B-roll lanes (drag/resize blocks → mutate spec.broll.clips[i]) ───┤
 *   └─ Playhead overlay (vertical line, draggable handle on top) ────────┘
 *
 * Mutations go through ``updateSpec`` so they flow through
 * ``useEditSession``'s coalesced history (undo) and debounced auto-save.
 *
 * Zoom (Week 3): ruler + lanes are wrapped in a horizontally scrolling
 * container. Cmd/Ctrl + wheel zooms the timeline anchored on the cursor's
 * seconds-position, so users can drill into a sub-second region without
 * losing their place. The playhead auto-pans into view during playback.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { PlayerRef } from "@remotion/player";
import { Scissors, ChevronsLeftRight, RotateCcw, Minus, Plus } from "lucide-react";

import type { EditSpec, TrackingData } from "../types";
import { BoundaryMarkers, betweenKey } from "./BoundaryMarkers";
import { CameraLane } from "./CameraLane";
import { CaptionLane } from "./CaptionLane";
import { ClipBlock } from "./ClipBlock";
import { TimelineRuler } from "./TimelineRuler";
import { WaveformLane } from "./WaveformLane";
import { ZoomsLane } from "./ZoomsLane";
import { useTimelineController } from "./useTimelineController";

// Lane heights are deliberately compact — the timeline is a strip, not a
// full DAW. Bumping them >40 wastes screen real estate that the preview
// already needs.
const LANE_HEIGHT = 40;
const RULER_HEIGHT = 22;
const LANE_LABEL_WIDTH = 88;

// Zoom bounds — 1x fits the whole clip on screen, 16x lets users line up
// frame-perfect edits even on a 30-second clip in a narrow window.
const ZOOM_MIN = 1;
const ZOOM_MAX = 16;
const ZOOM_STEP = 1.5;

export type TimelineSelection =
  | { kind: "none" }
  | { kind: "broll"; index: number }
  | { kind: "word"; index: number }
  | { kind: "camera"; index: number }
  | { kind: "zoom"; index: number }
  | { kind: "boundary"; id: string }
  /** "Between two B-roll clips" affordance — picking a transition here
   *  stamps it on BOTH boundaries (clip A's OUT + clip B's IN) and
   *  shifts clip B left so the clips overlap by the transition duration,
   *  producing a real crossfade (Week 6 follow-up). */
  | {
      kind: "between";
      outId: string;
      inId: string;
      clipAIdx: number;
      clipBIdx: number;
    };

export interface TimelineProps {
  spec: EditSpec;
  playerRef: React.RefObject<PlayerRef | null>;
  selection: TimelineSelection;
  setSelection: (s: TimelineSelection) => void;
  /** Atomic mutate-the-spec helper from useEditSession. */
  updateSpec: (mutator: (draft: EditSpec) => void) => void;
  /** Called once when a drag/resize gesture begins, so the parent can push
   *  the pre-state to its undo stack. */
  beginInteraction: () => void;
  /** Stable clip key used to fetch the waveform peaks; null when the
   *  session row hasn't been created yet (waveform stays blank in that case). */
  clipKey: string | null;
  /** Current zoom multiplier (1..16). Owned by the parent so keyboard
   *  shortcuts can poke it; default 1. */
  zoom: number;
  setZoom: (z: number) => void;
  /** Cached tracking + its status (from useTrackingData). Used to colorize
   *  Camera lane blocks and to show a "loading" stripe before the first
   *  detection arrives. */
  tracking?: TrackingData | null;
  trackingStatus?: "idle" | "computing" | "done" | "failed";
}

export function Timeline({
  spec,
  playerRef,
  selection,
  setSelection,
  updateSpec,
  beginInteraction,
  clipKey,
  zoom,
  setZoom,
  tracking,
  trackingStatus = "idle",
}: TimelineProps) {
  // Visible container width — the controller derives pixelsPerSecond from
  // this. Wrapped in a ref/state combo so ResizeObserver-driven updates
  // re-render the lanes.
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [viewportWidth, setViewportWidth] = useState(0);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      setViewportWidth(w);
    });
    ro.observe(el);
    setViewportWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);

  const controller = useTimelineController({
    playerRef,
    containerWidthPx: viewportWidth,
    clipStartSeconds: spec.clip.start_time,
    clipEndSeconds: spec.clip.end_time,
    fps: 30,
    zoom,
  });

  // Group B-roll clips by track so each lane stacks blocks correctly.
  const brollByTrack = new Map<number, Array<{ idx: number; clip: EditSpec["broll"]["clips"][number] }>>();
  spec.broll.clips.forEach((clip, idx) => {
    const arr = brollByTrack.get(clip.track) ?? [];
    arr.push({ idx, clip });
    brollByTrack.set(clip.track, arr);
  });
  const brollTracks = Array.from(brollByTrack.keys()).sort((a, b) => a - b);
  // Always show at least one B-roll lane so users have an obvious drop zone.
  if (brollTracks.length === 0) brollTracks.push(2);

  // Source duration as a single block that fills the lane. Trim handles
  // mutate spec.clip.start_time/end_time, which the render pipeline (and
  // the Remotion composition) already respect.
  const sourceDuration = spec.clip.end_time - spec.clip.start_time;

  // Total content width inside the scroller. We always render at least
  // viewport width so the scroller never feels "shorter than its container".
  const contentWidthPx = Math.max(
    viewportWidth,
    Math.ceil(controller.pixelsPerSecond * controller.durationSeconds),
  );

  // ---------- Cmd-wheel zoom anchored on the cursor ----------
  const handleWheel = useCallback(
    (e: React.WheelEvent<HTMLDivElement>) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const scroller = scrollerRef.current;
      if (!scroller) return;
      const rect = scroller.getBoundingClientRect();
      const cursorXInViewport = e.clientX - rect.left;
      // Time the cursor is hovering BEFORE we change zoom.
      const cursorTimeSec = controller.pxToSeconds(scroller.scrollLeft + cursorXInViewport);
      const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
      const nextZoom = clamp(zoom * factor, ZOOM_MIN, ZOOM_MAX);
      if (nextZoom === zoom) return;
      setZoom(nextZoom);
      // After React re-renders with the new zoom we need to adjust scrollLeft
      // so the same cursorTimeSec ends up under the cursor. requestAnimationFrame
      // lets the layout settle first.
      requestAnimationFrame(() => {
        const s = scrollerRef.current;
        if (!s) return;
        const newPxPerSec = s.scrollWidth / Math.max(0.01, controller.durationSeconds);
        const desiredLeft = cursorTimeSec * newPxPerSec - cursorXInViewport;
        s.scrollLeft = Math.max(0, desiredLeft);
      });
    },
    [zoom, setZoom, controller],
  );

  // ---------- Auto-pan: keep the playhead in view during playback ----------
  useEffect(() => {
    const s = scrollerRef.current;
    if (!s) return;
    if (!controller.isPlaying) return;
    const playheadX = controller.secondsToPx(controller.currentFrame / controller.fps);
    const margin = viewportWidth * 0.1;
    if (playheadX < s.scrollLeft + margin) {
      s.scrollLeft = Math.max(0, playheadX - margin);
    } else if (playheadX > s.scrollLeft + viewportWidth - margin) {
      s.scrollLeft = Math.max(0, playheadX - viewportWidth * 0.5);
    }
  }, [controller.currentFrame, controller.isPlaying, controller.fps, controller.secondsToPx, viewportWidth]);

  // ---------- Split/merge state for the currently selected caption word ----------
  const selectedWordIndex = selection.kind === "word" ? selection.index : null;
  const selectedWord =
    selectedWordIndex != null ? spec.clip.transcript[selectedWordIndex] ?? null : null;
  const prevWord =
    selectedWordIndex != null && selectedWordIndex > 0
      ? spec.clip.transcript[selectedWordIndex - 1] ?? null
      : null;

  const handleToggleBreak = useCallback(() => {
    if (selectedWordIndex == null || selectedWordIndex <= 0) return;
    beginInteraction();
    updateSpec((s) => {
      const prev = s.clip.transcript[selectedWordIndex - 1];
      if (!prev) return;
      // Three-state toggle: null → true → false → null. Lets a single key
      // (S) cycle a word through "auto", "force break", "force continue".
      const current = prev.force_break_after ?? null;
      prev.force_break_after =
        current === null ? true : current === true ? false : null;
    });
  }, [selectedWordIndex, updateSpec, beginInteraction]);

  const handleResetBreak = useCallback(() => {
    if (selectedWordIndex == null || selectedWordIndex <= 0) return;
    beginInteraction();
    updateSpec((s) => {
      const prev = s.clip.transcript[selectedWordIndex - 1];
      if (prev) prev.force_break_after = null;
    });
  }, [selectedWordIndex, updateSpec, beginInteraction]);

  // Expose the toggle on a ref so the parent's `S` keyboard handler can call
  // it without re-binding on every render. We use a ref + useEffect rather
  // than a hook return value so Timeline.tsx stays a pure component.
  // (Actually, since Studio.tsx owns the selection state we just let it call
  // these via the keyboard shortcut path below by reading selection.)

  // Listen for the S key while a word is selected; the global listener in
  // Studio.tsx forwards it via a custom event. We use a simple window event
  // because Timeline doesn't otherwise need to expose API surface.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ action: "toggle" | "reset" }>).detail;
      if (detail?.action === "reset") handleResetBreak();
      else handleToggleBreak();
    };
    window.addEventListener("studio:caption-split", handler);
    return () => window.removeEventListener("studio:caption-split", handler);
  }, [handleToggleBreak, handleResetBreak]);

  // Toolbar pinned to the timeline header so users can click split/merge as
  // well as use the S shortcut.
  const splitMergeLabel = useMemo(() => {
    if (!prevWord) return null;
    const v = prevWord.force_break_after;
    if (v === true) return "Break after prev (manual)";
    if (v === false) return "Merged with prev (manual)";
    return null;
  }, [prevWord]);

  return (
    <div className="border-t border-zinc-800 bg-zinc-950 select-none">
      {/* Toolbar row — zoom controls + split/merge buttons when a word is selected. */}
      <div className="flex items-center justify-between gap-2 border-b border-zinc-800/60 px-2 py-1 text-[11px] text-zinc-400">
        <div className="flex items-center gap-2">
          <span className="opacity-60">Timeline</span>
          {selectedWord && prevWord && (
            <div className="flex items-center gap-1 rounded border border-zinc-800 bg-zinc-900 px-1.5 py-0.5">
              <span className="opacity-60">
                "{prevWord.text}" → "{selectedWord.text}"
              </span>
              <button
                onClick={handleToggleBreak}
                className="ml-1 inline-flex items-center gap-1 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] hover:bg-zinc-700"
                title="Toggle caption break before this word (S)"
              >
                {prevWord.force_break_after === true ? (
                  <>
                    <ChevronsLeftRight className="h-3 w-3" />
                    Merge
                  </>
                ) : (
                  <>
                    <Scissors className="h-3 w-3" />
                    Break
                  </>
                )}
              </button>
              {prevWord.force_break_after !== null &&
                prevWord.force_break_after !== undefined && (
                  <button
                    onClick={handleResetBreak}
                    className="inline-flex items-center gap-1 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] hover:bg-zinc-700"
                    title="Reset to automatic grouping"
                  >
                    <RotateCcw className="h-3 w-3" />
                    Auto
                  </button>
                )}
              {splitMergeLabel && (
                <span className="ml-1 text-[10px] text-violet-300/80">{splitMergeLabel}</span>
              )}
            </div>
          )}
        </div>
        <ZoomControls zoom={zoom} setZoom={setZoom} />
      </div>

      <div className="flex">
        {/* Lane labels gutter — sticky so it stays put when the lanes scroll. */}
        <div
          className="flex flex-col border-r border-zinc-800 text-[10px] text-zinc-500"
          style={{ width: LANE_LABEL_WIDTH }}
        >
          <div style={{ height: RULER_HEIGHT }} />
          <LaneLabel height={LANE_HEIGHT} label="Source" />
          <LaneLabel height={LANE_HEIGHT} label="Camera" />
          <LaneLabel height={LANE_HEIGHT} label="Zooms" />
          <LaneLabel height={LANE_HEIGHT} label="Captions" />
          {brollTracks.map((t) => (
            <LaneLabel key={t} height={LANE_HEIGHT} label={`B-Roll ${t - 1}`} />
          ))}
        </div>

        {/* Scrollable lanes viewport */}
        <div className="relative min-w-0 flex-1" ref={viewportRef}>
          <div
            ref={scrollerRef}
            className="overflow-x-auto overflow-y-hidden"
            onWheel={handleWheel}
            // Click-through to deselect any word/broll when clicking the
            // empty scroller background.
            onPointerDown={(e) => {
              if (e.target === e.currentTarget) {
                setSelection({ kind: "none" });
              }
            }}
          >
            <div className="relative" style={{ width: contentWidthPx }}>
              <TimelineRuler controller={controller} height={RULER_HEIGHT} />

              {/* Source video lane — waveform painted as the lane background,
                  trim handles rendered on top with a transparent body so the
                  waveform shows through. */}
              <Lane height={LANE_HEIGHT}>
                <WaveformLane
                  clipKey={clipKey}
                  clipStartTime={spec.clip.start_time}
                  clipEndTime={spec.clip.end_time}
                  widthPx={contentWidthPx}
                  heightPx={LANE_HEIGHT}
                  color="#64748b"
                />
                <ClipBlock
                  controller={controller}
                  startSeconds={0}
                  endSeconds={sourceDuration}
                  label={spec.clip.suggested_title ?? "Source clip"}
                  color="transparent"
                  draggable={false}
                  resizableLeft
                  resizableRight
                  minDurationSeconds={0.5}
                  onInteractionStart={beginInteraction}
                  onChange={({ start, end }) => {
                    updateSpec((s) => {
                      const origStart = s.clip.start_time;
                      const dur = s.clip.end_time - origStart;
                      s.clip.start_time = origStart + start;
                      s.clip.end_time = origStart + Math.min(dur, end);
                    });
                  }}
                />
              </Lane>

              {/* Camera lane (Week 4) — virtual multi-cam cuts. */}
              <Lane height={LANE_HEIGHT}>
                <CameraLane
                  spec={spec}
                  tracking={tracking ?? null}
                  trackingStatus={trackingStatus}
                  controller={controller}
                  selectedIndex={
                    selection.kind === "camera" ? selection.index : null
                  }
                  onSelectCut={(idx) =>
                    setSelection(
                      idx == null ? { kind: "none" } : { kind: "camera", index: idx },
                    )
                  }
                  updateSpec={updateSpec}
                  beginInteraction={beginInteraction}
                />
              </Lane>

              {/* Zooms lane (Week 5) — auto-zoom punch-in markers. */}
              <Lane height={LANE_HEIGHT}>
                <ZoomsLane
                  spec={spec}
                  controller={controller}
                  selectedIndex={
                    selection.kind === "zoom" ? selection.index : null
                  }
                  onSelectZoom={(idx) =>
                    setSelection(
                      idx == null ? { kind: "none" } : { kind: "zoom", index: idx },
                    )
                  }
                />
              </Lane>

              {/* Captions lane */}
              <Lane height={LANE_HEIGHT}>
                <CaptionLane
                  spec={spec}
                  controller={controller}
                  selectedWordIndex={selectedWordIndex}
                  onSelectWord={(idx) =>
                    setSelection(idx == null ? { kind: "none" } : { kind: "word", index: idx })
                  }
                  updateSpec={updateSpec}
                  beginInteraction={beginInteraction}
                />
              </Lane>

              {/* B-roll lanes */}
              {brollTracks.map((track) => (
                <Lane key={track} height={LANE_HEIGHT}>
                  {(brollByTrack.get(track) ?? []).map(({ idx, clip }) => (
                    <ClipBlock
                      key={idx}
                      controller={controller}
                      startSeconds={clip.start}
                      endSeconds={clip.end}
                      label={clip.label ?? clip.clip_url.split("/").pop() ?? "broll"}
                      color="#7c3aed"
                      selected={selection.kind === "broll" && selection.index === idx}
                      minDurationSeconds={0.2}
                      onSelect={() => setSelection({ kind: "broll", index: idx })}
                      onInteractionStart={beginInteraction}
                      onChange={({ start, end }) =>
                        updateSpec((s) => {
                          if (s.broll.clips[idx]) {
                            s.broll.clips[idx].start = start;
                            s.broll.clips[idx].end = end;
                          }
                        })
                      }
                      onDelete={() =>
                        updateSpec((s) => {
                          s.broll.clips.splice(idx, 1);
                          setSelection({ kind: "none" });
                        })
                      }
                    />
                  ))}
                </Lane>
              ))}

              {/* Boundary markers (Week 6 Phase 4) — diamond at every B-roll
                  IN/OUT and camera-cut boundary; click to select for
                  per-boundary transition editing. Mounted above lanes,
                  below the playhead. */}
              <div
                className="pointer-events-none absolute left-0 right-0"
                style={{ top: RULER_HEIGHT, height: (4 + brollTracks.length) * LANE_HEIGHT }}
              >
                <BoundaryMarkers
                  spec={spec}
                  secondsToPx={controller.secondsToPx}
                  heightPx={(4 + brollTracks.length) * LANE_HEIGHT}
                  selectedId={selection.kind === "boundary" ? selection.id : null}
                  selectedBetweenKey={
                    selection.kind === "between"
                      ? betweenKey(selection.outId, selection.inId)
                      : null
                  }
                  onSelect={(id) =>
                    setSelection(id == null ? { kind: "none" } : { kind: "boundary", id })
                  }
                  onSelectBetween={(sel) =>
                    setSelection(
                      sel == null
                        ? { kind: "none" }
                        : {
                            kind: "between",
                            outId: sel.outId,
                            inId: sel.inId,
                            clipAIdx: sel.clipAIdx,
                            clipBIdx: sel.clipBIdx,
                          },
                    )
                  }
                />
              </div>

              {/* Playhead overlay — lives inside the scrollable content so it
                  scrolls with the lanes, not on top of them. */}
              <Playhead
                xPx={controller.secondsToPx(controller.currentFrame / controller.fps)}
                laneCount={4 + brollTracks.length}
                onScrub={(deltaPx) =>
                  controller.seekSeconds(
                    controller.currentFrame / controller.fps +
                      controller.pxToSeconds(deltaPx),
                  )
                }
                onClickThrough={() => setSelection({ kind: "none" })}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function LaneLabel({ height, label }: { height: number; label: string }) {
  return (
    <div
      className="flex items-center justify-end border-t border-zinc-800 px-2 uppercase tracking-wide"
      style={{ height }}
    >
      {label}
    </div>
  );
}

function Lane({
  height,
  children,
}: {
  height: number;
  children?: React.ReactNode;
}) {
  return (
    <div
      className="relative border-t border-zinc-800 bg-zinc-900/30"
      style={{ height }}
    >
      {children}
    </div>
  );
}

function Playhead({
  xPx,
  laneCount,
  onScrub,
  onClickThrough,
}: {
  xPx: number;
  laneCount: number;
  onScrub: (deltaPx: number) => void;
  onClickThrough: () => void;
}) {
  const [drag, setDrag] = useState<{ startX: number } | null>(null);

  useEffect(() => {
    if (!drag) return;
    const handleMove = (e: PointerEvent) => onScrub(e.clientX - drag.startX);
    const handleUp = () => setDrag(null);
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [drag, onScrub]);

  const fullHeight = laneCount * LANE_HEIGHT;

  return (
    <div
      className="pointer-events-none absolute top-0 z-10"
      style={{ left: xPx, height: RULER_HEIGHT + fullHeight }}
    >
      {/* Grabbable triangle in the ruler area */}
      <div
        className="pointer-events-auto absolute -left-2 top-0 h-0 w-0 cursor-ew-resize border-l-[8px] border-r-[8px] border-t-[10px] border-l-transparent border-r-transparent border-t-violet-400"
        onPointerDown={(e) => {
          e.preventDefault();
          (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
          setDrag({ startX: e.clientX });
        }}
        onClick={onClickThrough}
      />
      {/* Vertical line through all lanes */}
      <div
        className="absolute top-0 w-px bg-violet-400"
        style={{ height: RULER_HEIGHT + fullHeight }}
      />
    </div>
  );
}

function ZoomControls({ zoom, setZoom }: { zoom: number; setZoom: (z: number) => void }) {
  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => setZoom(clamp(zoom / ZOOM_STEP, ZOOM_MIN, ZOOM_MAX))}
        className="rounded p-1 hover:bg-zinc-800"
        title="Zoom out (⌘-)"
      >
        <Minus className="h-3 w-3" />
      </button>
      <button
        onClick={() => setZoom(1)}
        className="min-w-[42px] rounded px-1.5 py-0.5 text-center tabular-nums hover:bg-zinc-800"
        title="Reset zoom (⌘0)"
      >
        {Math.round(zoom * 100)}%
      </button>
      <button
        onClick={() => setZoom(clamp(zoom * ZOOM_STEP, ZOOM_MIN, ZOOM_MAX))}
        className="rounded p-1 hover:bg-zinc-800"
        title="Zoom in (⌘+)"
      >
        <Plus className="h-3 w-3" />
      </button>
    </div>
  );
}

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}
