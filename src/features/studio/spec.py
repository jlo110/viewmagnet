"""Canonical edit-session spec for the Studio editor.

This Pydantic model is the **single source of truth** for both the
in-browser Remotion preview and the server-side render. The frontend
sends/receives this JSON; the render job consumes it directly.

Versioned so older saved sessions still load when the schema evolves.
"""
from __future__ import annotations

import secrets
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

SPEC_VERSION = 1


def _stable_id() -> str:
    """Short collision-resistant ID for clips, cuts, and other spec children.

    Used so per-boundary transitions (Week 6) survive list reorders that
    would otherwise invalidate index-based references."""
    return secrets.token_hex(6)


# ---------------------------------------------------------------------------
# Enums (constrained string types so the frontend gets autocomplete via OpenAPI)
# ---------------------------------------------------------------------------


class AspectRatio(str, Enum):
    """Supported output aspect ratios."""

    PORTRAIT_9_16 = "9:16"   # TikTok / YT Shorts / Reels
    SQUARE_1_1 = "1:1"       # Instagram feed
    LANDSCAPE_4_5 = "4:5"    # Instagram tall feed
    LANDSCAPE_16_9 = "16:9"  # YouTube / Twitter


class CaptionStyleName(str, Enum):
    """Maps 1:1 to the visual presets in AnimatedCaptions.tsx."""

    CAPCUT = "capcut"
    MRBEAST = "mrbeast"
    HORMOZI = "hormozi"
    NEON = "neon"
    MINIMAL = "minimal"
    BOUNCE = "bounce"
    KARAOKE = "karaoke"


class CaptionPosition(str, Enum):
    """Vertical caption placement."""

    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


class HighlightMode(str, Enum):
    """Whether captions emphasize one word at a time or whole phrase groups."""

    WORD = "word"
    GROUP = "group"


class TransitionType(str, Enum):
    """Transition kinds the renderer + Remotion preview both implement.

    Catalog metadata (label, ffmpeg recipe, SFX file, thumbnail) lives in
    ``src.features.studio.transition_catalog`` — this enum is purely the
    set of valid string values for ``Transitions.type``. Keep these in sync.
    """

    # Basic
    CUT = "cut"
    FADE = "fade"
    DISSOLVE = "dissolve"
    # Slide (``swipe`` kept as legacy alias for "slide left" from Week 5)
    SWIPE = "swipe"
    SLIDE_UP = "slide_up"
    SLIDE_DOWN = "slide_down"
    # Zoom
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    ZOOM_BLUR = "zoom_blur"
    # Glitch
    RGB_SPLIT = "rgb_split"
    GLITCH_SHAKE = "glitch_shake"
    VHS = "vhs"
    # Cinematic
    FLASH_WHITE = "flash_white"
    FADE_TO_BLACK = "fade_to_black"
    WHOOSH = "whoosh"


# ---------------------------------------------------------------------------
# Spec components
# ---------------------------------------------------------------------------


class TranscriptWord(BaseModel):
    """Single word with Whisper-style timing. Mirrored to the frontend so it
    can render karaoke-style word-level highlights and let the user edit text
    without losing alignment.

    ``force_break_after`` overrides the automatic gap-based phrase grouping
    in ``ass_renderer._group_events`` and in the frontend ``CaptionLayer``:
    - ``True``  → next word always starts a new caption phrase (manual split)
    - ``False`` → next word always continues this phrase (manual merge)
    - ``None``  → fall back to the default grouping heuristic

    ``emoji`` is an optional sentiment-appropriate glyph attached to the
    word by the Week 6 emoji_suggester. Rendered as a trailing inline
    span in preview and appended to the karaoke text in the final ASS
    file when ``captions.emoji_enabled`` is True. Storing the emoji on
    the word (rather than mutating ``text``) keeps the toggle reversible
    without re-running the LLM.
    """

    text: str
    start: float = Field(..., description="Seconds from clip start")
    end: float = Field(..., description="Seconds from clip start")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    force_break_after: Optional[bool] = Field(
        default=None,
        description="Manual caption split/merge override. True forces a new "
        "phrase after this word; False forces continuation; None falls back "
        "to the default grouping heuristic.",
    )
    emoji: Optional[str] = Field(
        default=None,
        max_length=12,
        description="Single sentiment emoji to append after this word when "
        "captions.emoji_enabled is True. Populated by the emoji_suggester.",
    )


