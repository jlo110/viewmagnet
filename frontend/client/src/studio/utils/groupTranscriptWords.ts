/**
 * Group transcript words into caption phrases using the same precedence
 * rules as the backend ASS renderer (`src/features/studio/ass_renderer.py`
 * `_group_events`). This is the single source of truth for the preview
 * (CaptionLayer) and the timeline UI (CaptionLane), so the user always sees
 * the same phrase breaks they'll get in the rendered video.
 *
 * Precedence:
 *  1. `force_break_after === true`  → start a new phrase after this word.
 *  2. `force_break_after === false` → never break here even if the cap fires.
 *  3. Otherwise, cap each phrase at `groupMaxWords` words.
 */
import type { TranscriptWord } from "../types";

export function groupTranscriptWords(
  words: TranscriptWord[],
  groupMaxWords = 6,
): TranscriptWord[][] {
  if (words.length === 0) return [];

  const groups: TranscriptWord[][] = [];
  let bucket: TranscriptWord[] = [];

  for (const w of words) {
    bucket.push(w);
    const force = w.force_break_after;
    if (force === true) {
      groups.push(bucket);
      bucket = [];
      continue;
    }
    if (force === false) {
      continue;
    }
    if (bucket.length >= groupMaxWords) {
      groups.push(bucket);
      bucket = [];
    }
  }
  if (bucket.length > 0) groups.push(bucket);
  return groups;
}
