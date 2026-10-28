/**
 * CaptionLayer — renders the user's transcript words on top of the video,
 * sized + styled per the spec.captions config + style preset.
 *
 * Uses Remotion's frame clock so the highlighted word advances in perfect
 * sync with playback (and with the eventual server-side render).
 */
import { useMemo } from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

import type { BrandKit, Captions, TranscriptWord } from "../types";
import { groupTranscriptWords } from "../utils/groupTranscriptWords";
import { getCaptionPreset } from "./captionStyles";

// Spec defaults — used to detect "user hasn't customized this field"
// so the brand kit can fill it in. Kept in sync with the Captions
// defaults in src/features/studio/spec.py.
const CAPTIONS_DEFAULT_PRIMARY = "#FFFFFF";
const CAPTIONS_DEFAULT_HIGHLIGHT = "#00FF00";
const CAPTIONS_DEFAULT_FONT = "Montserrat";

interface CaptionLayerProps {
  captions: Captions;
  words: TranscriptWord[];
  /** Number of seconds to subtract from word.start/end to match clip timeline */
  timeOffsetSeconds?: number;
  /** When true, the layer draws a thin debug grid behind itself */
  debug?: boolean;
  /**
   * Pixel rectangle of the MAIN video region inside the composition. Captions
   * are anchored to the main rect so split/PiP layouts keep them inside the
   * primary video instead of straying over the background loop. Defaults to
   * the full canvas (single-layout behaviour).
   */
  mainRegion?: { x: number; y: number; w: number; h: number };
  /**
   * Per-user brand kit. When set, ``primary_color`` / ``accent_color`` and
   * ``font_family`` override the caption preset's defaults — but ONLY when
   * the user hasn't explicitly customized the matching field in the
   * Captions panel. Mirrors the same precedence rule applied server-side
   * in :func:`src.features.studio.ass_renderer._resolve_brand_overrides`.
   */
  brandKit?: BrandKit | null;
}