class SourceClip(BaseModel):
    """The piece of video the session is editing."""

    source_url: str = Field(..., description="YouTube URL or R2 video URL")
    source_clip_path: Optional[str] = Field(
        default=None,
        description="Pre-extracted local/R2 path if shorts pipeline already ran.",
    )
    start_time: float = Field(..., ge=0.0, description="Cut-in time in source (s)")
    end_time: float = Field(..., gt=0.0, description="Cut-out time in source (s)")
    transcript: List[TranscriptWord] = Field(default_factory=list)
    suggested_title: Optional[str] = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)


class Crop(BaseModel):
    """Crop rectangle for vertical / square reframe. ``x``/``y`` are top-left
    corner in source-video pixel space; ``width``/``height`` define the kept
    region. When ``tracking == "smart"`` the render job re-runs SubjectTracker
    to produce dynamic per-frame crop offsets."""

    x: int = Field(..., ge=0)
    y: int = Field(default=0, ge=0)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    tracking: Literal["static", "smart"] = "smart"


class Captions(BaseModel):
    """Caption rendering settings. ``font_size`` is in pixels at 1080p output."""

    enabled: bool = True
    style: CaptionStyleName = CaptionStyleName.CAPCUT
    position: CaptionPosition = CaptionPosition.BOTTOM
    highlight_mode: HighlightMode = HighlightMode.WORD
    font_family: str = "Montserrat"
    font_size: int = Field(default=72, ge=24, le=160)
    color_primary: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    color_highlight: str = Field(default="#00FF00", pattern=r"^#[0-9A-Fa-f]{6}$")
    stroke_width: int = Field(default=4, ge=0, le=20)
    stroke_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    uppercase: bool = False
    emoji_enabled: bool = False


class BRollClip(BaseModel):
    """A B-roll overlay inserted on a secondary timeline track.

    ``id`` is stable across edits — per-boundary transitions reference it
    (rather than list index) so reordering clips doesn't break attached
    transition instances. Auto-generated when missing for back-compat with
    Week 4/5 saves."""

    id: str = Field(default_factory=_stable_id)
    track: int = Field(default=2, ge=2, le=4, description="1=main, 2+=overlays")
    start: float = Field(..., ge=0.0)
    end: float = Field(..., gt=0.0)
    clip_url: str = Field(..., description="Pexels/Pixabay download URL")
    source: Literal["pexels", "pixabay", "upload", "tenor", "giphy"] = "pexels"
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    mute: bool = True
    label: Optional[str] = None


class BRollTrack(BaseModel):
    """Collection of B-roll overlays + auto-pick settings."""

    enabled: bool = True
    auto_suggest: bool = False
    clips: List[BRollClip] = Field(default_factory=list)


class Transitions(BaseModel):
    """Global default transition applied to every boundary.

    Week 6: this is still the source of truth when ``boundary_transitions``
    is empty. The first time a user opens a Week-5 session in the Week-6
    Studio, the spec normalizer expands this single setting into a list of
    per-boundary ``TransitionInstance`` so the user can then tweak each
    boundary individually without losing the original global feel."""

    enabled: bool = False
    type: TransitionType = TransitionType.CUT
    duration_ms: int = Field(default=300, ge=0, le=2000)
    sfx_enabled: bool = False


class TransitionInstance(BaseModel):
    """A transition attached to a single boundary in the timeline (Week 6).

    ``boundary_id`` is one of:
      - ``"broll_<clip.id>_in"``  — clip's leading edge
      - ``"broll_<clip.id>_out"`` — clip's trailing edge
      - ``"camera_cut_<cut.id>"`` — fires at the cut's ``start``

    Per-boundary instances take precedence over the global ``Transitions``
    block. When this list is empty AND ``Transitions.enabled`` is True the
    renderer falls back to applying the global type to every boundary.
    """

    boundary_id: str = Field(..., min_length=3, max_length=80)
    type: TransitionType = TransitionType.CUT
    duration_ms: int = Field(default=300, ge=0, le=2000)
    sfx_enabled: bool = False
    params: Dict[str, Any] = Field(default_factory=dict)


