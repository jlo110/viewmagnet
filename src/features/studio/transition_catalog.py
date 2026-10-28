"""Transition catalog (Week 6).

Single source of truth for the 15 visual transitions the Studio editor
exposes. Each entry has:

  - ``name``: enum value (matches :class:`TransitionType` in spec.py)
  - ``category``: UI grouping (basic / slide / zoom / glitch / cinematic)
  - ``label`` / ``description``: human-readable for the panel cards
  - ``default_duration_ms``: starting duration the user can tweak
  - ``sfx_file``: filename in ``src/assets/sfx/`` (None = no sting)
  - ``thumbnail``: filename in ``frontend/client/public/transitions/``
  - ``broll_filter_extension(ctx)``: returns extra ffmpeg filter-chain
    segments appended to a B-roll subgraph (after ``trim=duration=``).
    Empty string for transitions that don't need a per-clip filter
    (pure overlay-x sliders, for example).
  - ``overlay_x_expr(ctx)`` / ``overlay_y_expr(ctx)``: x/y for the
    ``overlay=`` filter. ``"0"`` means centered/no motion.

The same name space is mirrored on the frontend in
``frontend/client/src/studio/composition/transitionRecipes.ts`` so the
in-browser preview matches the rendered MP4 frame for frame.

Context dict passed to recipe builders:
    {
        "start": float,    # clip-local seconds where the B-roll begins
        "end":   float,    # clip-local seconds where it ends
        "duration_s": float,  # transition duration (capped at 40% of win)
        "win":   float,    # B-roll window length (end - start)
        "out_w": int,
        "out_h": int,
    }
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# Catalog entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransitionDef:
    name: str
    category: str  # "basic" | "slide" | "zoom" | "glitch" | "cinematic"
    label: str
    description: str
    default_duration_ms: int
    sfx_file: Optional[str]
    thumbnail: str
    # Recipe functions — all default to no-op so simple entries (like "cut")
    # don't need to define them.
    broll_filter_extension: Callable[[Dict[str, Any]], str] = field(
        default=lambda ctx: ""
    )
    overlay_x_expr: Callable[[Dict[str, Any]], str] = field(
        default=lambda ctx: "0"
    )
    overlay_y_expr: Callable[[Dict[str, Any]], str] = field(
        default=lambda ctx: "0"
    )

    def for_frontend(self) -> Dict[str, Any]:
        """JSON-safe view for the GET /studio/transitions endpoint."""
        return {
            "name": self.name,
            "category": self.category,
            "label": self.label,
            "description": self.description,
            "default_duration_ms": self.default_duration_ms,
            "has_sfx": self.sfx_file is not None,
            "thumbnail": self.thumbnail,
        }


# ---------------------------------------------------------------------------
# Filter recipe helpers — keep the common patterns DRY
# ---------------------------------------------------------------------------


def _fade_in_out(ctx: Dict[str, Any], alpha: bool = True) -> str:
    """``fade=in,fade=out`` on the B-roll subgraph alpha channel.

    Used by fade, dissolve, whoosh, vhs, fade-to-black, flash-white — every
    opacity-style transition shares this base. The caller can prepend or
    append extra filters (e.g. ``hue`` for vhs, ``colorlevels`` for flash).
    """
    win = ctx["win"]
    d = min(ctx["duration_s"], max(0.01, win * 0.4))
    if d < 0.01:
        return ""
    fmt = "yuva420p" if alpha else "yuv420p"
    target = ":alpha=1" if alpha else ""
    return (
        f",format={fmt},"
        f"fade=t=in:st=0:d={d:.3f}{target},"
        f"fade=t=out:st={max(0.0, win - d):.3f}:d={d:.3f}{target}"
    )


def _slide_overlay_expr(
    ctx: Dict[str, Any],
    axis: str = "x",
    sign: int = 1,
) -> str:
    """Build an overlay-x or overlay-y expression that slides the clip in
    from off-screen, holds centered, then slides off the opposite side.

    ``axis`` is ``"x"`` (horizontal slide; uses ``out_w`` for distance) or
    ``"y"`` (vertical; uses ``out_h``).
    ``sign``  =  +1 → enters from + edge (right / bottom), exits opposite
                 -1 → enters from - edge (left / top), exits opposite
    """
    s = ctx["start"]
    e = ctx["end"]
    d = min(ctx["duration_s"], max(0.01, (e - s) * 0.4))
    extent = ctx["out_w"] if axis == "x" else ctx["out_h"]
    far = sign * extent  # off-screen "enter from" position
    opp = -sign * extent  # off-screen "exit to"

    return (
        f"'if(lt(t,{s:.3f}),{far},"
        f"if(lt(t,{s + d:.3f}),{far}*(1-(t-{s:.3f})/{d:.3f}),"
        f"if(lt(t,{e - d:.3f}),0,"
        f"if(lt(t,{e:.3f}),{opp}*((t-{e - d:.3f})/{d:.3f}),{opp}))))'"
    )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
#
# Order matches the visual grid in the panel:
#   row 1: basic    — cut, fade, dissolve
#   row 2: slide    — swipe (slide-left), slide_up, slide_down
#   row 3: zoom     — zoom_in, zoom_out, zoom_blur
#   row 4: glitch   — rgb_split, glitch_shake, vhs
#   row 5: cinematic— flash_white, fade_to_black, whoosh
#
# ``swipe`` is kept as the catalog key (and TransitionType enum value) for
# back-compat with sessions saved in Week 5; it is logically the same as
# ``slide_left`` in CapCut's library. The label in the UI says "Slide Left"
# so users see the friendlier name.

TRANSITION_CATALOG: Dict[str, TransitionDef] = {
    # ----- BASIC -----------------------------------------------------------
    "cut": TransitionDef(
        name="cut",
        category="basic",
        label="Cut",
        description="Instant change, no transition.",
        default_duration_ms=0,
        sfx_file=None,
        thumbnail="cut.webm",
    ),
    "fade": TransitionDef(
        name="fade",
        category="basic",
        label="Fade",
        description="Smooth fade in and out.",
        default_duration_ms=250,
        sfx_file="fade.wav",
        thumbnail="fade.webm",
        broll_filter_extension=_fade_in_out,
    ),
    "dissolve": TransitionDef(
        name="dissolve",
        category="basic",
        label="Dissolve",
        description="Cross-dissolve — a longer, softer fade.",
        default_duration_ms=500,
        sfx_file="dissolve.wav",
        thumbnail="dissolve.webm",
        broll_filter_extension=_fade_in_out,
    ),
    # ----- SLIDE -----------------------------------------------------------
    "swipe": TransitionDef(
        name="swipe",
        category="slide",
        label="Slide Left",
        description="Slides in from the right, exits to the left.",
        default_duration_ms=300,
        sfx_file="swipe.wav",
        thumbnail="swipe.webm",
        overlay_x_expr=lambda ctx: _slide_overlay_expr(ctx, "x", +1),
    ),
    "slide_up": TransitionDef(
        name="slide_up",
        category="slide",
        label="Slide Up",
        description="Slides in from the bottom, exits to the top.",
        default_duration_ms=300,
        sfx_file="swipe.wav",
        thumbnail="slide_up.webm",
        overlay_y_expr=lambda ctx: _slide_overlay_expr(ctx, "y", +1),
    ),
    "slide_down": TransitionDef(
        name="slide_down",
        category="slide",
        label="Slide Down",
        description="Slides in from the top, exits to the bottom.",
        default_duration_ms=300,
        sfx_file="swipe.wav",
        thumbnail="slide_down.webm",
        overlay_y_expr=lambda ctx: _slide_overlay_expr(ctx, "y", -1),
    ),
    # ----- ZOOM ------------------------------------------------------------
    "zoom_in": TransitionDef(
        name="zoom_in",
        category="zoom",
        label="Zoom In",
        description="Punches in from small to full-size.",
        default_duration_ms=350,
        sfx_file="zoom.wav",
        thumbnail="zoom_in.webm",
        broll_filter_extension=lambda ctx: _zoom_filter(ctx, mode="in"),
    ),
    "zoom_out": TransitionDef(
        name="zoom_out",
        category="zoom",
        label="Zoom Out",
        description="Pulls back from oversized to full-size.",
        default_duration_ms=350,
        sfx_file="zoom.wav",
        thumbnail="zoom_out.webm",
        broll_filter_extension=lambda ctx: _zoom_filter(ctx, mode="out"),
    ),
    "zoom_blur": TransitionDef(
        name="zoom_blur",
        category="zoom",
        label="Zoom Blur",
        description="Punches in with a radial motion blur edge.",
        default_duration_ms=300,
        sfx_file="zoom.wav",
        thumbnail="zoom_blur.webm",
        broll_filter_extension=lambda ctx: _zoom_filter(ctx, mode="in", blur=True),
    ),
    # ----- GLITCH ----------------------------------------------------------
    "rgb_split": TransitionDef(
        name="rgb_split",
        category="glitch",
        label="RGB Split",
        description="Chromatic aberration edges during the in/out frames.",
        default_duration_ms=200,
        sfx_file="glitch.wav",
        thumbnail="rgb_split.webm",
        broll_filter_extension=lambda ctx: _rgb_split_filter(ctx),
    ),
    "glitch_shake": TransitionDef(
        name="glitch_shake",
        category="glitch",
        label="Glitch Shake",
        description="Quick horizontal jitter as the clip arrives.",
        default_duration_ms=200,
        sfx_file="glitch.wav",
        thumbnail="glitch_shake.webm",
        broll_filter_extension=_fade_in_out,
        overlay_x_expr=lambda ctx: _shake_overlay_expr(ctx, axis="x"),
    ),
    "vhs": TransitionDef(
        name="vhs",
        category="glitch",
        label="VHS",
        description="Hue-shifted retro tape distortion on the entry frames.",
        default_duration_ms=300,
        sfx_file="vhs.wav",
        thumbnail="vhs.webm",
        broll_filter_extension=lambda ctx: _vhs_filter(ctx),
    ),
    # ----- CINEMATIC -------------------------------------------------------
    "flash_white": TransitionDef(
        name="flash_white",
        category="cinematic",
        label="Flash White",
        description="Quick white flash hides the cut.",
        default_duration_ms=200,
        sfx_file="flash.wav",
        thumbnail="flash_white.webm",
        broll_filter_extension=lambda ctx: _flash_filter(ctx, color="white"),
    ),
    "fade_to_black": TransitionDef(
        name="fade_to_black",
        category="cinematic",
        label="Fade to Black",
        description="Fades through black between in and out.",
        default_duration_ms=400,
        sfx_file="fade.wav",
        thumbnail="fade_to_black.webm",
        broll_filter_extension=lambda ctx: _flash_filter(ctx, color="black"),
    ),
    "whoosh": TransitionDef(
        name="whoosh",
        category="cinematic",
        label="Whoosh",
        description="Fast fade paired with a whoosh stinger.",
        default_duration_ms=300,
        sfx_file="whoosh.wav",
        thumbnail="whoosh.webm",
        broll_filter_extension=_fade_in_out,
    ),
}


# ---------------------------------------------------------------------------
# Per-recipe filter helpers (defined below so the catalog above stays readable)
# ---------------------------------------------------------------------------


def _zoom_filter(ctx: Dict[str, Any], *, mode: str, blur: bool = False) -> str:
    """Animate the B-roll's scale during the in/out windows.

    To keep the ffmpeg ``crop`` filter happy (cropping back to
    ``out_w × out_h`` requires the scaled source to be at least that big),
    every z(t) value stays ``>= 1.0`` so we never produce a sub-canvas
    frame.

    ``mode="in"``  → enter 1.5→1.0  hold 1.0  exit 1.0→1.5
                    ("punch into focus, then push back out")
    ``mode="out"`` → enter 1.0→1.5  hold 1.5  exit 1.5→1.0
                    ("pull back, then settle in")
    """
    win = ctx["win"]
    d = min(ctx["duration_s"], max(0.01, win * 0.4))
    w = ctx["out_w"]
    h = ctx["out_h"]
    if d < 0.01:
        return ""

    if mode == "in":
        # enter z = 1.5 → 1.0  ;  hold z = 1.0  ;  exit z = 1.0 → 1.5
        z_expr = (
            f"if(lt(t,{d:.3f}),1.5-0.5*(t/{d:.3f}),"
            f"if(lt(t,{win - d:.3f}),1.0,"
            f"1.0+0.5*((t-{win - d:.3f})/{d:.3f})))"
        )
    else:
        # enter z = 1.0 → 1.5  ;  hold z = 1.5  ;  exit z = 1.5 → 1.0
        z_expr = (
            f"if(lt(t,{d:.3f}),1.0+0.5*(t/{d:.3f}),"
            f"if(lt(t,{win - d:.3f}),1.5,"
            f"1.5-0.5*((t-{win - d:.3f})/{d:.3f})))"
        )

    # Alpha fades alongside so the edges of the zoomed clip don't snap.
    alpha = (
        f",format=yuva420p,"
        f"fade=t=in:st=0:d={d:.3f}:alpha=1,"
        f"fade=t=out:st={max(0.0, win - d):.3f}:d={d:.3f}:alpha=1"
    )

    # Scale + center-crop. trunc(..)/2*2 keeps the dimensions even (libx264).
    new_w = f"trunc({w}*({z_expr})/2)*2"
    new_h = f"trunc({h}*({z_expr})/2)*2"
    scale_seg = (
        f",scale=w='{new_w}':h='{new_h}':eval=frame:flags=lanczos,"
        f"crop={w}:{h}:(iw-{w})/2:(ih-{h})/2"
    )

    blur_seg = ""
    if blur:
        # ffmpeg's boxblur doesn't accept time-varying expressions in this
        # build, so we apply a constant low-radius blur over the whole clip.
        # The transition feel comes from the zoom-scale animation + alpha
        # fades; the blur reads as motion smear during the punch frames
        # because the source is also scaling fast at the edges.
        blur_seg = ",boxblur=lr=2:lp=1"

    return alpha + scale_seg + blur_seg


def _shake_overlay_expr(ctx: Dict[str, Any], *, axis: str = "x") -> str:
    """Jitter the overlay position during the in/out windows.

    Combines with ``_fade_in_out`` for a "glitch shake" feel. Uses sin()
    at a high frequency so the motion reads as jitter, not smooth pan.
    """
    s = ctx["start"]
    e = ctx["end"]
    d = min(ctx["duration_s"], max(0.01, (e - s) * 0.4))
    AMP = 30  # pixels of peak jitter
    FREQ = 25  # Hz
    # Active during [s, s+d] ∪ [e-d, e], otherwise 0.
    jitter = f"({AMP}*sin(2*PI*{FREQ}*(t-{s:.3f})))"
    decay_in = f"(1-(t-{s:.3f})/{d:.3f})"
    decay_out = f"((t-{e - d:.3f})/{d:.3f})"
    return (
        f"'if(lt(t,{s:.3f}),0,"
        f"if(lt(t,{s + d:.3f}),{jitter}*{decay_in},"
        f"if(lt(t,{e - d:.3f}),0,"
        f"if(lt(t,{e:.3f}),{jitter}*{decay_out},0))))'"
    )


def _rgb_split_filter(ctx: Dict[str, Any]) -> str:
    """Chromatic-aberration tint — uniform red/blue separation across the clip.

    ffmpeg's ``colorbalance`` filter doesn't support time-varying expressions,
    so the chromatic shift is constant over the B-roll's lifetime. The
    transition feel comes from the paired alpha fade on the in/out windows —
    the user sees a glitchy-tinted clip wash in and out instead of the plain
    fade.
    """
    win = ctx["win"]
    d = min(ctx["duration_s"], max(0.01, win * 0.4))
    if d < 0.01:
        return ""
    return (
        f",format=yuva420p,"
        f"fade=t=in:st=0:d={d:.3f}:alpha=1,"
        f"fade=t=out:st={max(0.0, win - d):.3f}:d={d:.3f}:alpha=1,"
        f"colorbalance=rs=0.30:bs=-0.30"
    )


def _vhs_filter(ctx: Dict[str, Any]) -> str:
    """Retro VHS hue-shift over the entire B-roll clip (constant intensity).

    Older ffmpeg builds don't expose ``hue=eval=frame``, so we apply a fixed
    hue rotation + saturation bump for the whole clip. The transition feel
    comes from the alpha fades at the edges — the user sees a hue-shifted,
    saturation-boosted clip wash in and out.
    """
    win = ctx["win"]
    d = min(ctx["duration_s"], max(0.01, win * 0.4))
    if d < 0.01:
        return ""
    return (
        f",format=yuva420p,"
        f"fade=t=in:st=0:d={d:.3f}:alpha=1,"
        f"fade=t=out:st={max(0.0, win - d):.3f}:d={d:.3f}:alpha=1,"
        f"hue=h=25:s=1.30"
    )


def _flash_filter(ctx: Dict[str, Any], *, color: str) -> str:
    """White or black flash by ramping brightness over the in/out window.

    For ``color="white"`` we bump brightness toward 1; for ``color="black"``
    we drop toward -1. Pure ffmpeg-side — no extra inputs required.
    """
    win = ctx["win"]
    d = min(ctx["duration_s"], max(0.01, win * 0.4))
    if d < 0.01:
        return ""
    sign = 1.0 if color == "white" else -1.0
    env = (
        f"if(lt(t,{d:.3f}),1-(t/{d:.3f}),"
        f"if(lt(t,{win - d:.3f}),0,(t-{win - d:.3f})/{d:.3f}))"
    )
    return (
        f",format=yuva420p,"
        f"fade=t=in:st=0:d={d:.3f}:alpha=1,"
        f"fade=t=out:st={max(0.0, win - d):.3f}:d={d:.3f}:alpha=1,"
        f"eq=brightness='{sign}*({env})':eval=frame"
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_transition(name: str) -> TransitionDef:
    """Return the catalog entry for ``name``; defaults to "cut" on unknown
    so legacy specs with old type names render as a hard cut rather than
    crashing the render job."""
    return TRANSITION_CATALOG.get(name) or TRANSITION_CATALOG["cut"]


def list_for_frontend() -> List[Dict[str, Any]]:
    """JSON-serializable list ordered by category then default order. The
    GET /studio/transitions endpoint returns this verbatim."""
    return [tdef.for_frontend() for tdef in TRANSITION_CATALOG.values()]


__all__ = [
    "TRANSITION_CATALOG",
    "TransitionDef",
    "get_transition",
    "list_for_frontend",
]