export function CaptionLayer({
  captions: rawCaptions,
  words,
  timeOffsetSeconds = 0,
  debug = false,
  mainRegion,
  brandKit,
}: CaptionLayerProps) {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const tSeconds = frame / fps + timeOffsetSeconds;

  if (!rawCaptions.enabled || words.length === 0) {
    return debug ? <DebugGrid /> : null;
  }

  const presetBase = getCaptionPreset(rawCaptions.style);

  // Brand kit overrides: only apply when the user hasn't moved the
  // matching caption field off its default. This way explicit user choices
  // in the Captions panel always beat brand kit, but a brand kit still
  // styles every new clip out of the box.
  let captions: Captions = rawCaptions;
  let preset = presetBase;
  if (brandKit) {
    const next: Captions = { ...rawCaptions };
    let dirty = false;
    if (
      brandKit.primary_color &&
      rawCaptions.color_primary === CAPTIONS_DEFAULT_PRIMARY
    ) {
      next.color_primary = brandKit.primary_color;
      dirty = true;
    }
    if (
      brandKit.accent_color &&
      rawCaptions.color_highlight === CAPTIONS_DEFAULT_HIGHLIGHT
    ) {
      next.color_highlight = brandKit.accent_color;
      dirty = true;
    }
    if (dirty) captions = next;

    if (
      brandKit.font_family &&
      (!rawCaptions.font_family || rawCaptions.font_family === CAPTIONS_DEFAULT_FONT)
    ) {
      preset = { ...presetBase, fontFamily: brandKit.font_family };
    }
  }

  const region = mainRegion ?? { x: 0, y: 0, w: width, h: height };

  // Vertical placement → flex alignment
  const justify =
    captions.position === "top"
      ? "flex-start"
      : captions.position === "middle"
      ? "center"
      : "flex-end";

  // Margin from the edge as a fraction of the MAIN region height — keeps
  // captions readable on phones (matches the ASS MarginV of region_h/12).
  const edgePadding = Math.max(40, Math.round(region.h / 12));

  const containerStyle: React.CSSProperties = {
    position: "absolute",
    left: region.x,
    top: region.y,
    width: region.w,
    height: region.h,
    justifyContent: justify,
    alignItems: "center",
    display: "flex",
  };

  if (captions.highlight_mode === "word") {
    return (
      <div style={containerStyle}>
        <CurrentWord
          words={words}
          tSeconds={tSeconds}
          captions={captions}
          preset={preset}
          edgePadding={edgePadding}
        />
      </div>
    );
  }

  return (
    <div style={containerStyle}>
      <CurrentGroup
        words={words}
        tSeconds={tSeconds}
        captions={captions}
        preset={preset}
        edgePadding={edgePadding}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Word-by-word mode
// ---------------------------------------------------------------------------

interface RenderProps {
  words: TranscriptWord[];
  tSeconds: number;
  captions: Captions;
  preset: ReturnType<typeof getCaptionPreset>;
  edgePadding: number;
}

function CurrentWord({ words, tSeconds, captions, preset, edgePadding }: RenderProps) {
  const active = words.find((w) => tSeconds >= w.start && tSeconds <= w.end);
  if (!active) return null;

  const ageSec = Math.max(0, tSeconds - active.start);
  const popProgress = Math.min(1, (ageSec * 1000) / preset.popDurationMs);
  const scale = 1 + (preset.popScale - 1) * (1 - Math.pow(1 - popProgress, 3));

  const text = captions.uppercase ? active.text.toUpperCase() : active.text;
  const emoji =
    captions.emoji_enabled && active.emoji ? active.emoji : undefined;

  return (
    <div
      style={{
        marginTop: captions.position === "top" ? edgePadding : 0,
        marginBottom: captions.position === "bottom" ? edgePadding : 0,
        transform: `scale(${scale.toFixed(3)})`,
        transformOrigin: "center",
        transition: "none",
        maxWidth: "85%",
        textAlign: "center",
      }}
    >
      <WordSpan
        text={text}
        emoji={emoji}
        captions={captions}
        preset={preset}
        highlighted
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Group / phrase mode
// ---------------------------------------------------------------------------

function CurrentGroup({ words, tSeconds, captions, preset, edgePadding }: RenderProps) {
  // Group words into phrases using the same rules as the backend ASS
  // renderer so what users see in the preview matches the final render
  // exactly. Cached per `words` reference so we don't rebucket every frame.
  const groups = useMemo(() => groupTranscriptWords(words, 6), [words]);
  if (groups.length === 0) return null;

  // Pick the group containing the current time. We use the first group
  // whose last word's `end` is >= tSeconds; for the trailing tail (past the
  // final word) we hold the last group on screen briefly.
  const group =
    groups.find((g) => tSeconds <= g[g.length - 1].end) ?? groups[groups.length - 1];
  if (!group || group.length === 0) return null;

  return (
    <div
      style={{
        marginTop: captions.position === "top" ? edgePadding : 0,
        marginBottom: captions.position === "bottom" ? edgePadding : 0,
        maxWidth: "85%",
        textAlign: "center",
        lineHeight: 1.2,
        display: "flex",
        flexWrap: "wrap",
        justifyContent: "center",
        gap: "0.4em",
      }}
    >
      {group.map((word, i) => {
        const isActive = tSeconds >= word.start && tSeconds <= word.end;
        const text = captions.uppercase ? word.text.toUpperCase() : word.text;
        const emoji =
          captions.emoji_enabled && word.emoji ? word.emoji : undefined;
        return (
          <WordSpan
            key={`${word.start}-${i}`}
            text={text}
            emoji={emoji}
            captions={captions}
            preset={preset}
            highlighted={isActive}
          />
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single word renderer (handles both modes' styling)
// ---------------------------------------------------------------------------

interface WordSpanProps {
  text: string;
  /** Optional sentiment emoji rendered as a trailing inline span. The
   *  parent decides whether to pass this based on captions.emoji_enabled
   *  + word.emoji, so WordSpan stays purely presentational. */
  emoji?: string;
  captions: Captions;
  preset: ReturnType<typeof getCaptionPreset>;
  highlighted: boolean;
}

function WordSpan({ text, emoji, captions, preset, highlighted }: WordSpanProps) {
  const color = highlighted ? captions.color_highlight : captions.color_primary;

  // Multi-shadow trick to fake a uniform text-stroke that works in all
  // browsers (and in Remotion's headless renderer). Each shadow draws one
  // offset copy in the stroke color.
  const stroke = preset.strokeWidth;
  const strokeShadows = stroke
    ? [
        `${stroke}px 0 0 ${preset.strokeColor}`,
        `-${stroke}px 0 0 ${preset.strokeColor}`,
        `0 ${stroke}px 0 ${preset.strokeColor}`,
        `0 -${stroke}px 0 ${preset.strokeColor}`,
        `${stroke}px ${stroke}px 0 ${preset.strokeColor}`,
        `-${stroke}px -${stroke}px 0 ${preset.strokeColor}`,
        `${stroke}px -${stroke}px 0 ${preset.strokeColor}`,
        `-${stroke}px ${stroke}px 0 ${preset.strokeColor}`,
      ]
    : [];
  const dropShadow =
    preset.shadowBlur || preset.shadowOffsetY
      ? `0 ${preset.shadowOffsetY}px ${preset.shadowBlur}px ${preset.shadowColor}`
      : null;
  const textShadow = [...strokeShadows, dropShadow].filter(Boolean).join(", ");

  const baseStyle: React.CSSProperties = {
    color,
    fontFamily: preset.fontFamily,
    fontWeight: preset.fontWeight,
    fontSize: `${captions.font_size}px`,
    textTransform: preset.textTransform,
    letterSpacing: preset.letterSpacing,
    textShadow,
    display: "inline-block",
    whiteSpace: "nowrap",
  };

  // Emoji renders as a trailing inline span at ~80% of the word size, so
  // it sits beside the word without dominating the caption layout. Drop
  // the text shadow / stroke on the emoji glyph itself — those tricks
  // were tuned for letters and look muddy on color glyphs.
  const emojiNode = emoji ? (
    <span
      style={{
        marginLeft: "0.3em",
        fontSize: `${Math.round(captions.font_size * 0.8)}px`,
        textShadow: "none",
        display: "inline-block",
        verticalAlign: "baseline",
      }}
    >
      {emoji}
    </span>
  ) : null;

  if (preset.boxed) {
    return (
      <span
        style={{
          ...baseStyle,
          backgroundColor: highlighted ? captions.color_highlight : preset.boxColor,
          color: highlighted ? "#000" : color,
          padding: preset.boxPadding,
          borderRadius: 6,
        }}
      >
        {text}
        {emojiNode}
      </span>
    );
  }

  return (
    <span style={baseStyle}>
      {text}
      {emojiNode}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Debug grid (off by default, useful when fiddling with alignment)
// ---------------------------------------------------------------------------

function DebugGrid() {
  return (
    <AbsoluteFill
      style={{
        backgroundImage:
          "linear-gradient(rgba(0,255,0,0.15) 1px, transparent 1px), linear-gradient(90deg, rgba(0,255,0,0.15) 1px, transparent 1px)",
        backgroundSize: "60px 60px",
        pointerEvents: "none",
      }}
    />
  );
}
