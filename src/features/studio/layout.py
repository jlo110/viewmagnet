"""Canvas layout math (Week 6 Phase 3).

Pure function for computing where the main video + background-loop regions
sit on the output canvas, given a ``Layout`` spec and canvas dimensions.
Used by:

  - ``src.features.studio.render._cmd_unified`` to position ffmpeg overlay
    + scale filters for each region.
  - ``frontend/client/src/studio/composition/LayoutComposition.tsx`` (via
    a 1:1 TypeScript mirror) so the in-browser preview reads the same
    rectangles.

All math is integer-pixel based so the ffmpeg filter graph never deals
with sub-pixel rectangles (which libx264 rejects with "Width/height not
divisible by 2"). Regions are clamped to even pixel boundaries for the
same reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from src.features.studio.spec import Layout


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle in canvas pixel coordinates (origin top-left)."""

    x: int
    y: int
    w: int
    h: int

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


@dataclass(frozen=True)
class LayoutRegions:
    """Pixel-rect breakdown for a Layout.mode applied to ``canvas_w × canvas_h``.

    ``main`` is always present (every layout displays the user's video).
    ``bg`` is only present for split / pip modes — None for single layout.
    """

    main: Rect
    bg: Optional[Rect]
    canvas_w: int
    canvas_h: int


def _even(n: int) -> int:
    """Snap to nearest even pixel — libx264 requires even dimensions."""
    return max(2, n - (n % 2))


def regions_for(
    layout: Layout,
    canvas_w: int,
    canvas_h: int,
) -> LayoutRegions:
    """Return where the main + (optional) background rectangles sit.

    Modes:
      - ``single``           — main fills the entire canvas; bg is None.
      - ``split_horizontal`` — main on top, bg below. Heights split using
        ``layout.main_weight``.
      - ``split_vertical``   — main on left, bg on right. Widths split.
      - ``pip_corner``       — main fills the canvas, bg is a corner
        inset sized at ``pip_size`` of canvas width (16:9 aspect).
    """
    cw = _even(canvas_w)
    ch = _even(canvas_h)

    if layout.mode == "single":
        return LayoutRegions(
            main=Rect(0, 0, cw, ch),
            bg=None,
            canvas_w=cw,
            canvas_h=ch,
        )

    if layout.mode == "split_horizontal":
        main_h = _even(int(round(ch * layout.main_weight)))
        # Clamp so neither region collapses below 64px — keeps captions /
        # bg visible enough to be useful.
        main_h = max(64, min(ch - 64, main_h))
        bg_h = _even(ch - main_h)
        return LayoutRegions(
            main=Rect(0, 0, cw, main_h),
            bg=Rect(0, main_h, cw, bg_h),
            canvas_w=cw,
            canvas_h=ch,
        )

    if layout.mode == "split_vertical":
        main_w = _even(int(round(cw * layout.main_weight)))
        main_w = max(64, min(cw - 64, main_w))
        bg_w = _even(cw - main_w)
        return LayoutRegions(
            main=Rect(0, 0, main_w, ch),
            bg=Rect(main_w, 0, bg_w, ch),
            canvas_w=cw,
            canvas_h=ch,
        )

    if layout.mode == "pip_corner":
        # PiP is a 16:9 rectangle inset in one corner with a small padding.
        # The main region stays full-canvas behind it.
        pip_w = _even(int(round(cw * layout.pip_size)))
        pip_h = _even(int(round(pip_w * 9 / 16)))
        # Make sure we don't run off the canvas on small aspect ratios.
        pip_w = min(pip_w, cw - 32)
        pip_h = min(pip_h, ch - 32)
        margin = max(8, cw // 64)  # ~1-2% canvas-width padding
        if layout.pip_corner == "tl":
            x, y = margin, margin
        elif layout.pip_corner == "tr":
            x, y = cw - pip_w - margin, margin
        elif layout.pip_corner == "bl":
            x, y = margin, ch - pip_h - margin
        else:  # "br"
            x, y = cw - pip_w - margin, ch - pip_h - margin
        return LayoutRegions(
            main=Rect(0, 0, cw, ch),
            bg=Rect(_even(x), _even(y), pip_w, pip_h),
            canvas_w=cw,
            canvas_h=ch,
        )

    # Forward-compat: unknown mode → behave like single rather than crash.
    return LayoutRegions(
        main=Rect(0, 0, cw, ch),
        bg=None,
        canvas_w=cw,
        canvas_h=ch,
    )


__all__ = ["Rect", "LayoutRegions", "regions_for"]
