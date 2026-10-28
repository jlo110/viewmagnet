/**
 * BoundaryMarkers — overlay drawn across the full timeline that surfaces
 * every transition boundary as a clickable affordance:
 *
 *  - Diamond marker → single boundary (camera cut or an isolated B-roll
 *    IN/OUT edge that does not abut another B-roll clip).
 *
 *  - "Between" pill → CapCut-style affordance that sits at the seam of
 *    two adjacent B-roll clips on the same track. Clicking it selects
 *    BOTH boundaries (clip A's OUT + clip B's IN) so the Effects panel
 *    can apply ONE transition that produces a real crossfade by
 *    overlapping the clips by the transition duration.
 *
 * Visual encoding for diamonds:
 *   - Pink/glow:   currently selected.
 *   - Purple:      boundary has a TransitionInstance override (or the
 *                  global default is on and explicitly applied).
 *   - Zinc:        plain cut.
 *
 * Visual encoding for between pills:
 *   - Pink ring:   currently selected (between mode).
 *   - Purple:      either edge has an override — the seam carries a
 *                  transition.
 *   - Zinc:        no transition; clips just cut.
 *
 * Mounted as a sibling of the lanes inside the scrollable content so it
 * scrolls with the timeline. ``pointer-events: none`` on the container —
 * each marker re-enables them so clicks land on the marker glyphs and
 * everything else clicks through to the underlying lanes.
 */
import { useMemo } from "react";
import { ArrowLeftRight } from "lucide-react";

import type { EditSpec, TransitionInstance } from "../types";

export interface BoundaryRef {
  id: string;
  kind: "broll_in" | "broll_out" | "camera_cut";
  /** Clip-local seconds where the boundary fires. */
  timeSeconds: number;
  /** Whether an explicit ``TransitionInstance`` exists for this id. */
  hasOverride: boolean;
}

/** Payload emitted when the user clicks a "between two B-roll clips" pill. */
export interface BetweenSelection {
  outId: string;
  inId: string;
  clipAIdx: number;
  clipBIdx: number;
  /** Midpoint timeline time for the pill (in seconds). */
  timeSeconds: number;
}

interface BoundaryMarkersProps {
  spec: EditSpec;
  /** secondsToPx from the timeline controller. */
  secondsToPx: (s: number) => number;
  /** Total vertical extent the markers should span (timeline height). */
  heightPx: number;
  /** ID of a currently-selected single boundary. */
  selectedId: string | null;
  /** ID of a currently-selected between-clips pair (composite key). */
  selectedBetweenKey: string | null;
  /** Called when a single diamond marker is clicked. ``null`` deselects. */
  onSelect: (id: string | null) => void;
  /** Called when a between-clips pill is clicked. ``null`` deselects. */
  onSelectBetween: (sel: BetweenSelection | null) => void;
}

/** Maximum gap (in seconds) between two B-roll clips that we still treat
 *  as "adjacent" for the between-marker. Anything wider than this leaves
 *  visible empty space, so a transition would not produce a true
 *  crossfade — the user can still edit each edge via its own diamond. */
const ADJACENCY_EPSILON_SECONDS = 0.5;

export function betweenKey(outId: string, inId: string): string {
  return `${outId}|${inId}`;
}

