/**
 * Tests for studio/utils/groupTranscriptWords.ts
 *
 * This is the single source of truth for phrase grouping in both the
 * Remotion caption preview (CaptionLayer) and the timeline (CaptionLane).
 * It must match the Python backend's `_group_events` in ass_renderer.py.
 */
import { describe, it, expect } from "vitest";
import { groupTranscriptWords } from "../studio/utils/groupTranscriptWords";
import type { TranscriptWord } from "../studio/types";

function word(text: string, start = 0, end = 1, force?: boolean): TranscriptWord {
  return { text, start, end, force_break_after: force } as TranscriptWord;
}

describe("groupTranscriptWords", () => {
  it("returns empty array for empty input", () => {
    expect(groupTranscriptWords([])).toEqual([]);
  });

  it("groups up to groupMaxWords words per bucket", () => {
    const words = [
      word("a"), word("b"), word("c"), word("d"),
      word("e"), word("f"), word("g"),
    ];
    const groups = groupTranscriptWords(words, 3);
    expect(groups).toHaveLength(3);
    expect(groups[0]).toHaveLength(3);
    expect(groups[1]).toHaveLength(3);
    expect(groups[2]).toHaveLength(1);
  });

  it("uses default groupMaxWords of 6", () => {
    const words = Array.from({ length: 12 }, (_, i) => word(`w${i}`));
    const groups = groupTranscriptWords(words);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveLength(6);
  });

  it("force_break_after === true ends current bucket immediately", () => {
    const words = [
      word("hello", 0, 1, true),    // force break after 1st word
      word("world", 1, 2),
      word("foo", 2, 3),
    ];
    const groups = groupTranscriptWords(words, 10);
    // First bucket is just ["hello"], second is ["world", "foo"]
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveLength(1);
    expect(groups[0][0].text).toBe("hello");
  });

  it("force_break_after === false prevents a break even when cap is reached", () => {
    const words = [
      word("a", 0, 1, false),
      word("b", 1, 2, false),
      word("c", 2, 3, false),   // cap=3 but false prevents break
      word("d", 3, 4),
    ];
    const groups = groupTranscriptWords(words, 3);
    // a, b, c have force=false so no break at 3; d triggers break or end
    expect(groups).toHaveLength(1);  // all 4 in one bucket
  });

  it("force_break_after true overrides cap limit", () => {
    // Single word with force break → single-word group
    const words = [word("only", 0, 1, true), word("next", 1, 2)];
    const groups = groupTranscriptWords(words, 6);
    expect(groups[0]).toHaveLength(1);
    expect(groups[0][0].text).toBe("only");
  });

  it("final bucket is included even without hitting the cap", () => {
    const words = [word("a"), word("b")];
    const groups = groupTranscriptWords(words, 6);
    expect(groups).toHaveLength(1);
    expect(groups[0]).toHaveLength(2);
  });

  it("multiple consecutive force breaks produce multiple single-word groups", () => {
    const words = [
      word("a", 0, 1, true),
      word("b", 1, 2, true),
      word("c", 2, 3),
    ];
    const groups = groupTranscriptWords(words, 10);
    expect(groups).toHaveLength(3);
    expect(groups[0][0].text).toBe("a");
    expect(groups[1][0].text).toBe("b");
    expect(groups[2][0].text).toBe("c");
  });

  it("large input produces correct number of groups", () => {
    const words = Array.from({ length: 100 }, (_, i) => word(`w${i}`));
    const groups = groupTranscriptWords(words, 6);
    // 100 / 6 = 16 full groups + 1 remainder = 17
    expect(groups).toHaveLength(Math.ceil(100 / 6));
    const total = groups.reduce((sum, g) => sum + g.length, 0);
    expect(total).toBe(100);
  });
});