class Layout(BaseModel):
    """Canvas layout mode (Week 6).

    - ``single``           — one region filling the whole canvas (today's behavior).
    - ``split_horizontal`` — two regions stacked top/bottom; main on top, bg below.
    - ``split_vertical``   — two regions side by side; main on left, bg on right.
    - ``pip_corner``       — main fills the canvas, bg shrunk into a corner inset.

    ``main_weight`` controls the split ratio (the fraction of canvas the main
    video occupies; the background fills the rest). ``pip_size`` is the bg
    rectangle's width as a fraction of canvas width when in ``pip_corner``.
    """

    mode: Literal["single", "split_horizontal", "split_vertical", "pip_corner"] = "single"
    pip_corner: Literal["tl", "tr", "bl", "br"] = "br"
    pip_size: float = Field(default=0.30, ge=0.15, le=0.50)
    main_weight: float = Field(default=0.50, ge=0.30, le=0.80)


class BackgroundLoop(BaseModel):
    """A looping video that fills the background region in a multi-region layout.

    Two source flavors:
      - ``catalog`` — references a hand-curated R2-hosted entry in
        ``src.features.studio.background_catalog.FEATURED_LOOPS``.
      - ``pexels`` — points directly at a Pexels download URL the user picked
        from search.

    Audio defaults to silent (``volume=0``) so the voice from the main video
    wins. Loop is shifted by ``loop_start_offset_seconds`` for variety across
    renders of similar sessions."""

    source: Literal["catalog", "pexels"] = "catalog"
    catalog_id: Optional[str] = Field(default=None, max_length=64)
    clip_url: Optional[str] = Field(default=None, max_length=2000)
    loop_start_offset_seconds: float = Field(default=0.0, ge=0.0)
    volume: float = Field(default=0.0, ge=0.0, le=1.0)
    label: Optional[str] = Field(default=None, max_length=120)


class BrandKit(BaseModel):
    """Optional brand asset overlay applied to all renders for this user."""

    logo_url: Optional[str] = None
    logo_position: Literal["tl", "tr", "bl", "br"] = "br"
    logo_opacity: float = Field(default=0.85, ge=0.0, le=1.0)
    primary_color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    font_family: Optional[str] = None


class AutoZoom(BaseModel):
    """Punch-in zoom on LLM-detected punchlines (week 5 wiring)."""

    enabled: bool = False
    max_scale: float = Field(default=1.15, ge=1.0, le=2.0)
    timestamps: List[float] = Field(default_factory=list)


class CameraCut(BaseModel):
    """A single contiguous focus-on-subject segment in the Camera lane.

    ``[start, end]`` are in **clip-local** seconds (matching the timeline /
    Remotion frame clock). ``subject_id`` references one of the IDs in the
    cached tracking payload's ``subjects`` array. ``id`` is stable across
    edits — per-boundary transitions reference it so a reordered cut keeps
    its attached transition."""

    id: str = Field(default_factory=_stable_id)
    start: float = Field(..., ge=0.0)
    end: float = Field(..., gt=0.0)
    subject_id: int = Field(..., ge=0, le=15)


class Camera(BaseModel):
    """Multi-subject "virtual multi-cam" config (Week 4).

    ``tracks`` is an ordered list of ``CameraCut``s. Empty list means the
    Camera feature is dormant and preview/render fall back to ``EditSpec.crop``
    or the centered-aspect default. Non-empty list means: for any time `t`
    inside a cut, the renderer/preview centers the crop on
    ``tracking.subjects[subject_id].smoothed_crop_x[t]``.

    Outside any cut, behavior falls back to the static ``EditSpec.crop``
    (or centered aspect) — same as if ``tracks`` were empty.
    """

    tracks: List[CameraCut] = Field(default_factory=list)
    bbox_overlay_enabled: bool = Field(
        default=False,
        description="When True, the preview overlays a labeled rectangle for "
        "each detected subject so users can click to insert cuts.",
    )
    ease_pan: bool = Field(
        default=False,
        description="When True, transitions between cuts lerp the crop X over "
        "~200ms using a smoothstep. When False (default), the cut is a hard "
        "switch — matches the multi-camera feel of Spikes/Submagic.",
    )
    n_subjects_requested: int = Field(
        default=4,
        ge=1,
        le=8,
        description="How many subjects the tracker should attempt to detect "
        "for this session. Server caches the result keyed on this number.",
    )


