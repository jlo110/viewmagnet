/**
 * CaptionLane — interactive caption strip in the timeline.
 *
 * Each transcript word is rendered as a small button positioned by its
 * timing. Interactions:
 *   - single click  → select word + seek the player to its start
 *   - double click  → inline edit popover (renames the word's text)
 *   - hover         → tooltip with the word + timestamp
 *
 * The currently-spoken word (per the Remotion playhead) is highlighted in
 * real time. Selection state is owned by the parent Timeline so other UI
 * (split/merge buttons, transcript editor) can react to it.
 *
 * Phrase grouping (visual underline below each phrase) uses the exact same
 * rules as the backend ASS renderer / Remotion CaptionLayer so what users
 * see on the timeline matches the final output.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import type { EditSpec, TranscriptWord } from "../types";
import { groupTranscriptWords } from "../utils/groupTranscriptWords";
import type { TimelineController } from "./useTimelineController";

interface CaptionLaneProps {
  spec: EditSpec;
  controller: TimelineController;
  /** Index of the currently selected word (in `spec.clip.transcript`), or null. */
  selectedWordIndex: number | null;
  onSelectWord: (index: number | null) => void;
  updateSpec: (mutator: (draft: EditSpec) => void) => void;
  beginInteraction: () => void;
}

export function CaptionLane({
  spec,
  controller,
  selectedWordIndex,
  onSelectWord,
  updateSpec,
  beginInteraction,
}: CaptionLaneProps) {
  const words = spec.clip.transcript;
  const captionColor = spec.captions.color_highlight || "#fbbf24";

  // Find the active word for the current playhead frame. Binary search keeps
  // this O(log n) so re-running on every frameupdate stays cheap even with
  // hundreds of words.
  const activeIndex = useMemo(() => {
    if (words.length === 0) return -1;
    const tSec = controller.currentFrame / controller.fps;
    return findActiveWordIndex(words, tSec);
  }, [words, controller.currentFrame, controller.fps]);

  // Phrase groupings — used to draw a thin underline under each phrase so
  // users can see where caption breaks fall in time.
  const phrases = useMemo(() => groupTranscriptWords(words, 6), [words]);

  // Inline-edit popover state. Tracks which word is being edited and the
  // current draft text; mutates the spec on commit.
  const [editingIdx, setEditingIdx] = useState<number | null>(null);

  // Clear selection / edit when the spec swaps to a different clip.
  useEffect(() => {
    setEditingIdx(null);
  }, [spec.clip.source_url]);

  if (!spec.captions.enabled || words.length === 0) {
    return (
      <div className="px-2 text-[10px] leading-loose text-zinc-600">
        Captions disabled or empty — turn on Captions in the right panel.
      </div>
    );
  }

  return (
    <>
      {/* Word blocks */}
      {words.map((w, i) => {
        const start = w.start;
        const end = Math.max(w.end, w.start + 0.05);
        const leftPx = controller.secondsToPx(start);
        const widthPx = Math.max(
          6,
          controller.secondsToPx(end) - controller.secondsToPx(start),
        );
        const isActive = i === activeIndex;
        const isSelected = i === selectedWordIndex;
        return (
          <button
            key={`${i}-${w.start}`}
            type="button"
            data-active={isActive ? "true" : undefined}
            className={`absolute top-1/4 h-1/2 truncate rounded-sm border px-1 text-[10px] font-medium text-zinc-900 transition-colors ${
              isSelected
                ? "ring-2 ring-violet-400 ring-offset-1 ring-offset-zinc-900"
                : ""
            } ${
              isActive
                ? "border-violet-200 brightness-110"
                : "border-transparent opacity-80 hover:opacity-100"
            }`}
            style={{
              left: leftPx,
              width: widthPx,
              background: captionColor,
            }}
            title={`${w.text}  (${start.toFixed(2)}–${end.toFixed(2)}s)`}
            onPointerDown={(e) => {
              // Pointer down (not click) so dragging the scrollable timeline
              // container still works — we don't capture the pointer.
              e.stopPropagation();
              onSelectWord(i);
              controller.seekSeconds(start);
            }}
            onDoubleClick={(e) => {
              e.stopPropagation();
              onSelectWord(i);
              setEditingIdx(i);
            }}
          >
            {w.text}
          </button>
        );
      })}

      {/* Phrase underline ticks (small horizontal lines below each phrase) */}
      {phrases.map((phrase, pIdx) => {
        if (phrase.length === 0) return null;
        const start = phrase[0].start;
        const end = Math.max(
          phrase[phrase.length - 1].end,
          phrase[phrase.length - 1].start + 0.05,
        );
        const left = controller.secondsToPx(start);
        const width = Math.max(2, controller.secondsToPx(end) - left);
        return (
          <div
            key={`phrase-${pIdx}`}
            className="pointer-events-none absolute bottom-0.5 h-px"
            style={{
              left,
              width,
              background: captionColor,
              opacity: 0.6,
            }}
          />
        );
      })}

      {/* Inline edit popover */}
      {editingIdx != null && words[editingIdx] && (
        <InlineWordEdit
          key={`edit-${editingIdx}`}
          word={words[editingIdx]}
          leftPx={controller.secondsToPx(words[editingIdx].start)}
          onCancel={() => setEditingIdx(null)}
          onCommit={(text) => {
            const trimmed = text.trim();
            if (trimmed && trimmed !== words[editingIdx].text) {
              beginInteraction();
              updateSpec((s) => {
                if (s.clip.transcript[editingIdx]) {
                  s.clip.transcript[editingIdx].text = trimmed;
                }
              });
            }
            setEditingIdx(null);
          }}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Binary search for the word whose [start, end] contains `tSec`. Falls back
 * to the closest preceding word's index if the playhead is between words
 * (so the UI always has a visual "current" position).
 */
function findActiveWordIndex(words: TranscriptWord[], tSec: number): number {
  if (words.length === 0) return -1;
  let lo = 0;
  let hi = words.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const w = words[mid];
    if (tSec < w.start) {
      hi = mid - 1;
    } else if (tSec > w.end) {
      lo = mid + 1;
    } else {
      return mid;
    }
  }
  // Not strictly inside any word; surface the previous one if there is one.
  return Math.max(0, hi);
}

interface InlineWordEditProps {
  word: TranscriptWord;
  leftPx: number;
  onCommit: (text: string) => void;
  onCancel: () => void;
}

function InlineWordEdit({ word, leftPx, onCommit, onCancel }: InlineWordEditProps) {
  const [draft, setDraft] = useState(word.text);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  return (
    <div
      className="absolute -top-7 z-20 flex items-center gap-1 rounded border border-violet-400 bg-zinc-900 px-1 py-0.5 shadow-lg"
      style={{ left: Math.max(0, leftPx) }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            onCommit(draft);
          } else if (e.key === "Escape") {
            e.preventDefault();
            onCancel();
          }
          e.stopPropagation();
        }}
        onBlur={() => onCommit(draft)}
        className="w-32 rounded bg-zinc-800 px-1 text-xs text-zinc-100 outline-none focus:bg-zinc-700"
      />
    </div>
  );
}
