"""Render an EditSpec.captions config into an ASS subtitle file.

ASS (Advanced SubStation Alpha) is the format ffmpeg's ``subtitles`` filter
understands for richly styled, animated burn-in captions. Each preset in
``CaptionStyleName`` maps to an ASS Style line with the right font, color,
outline, and per-event animation tags.

This is the *server-side* burn-in path used by the render job. The browser
preview uses Remotion's React-based caption components so what users see
in the editor matches what gets rendered — but ASS gives us the exact
visual output the user previewed because both paths consume the same
``Captions`` config.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from src.features.studio.spec import (
    BrandKit,
    CaptionPosition,
    CaptionStyleName,
    Captions,
    HighlightMode,
    TranscriptWord,
)

# --------------------------------------------------------------------------
# ASS color helpers (ASS uses &HBBGGRR& — note BGR order, not RGB)
# --------------------------------------------------------------------------


def _hex_to_ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """``"#RRGGBB"`` → ASS ``"&HAABBGGRR"``. ``alpha`` 0=opaque, 255=transparent."""
    h = hex_rgb.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _format_ass_time(seconds: float) -> str:
    """Seconds → ``H:MM:SS.CC`` (centisecond precision; ASS requirement)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:01d}:{m:02d}:{int(s):02d}.{int((s % 1) * 100):02d}"


# --------------------------------------------------------------------------
# Style presets — these map 1:1 to the visual presets in AnimatedCaptions.tsx
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _StylePreset:
    """Per-style overrides applied on top of the user's ``Captions`` config."""

    font_family: str
    bold: bool
    italic: bool
    border_style: int  # 1=outline+shadow, 3=opaque box
    outline: float
    shadow: float