# ---------------------------------------------------------------------------
# Top-level spec
# ---------------------------------------------------------------------------


class EditSpec(BaseModel):
    """Complete editor state for one clip. Stored as JSON in
    ``EditSession.spec``; consumed verbatim by the render job and by the
    Remotion ``<Player />`` in the browser."""

    version: int = Field(default=SPEC_VERSION)
    clip: SourceClip
    aspect_ratio: AspectRatio = AspectRatio.PORTRAIT_9_16
    crop: Optional[Crop] = Field(
        default=None,
        description="Required for non-16:9 outputs; backend computes a sensible "
        "default when omitted using SubjectTracker.",
    )
    captions: Captions = Field(default_factory=Captions)
    broll: BRollTrack = Field(default_factory=BRollTrack)
    transitions: Transitions = Field(default_factory=Transitions)
    boundary_transitions: List[TransitionInstance] = Field(
        default_factory=list,
        description="Per-boundary transition overrides (Week 6). When empty, "
        "the global ``transitions`` block applies to every boundary.",
    )
    brand_kit: BrandKit = Field(default_factory=BrandKit)
    auto_zoom: AutoZoom = Field(default_factory=AutoZoom)
    camera: Camera = Field(default_factory=Camera)
    layout: Layout = Field(default_factory=Layout)
    background_loop: Optional[BackgroundLoop] = Field(
        default=None,
        description="Looping video that fills the background region in a "
        "multi-region layout. Null when the layout is ``single`` or when "
        "the user picked a plain solid background.",
    )
    template: Optional[str] = Field(
        default=None,
        description="Preset name like 'podcast', 'tutorial', 'reaction'. When "
        "set, the render job applies the template's defaults before user "
        "overrides — None means fully custom.",
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=10_000,
        description="Free-text creator notes for the clip. Surfaced in "
        "the editor sidebar as a teleprompter / script reference but "
        "doesn't affect rendering. Populated automatically when a clip "
        "is scaffolded from an AI-generated script section (Week 9 "
        "Script-to-Project handoff).",
    )

    def normalize(self) -> "EditSpec":
        """Return a deep copy with derived defaults filled in for Week 6 features.

        Specifically:
          1. Assigns stable ``id``s to any BRollClip / CameraCut loaded from
             older saves that lacked them (Pydantic's ``default_factory``
             already does this — we just need to copy back into the spec).
          2. If ``boundary_transitions`` is empty AND the global
             ``transitions.enabled`` is True, expands the global setting into
             one ``TransitionInstance`` per boundary so the renderer's per-
             boundary path "just works" and the Effects panel can show every
             boundary individually.
        """
        spec = self.model_copy(deep=True)

        if not spec.boundary_transitions and spec.transitions.enabled:
            instances: List[TransitionInstance] = []
            for clip in spec.broll.clips:
                for edge in ("in", "out"):
                    instances.append(
                        TransitionInstance(
                            boundary_id=f"broll_{clip.id}_{edge}",
                            type=spec.transitions.type,
                            duration_ms=spec.transitions.duration_ms,
                            sfx_enabled=spec.transitions.sfx_enabled,
                        )
                    )
            for cut in spec.camera.tracks:
                instances.append(
                    TransitionInstance(
                        boundary_id=f"camera_cut_{cut.id}",
                        type=spec.transitions.type,
                        duration_ms=spec.transitions.duration_ms,
                        sfx_enabled=spec.transitions.sfx_enabled,
                    )
                )
            spec.boundary_transitions = instances

        return spec