export function BoundaryMarkers({
  spec,
  secondsToPx,
  heightPx,
  selectedId,
  selectedBetweenKey,
  onSelect,
  onSelectBetween,
}: BoundaryMarkersProps) {
  const { singletons, pairs } = useMemo(() => collectBoundaries(spec), [spec]);
  if (singletons.length === 0 && pairs.length === 0) return null;

  return (
    <div
      className="pointer-events-none absolute top-0 z-20"
      style={{ left: 0, right: 0, height: heightPx }}
    >
      {singletons.map((b) => {
        const x = secondsToPx(b.timeSeconds);
        const isSelected = b.id === selectedId;
        return (
          <BoundaryDiamond
            key={b.id}
            x={x}
            hasOverride={b.hasOverride}
            selected={isSelected}
            label={b.id}
            heightPx={heightPx}
            onClick={() => onSelect(isSelected ? null : b.id)}
          />
        );
      })}

      {pairs.map((p) => {
        const x = secondsToPx(p.timeSeconds);
        const key = betweenKey(p.outId, p.inId);
        const isSelected = key === selectedBetweenKey;
        return (
          <BetweenPill
            key={key}
            x={x}
            hasOverride={p.hasOverride}
            selected={isSelected}
            label={`Crossfade ${p.outId} → ${p.inId}`}
            heightPx={heightPx}
            onClick={() =>
              onSelectBetween(
                isSelected
                  ? null
                  : {
                      outId: p.outId,
                      inId: p.inId,
                      clipAIdx: p.clipAIdx,
                      clipBIdx: p.clipBIdx,
                      timeSeconds: p.timeSeconds,
                    },
              )
            }
          />
        );
      })}
    </div>
  );
}

function BoundaryDiamond({
  x,
  hasOverride,
  selected,
  label,
  heightPx,
  onClick,
}: {
  x: number;
  hasOverride: boolean;
  selected: boolean;
  label: string;
  heightPx: number;
  onClick: () => void;
}) {
  const color = selected
    ? "#ec4899" // pink — selected
    : hasOverride
    ? "#a855f7" // purple — has override
    : "#71717a"; // zinc-500 — plain cut

  return (
    <div
      className="absolute top-0"
      style={{ left: x, height: heightPx, transform: "translateX(-50%)" }}
    >
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2"
        style={{
          width: 1,
          height: heightPx,
          background: selected ? `${color}55` : "transparent",
        }}
      />
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
        title={label}
        className="pointer-events-auto absolute top-1.5 left-1/2 -translate-x-1/2 cursor-pointer transition-transform hover:scale-125"
        style={{
          width: 10,
          height: 10,
          background: color,
          transform: "translateX(-50%) rotate(45deg)",
          borderRadius: 2,
          boxShadow: selected ? `0 0 8px ${color}` : undefined,
        }}
        aria-label={`Boundary ${label}`}
      />
    </div>
  );
}