_PRESETS: dict[CaptionStyleName, _StylePreset] = {
    CaptionStyleName.CAPCUT: _StylePreset(
        font_family="Montserrat", bold=True, italic=False,
        border_style=1, outline=3.5, shadow=1.0,
    ),
    CaptionStyleName.MRBEAST: _StylePreset(
        font_family="Impact", bold=True, italic=False,
        border_style=1, outline=5.0, shadow=2.0,
    ),
    CaptionStyleName.HORMOZI: _StylePreset(
        font_family="Arial Black", bold=True, italic=False,
        border_style=3, outline=4.0, shadow=0.0,
    ),
    CaptionStyleName.NEON: _StylePreset(
        font_family="Bebas Neue", bold=True, italic=False,
        border_style=1, outline=2.5, shadow=4.0,
    ),
    CaptionStyleName.MINIMAL: _StylePreset(
        font_family="Inter", bold=False, italic=False,
        border_style=1, outline=1.5, shadow=0.5,
    ),
    CaptionStyleName.BOUNCE: _StylePreset(
        font_family="Poppins", bold=True, italic=False,
        border_style=1, outline=3.0, shadow=1.5,
    ),
    CaptionStyleName.KARAOKE: _StylePreset(
        font_family="Roboto", bold=True, italic=False,
        border_style=1, outline=2.5, shadow=1.0,
    ),
}


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def build_ass(
    captions: Captions,
    words: List[TranscriptWord],
    video_width: int,
    video_height: int,
    group_max_words: int = 6,
    *,
    main_region_y: int = 0,
    main_region_h: Optional[int] = None,
    brand_kit: Optional[BrandKit] = None,
) -> str:
    """Render captions config + transcript words → full ASS subtitle file body.

    The caller writes this to a ``.ass`` file then references it from ffmpeg:

        ffmpeg ... -vf "ass=captions.ass" ...

    Args:
        captions: User-chosen caption settings (style, colors, font size, …).
        words: Whisper word-level timing, seconds from clip start.
        video_width / video_height: Output dimensions used for ASS PlayResX/Y.
        group_max_words: When ``highlight_mode == GROUP``, words per phrase
            line (smaller numbers → faster pace, bigger emphasis on each).
        main_region_y / main_region_h: Pixel rectangle of the main video
            region inside the canvas (Week 6 split / PiP layouts). When the
            main region doesn't fill the canvas, ASS captions need their
            ``MarginV`` shifted so the text lands *inside* the main video
            instead of overlapping the background loop. Defaults to
            ``y=0, h=video_height`` (single-layout behaviour).
        brand_kit: When the user has a per-user brand kit configured,
            ``primary_color`` / ``accent_color`` override the caption
            preset's primary / highlight colors, and ``font_family``
            overrides the preset's font. The explicit caption settings
            still win when the user has changed them away from the spec
            defaults — see ``_resolve_brand_overrides`` below. Optional
            so callers that don't care about branding (tests, legacy code)
            keep working unchanged.
    """
    if main_region_h is None or main_region_h <= 0:
        main_region_h = video_height
        main_region_y = 0
    main_region_y = max(0, min(video_height, int(main_region_y)))
    main_region_h = max(1, min(video_height - main_region_y, int(main_region_h)))

    if not captions.enabled or not words:
        # Return a valid-but-empty ASS file so ffmpeg's subtitles filter is
        # a no-op rather than failing the render.
        return _empty_ass(video_width, video_height)

    preset = _PRESETS.get(captions.style, _PRESETS[CaptionStyleName.CAPCUT])

    # Brand kit overrides (Week 6). When the user has a brand kit AND
    # they haven't explicitly overridden the relevant caption fields
    # (e.g. picked a custom highlight color in the Captions panel), we
    # apply the brand kit on top so brand colors / font follow them
    # across every clip without manual setup per session.
    primary_color, highlight_color, font_family = _resolve_brand_overrides(
        captions, preset, brand_kit
    )

    primary = _hex_to_ass_color(primary_color)
    secondary = _hex_to_ass_color(highlight_color)
    outline = _hex_to_ass_color(captions.stroke_color)
    back = _hex_to_ass_color("#000000", alpha=128)

    # ASS alignment numpad: 1=BL 2=BC 3=BR 5=TL 6=TC 7=TR 9=middle-row...
    alignment = {
        CaptionPosition.TOP: 8,     # top-center
        CaptionPosition.MIDDLE: 5,  # middle-center
        CaptionPosition.BOTTOM: 2,  # bottom-center
    }[captions.position]

    # ASS interprets MarginV depending on alignment:
    #   - top alignments (7/8/9)    → distance from canvas TOP
    #   - bottom alignments (1/2/3) → distance from canvas BOTTOM
    #   - middle alignments (4/5/6) → distance from CENTER (vertical nudge)
    # For Week 6 split/PiP layouts the captions must land inside the *main*
    # region, not over the background. We translate the user's "in-region"
    # padding (default video_height/12) into canvas-absolute MarginV.
    base_pad = max(40, main_region_h // 12)
    bottom_band = video_height - (main_region_y + main_region_h)
    top_band = main_region_y
    if alignment in (1, 2, 3):  # bottom
        margin_v = base_pad + bottom_band
    elif alignment in (7, 8, 9):  # top
        margin_v = base_pad + top_band
    else:  # middle (5 etc.) — shift toward the main region center
        canvas_center = video_height / 2
        main_center = main_region_y + main_region_h / 2
        margin_v = max(40, int(round(main_center - canvas_center)))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_family},{captions.font_size},{primary},{secondary},{outline},{back},{-1 if preset.bold else 0},{-1 if preset.italic else 0},0,0,100,100,0,0,{preset.border_style},{captions.stroke_width or preset.outline},{preset.shadow},{alignment},80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = (
        _word_events(words, captions, secondary)
        if captions.highlight_mode == HighlightMode.WORD
        else _group_events(words, captions, secondary, group_max_words)
    )

    return header + "\n".join(events) + "\n"