function BetweenPill({
  x,
  hasOverride,
  selected,
  label,
  heightPx,
  onClick,
}: {
  x: number;
  hasOverride: boolean;
  selected: boolean;
  label: string;
  heightPx: number;
  onClick: () => void;
}) {
  // Color story mirrors the diamond. The pill is wider and carries an
  // icon so it reads as a different concept ("between two clips") than
  // the single-boundary diamonds.
  const ringColor = selected
    ? "#ec4899"
    : hasOverride
    ? "#a855f7"
    : "#52525b"; // zinc-600
  const fillColor = selected
    ? "rgba(236, 72, 153, 0.18)"
    : hasOverride
    ? "rgba(168, 85, 247, 0.18)"
    : "rgba(63, 63, 70, 0.7)";
  const iconColor = selected
    ? "#fce7f3"
    : hasOverride
    ? "#e9d5ff"
    : "#d4d4d8";

  return (
    <div
      className="absolute top-0"
      style={{ left: x, height: heightPx, transform: "translateX(-50%)" }}
    >
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2"
        style={{
          width: 1,
          height: heightPx,
          background: selected ? `${ringColor}66` : "transparent",
        }}
      />
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
        title={label}
        className="pointer-events-auto absolute top-0.5 left-1/2 inline-flex -translate-x-1/2 items-center justify-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide transition-transform hover:scale-110"
        style={{
          borderColor: ringColor,
          background: fillColor,
          color: iconColor,
          boxShadow: selected ? `0 0 10px ${ringColor}` : undefined,
        }}
        aria-label={label}
      >
        <ArrowLeftRight className="h-2.5 w-2.5" strokeWidth={2.5} />
        <span>tx</span>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Boundary enumeration — mirrors render.py's _collect_all_boundaries
// ---------------------------------------------------------------------------

interface BetweenRef {
  outId: string;
  inId: string;
  clipAIdx: number;
  clipBIdx: number;
  /** Midpoint between A.end and B.start for marker placement. */
  timeSeconds: number;
  hasOverride: boolean;
}

function collectBoundaries(spec: EditSpec): {
  singletons: BoundaryRef[];
  pairs: BetweenRef[];
} {
  const overrideIds = new Set(
    (spec.boundary_transitions ?? []).map((t: TransitionInstance) => t.boundary_id),
  );

  const globalEnabled = spec.transitions?.enabled === true;

  const singletons: BoundaryRef[] = [];
  const pairs: BetweenRef[] = [];

  // -----------------------------------------------------------------
  // B-roll: walk clips per track and decide singleton-vs-pair per edge.
  // Two clips on the same track whose OUT and IN are within
  // ADJACENCY_EPSILON_SECONDS collapse into ONE "between" pill — that
  // is the affordance users reach for when they want a crossfade.
  // Edges that have no adjacent neighbor stay as a diamond.
  // -----------------------------------------------------------------
  if (spec.broll?.enabled !== false && spec.broll?.clips) {
    const clipsWithIdx = spec.broll.clips.map((c, idx) => ({ clip: c, idx }));

    const byTrack = new Map<number, Array<{ clip: typeof clipsWithIdx[number]["clip"]; idx: number }>>();
    for (const entry of clipsWithIdx) {
      const arr = byTrack.get(entry.clip.track) ?? [];
      arr.push(entry);
      byTrack.set(entry.clip.track, arr);
    }

    for (const trackList of Array.from(byTrack.values())) {
      const sorted = [...trackList].sort((a, b) => a.clip.start - b.clip.start);

      // Pair set: for each clip i, look at clip i+1. If adjacent, the
      // (i.out, i+1.in) edges become one pill. Both edges are excluded
      // from the singleton list to avoid duplicating the affordance.
      const consumedAsPair = new Set<string>();

      for (let i = 0; i < sorted.length - 1; i++) {
        const a = sorted[i];
        const b = sorted[i + 1];
        const gap = b.clip.start - a.clip.end;
        if (gap >= -ADJACENCY_EPSILON_SECONDS && gap <= ADJACENCY_EPSILON_SECONDS) {
          const outId = `broll_${a.clip.id}_out`;
          const inId = `broll_${b.clip.id}_in`;
          consumedAsPair.add(outId);
          consumedAsPair.add(inId);
          const hasOverride =
            overrideIds.has(outId) || overrideIds.has(inId) || globalEnabled;
          // Place pill at the seam (A.end). If there's a tiny gap we
          // bias slightly toward the midpoint so it sits visually
          // between the two blocks.
          const t =
            gap > 0
              ? (a.clip.end + b.clip.start) / 2
              : a.clip.end;
          pairs.push({
            outId,
            inId,
            clipAIdx: a.idx,
            clipBIdx: b.idx,
            timeSeconds: t,
            hasOverride,
          });
        }
      }

      for (const entry of sorted) {
        const inId = `broll_${entry.clip.id}_in`;
        const outId = `broll_${entry.clip.id}_out`;
        if (!consumedAsPair.has(inId)) {
          singletons.push({
            id: inId,
            kind: "broll_in",
            timeSeconds: entry.clip.start,
            hasOverride: overrideIds.has(inId) || globalEnabled,
          });
        }
        if (entry.clip.end - entry.clip.start > 0.5 && !consumedAsPair.has(outId)) {
          singletons.push({
            id: outId,
            kind: "broll_out",
            timeSeconds: entry.clip.end,
            hasOverride: overrideIds.has(outId) || globalEnabled,
          });
        }
      }
    }
  }

  if (spec.camera?.tracks?.length) {
    const cuts = [...spec.camera.tracks].sort((a, b) => a.start - b.start);
    for (let i = 0; i < cuts.length - 1; i++) {
      const a = cuts[i];
      const b = cuts[i + 1];
      if (a.subject_id === b.subject_id) continue;
      const id = `camera_cut_${b.id}`;
      singletons.push({
        id,
        kind: "camera_cut",
        timeSeconds: b.start,
        hasOverride: overrideIds.has(id) || globalEnabled,
      });
    }
  }

  return { singletons, pairs };
}