def write_ass_file(
    captions: Captions,
    words: List[TranscriptWord],
    video_width: int,
    video_height: int,
    out_path: str,
    *,
    main_region_y: int = 0,
    main_region_h: Optional[int] = None,
    brand_kit: Optional[BrandKit] = None,
) -> str:
    """Convenience wrapper that writes the ASS body to disk."""
    body = build_ass(
        captions,
        words,
        video_width,
        video_height,
        main_region_y=main_region_y,
        main_region_h=main_region_h,
        brand_kit=brand_kit,
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    return out_path


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------


# Sentinel "spec-default" caption values used to decide whether the user
# has explicitly chosen a color/font. When the value still matches the
# default, the brand kit may override it; once the user picks something
# in the Captions panel, that explicit choice wins over brand kit. This
# matches the policy spelled out in the BrandKitPanel UX text.
_CAPTIONS_DEFAULT_PRIMARY = "#FFFFFF"
_CAPTIONS_DEFAULT_HIGHLIGHT = "#00FF00"
_CAPTIONS_DEFAULT_FONT = "Montserrat"


def _resolve_brand_overrides(
    captions: Captions,
    preset: "_StylePreset",
    brand_kit: Optional[BrandKit],
) -> tuple[str, str, str]:
    """Return ``(primary_color, highlight_color, font_family)`` with the
    brand kit applied on top of the caption preset's defaults.

    Order of precedence (highest first):
      1. Explicit, non-default user choice in ``captions`` (color picker /
         font picker in the Captions panel).
      2. Brand kit value (``brand_kit.primary_color`` → primary,
         ``brand_kit.accent_color`` → highlight,
         ``brand_kit.font_family`` → font).
      3. Caption preset default (``preset.font_family``) or the schema
         default (``captions.color_primary`` / ``color_highlight``).
    """
    # Start with the user/preset values.
    primary = captions.color_primary
    highlight = captions.color_highlight
    font = preset.font_family

    if brand_kit is None:
        return primary, highlight, font

    if brand_kit.primary_color and primary == _CAPTIONS_DEFAULT_PRIMARY:
        primary = brand_kit.primary_color
    if brand_kit.accent_color and highlight == _CAPTIONS_DEFAULT_HIGHLIGHT:
        highlight = brand_kit.accent_color
    if brand_kit.font_family and (
        not captions.font_family or captions.font_family == _CAPTIONS_DEFAULT_FONT
    ):
        font = brand_kit.font_family

    return primary, highlight, font


def _maybe_upper(text: str, upper: bool) -> str:
    return text.upper() if upper else text


def _escape(text: str) -> str:
    """Escape ASS-meaningful characters so user text doesn't break the file."""
    return (
        text.replace("\\", "\\\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", " ")
    )


def _word_with_emoji(w: TranscriptWord, captions: Captions) -> str:
    """Render the word text (with uppercase + escape) plus an optional
    trailing emoji suggested by the suggester. Emoji is appended verbatim
    (not uppercased, never escaped — it's outside the ASS grammar) and
    only when ``captions.emoji_enabled`` is True so the user can flip the
    feature on/off without losing the saved suggestions.
    """
    text = _maybe_upper(_escape(w.text), captions.uppercase)
    if captions.emoji_enabled and w.emoji:
        text = f"{text} {w.emoji}"
    return text


def _word_events(
    words: List[TranscriptWord],
    captions: Captions,
    highlight_color_ass: str,
) -> List[str]:
    """One Dialogue event per word — TikTok pop-in feel."""
    events: List[str] = []
    for w in words:
        text = _word_with_emoji(w, captions)
        # \fad(t1,t2) = fade in over t1ms, fade out over t2ms
        # \1c overrides primary color → use highlight color for the active word
        pop_in = r"{\fad(40,80)\1c" + highlight_color_ass[:10] + "&}"
        events.append(
            f"Dialogue: 0,{_format_ass_time(w.start)},{_format_ass_time(w.end)},"
            f"Default,,0,0,0,,{pop_in}{text}"
        )
    return events


def _group_events(
    words: List[TranscriptWord],
    captions: Captions,
    highlight_color_ass: str,
    group_max_words: int,
) -> List[str]:
    """Phrase-by-phrase Dialogue events. Within each phrase, the currently-
    spoken word can be highlighted using ASS ``\\k`` karaoke timing.

    Phrase boundaries (in order of precedence):
      1. ``force_break_after`` on a word — manual splits/merges win.
      2. ``group_max_words`` cap — keeps phrases readable on small screens.
    Without an explicit ``force_break_after`` we fall back to the cap; an
    explicit ``False`` overrides the cap so the user can build a long phrase.
    """
    events: List[str] = []
    if not words:
        return events

    bucket: List[TranscriptWord] = []
    for w in words:
        bucket.append(w)
        force = w.force_break_after
        if force is True:
            events.append(_build_group_event(bucket, captions, highlight_color_ass))
            bucket = []
            continue
        if force is False:
            # User explicitly merged — never auto-break here.
            continue
        if len(bucket) >= group_max_words:
            events.append(_build_group_event(bucket, captions, highlight_color_ass))
            bucket = []
    if bucket:
        events.append(_build_group_event(bucket, captions, highlight_color_ass))
    return events


def _build_group_event(
    bucket: List[TranscriptWord],
    captions: Captions,
    highlight_color_ass: str,
) -> str:
    start = bucket[0].start
    end = bucket[-1].end
    # \k<csec> = highlight this word for <csec> centiseconds before advancing.
    parts: List[str] = []
    for w in bucket:
        duration_cs = max(1, int((w.end - w.start) * 100))
        word_text = _word_with_emoji(w, captions)
        parts.append(r"{\k" + str(duration_cs) + "}" + word_text)
    text = " ".join(parts)
    fade_tag = r"{\fad(60,60)}"
    return (
        f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end)},"
        f"Default,,0,0,0,,{fade_tag}{text}"
    )


def _empty_ass(video_width: int, video_height: int) -> str:
    """Minimal valid ASS file with no Dialogue lines."""
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,80,80,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
