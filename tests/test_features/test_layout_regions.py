"""Tests for src/features/studio/layout.py — pure region math.

The layout function is the single source of truth for where the main
video + background loop sit on the rendered canvas, so this suite exercises
every mode + edge case so that ffmpeg overlays in render.py don't drift
from the in-browser preview.
"""
from __future__ import annotations

import pytest

from src.features.studio.layout import LayoutRegions, Rect, regions_for
from src.features.studio.spec import Layout


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _layout(**overrides) -> Layout:
    """Construct a Layout with sensible defaults for tests."""
    base = {
        "mode": "single",
        "pip_corner": "br",
        "pip_size": 0.30,
        "main_weight": 0.50,
    }
    base.update(overrides)
    return Layout(**base)


# ---------------------------------------------------------------------------
# Single mode
# ---------------------------------------------------------------------------


class TestSingleMode:
    def test_main_fills_canvas(self):
        r = regions_for(_layout(mode="single"), 1080, 1920)
        assert r.main == Rect(0, 0, 1080, 1920)
        assert r.bg is None

    def test_even_pixel_clamp(self):
        # Odd width gets snapped down to even — libx264 requirement.
        r = regions_for(_layout(mode="single"), 1081, 1921)
        assert r.main.w % 2 == 0
        assert r.main.h % 2 == 0
        assert r.canvas_w == 1080
        assert r.canvas_h == 1920


# ---------------------------------------------------------------------------
# Split horizontal — main top, bg bottom
# ---------------------------------------------------------------------------


class TestSplitHorizontal:
    def test_default_split_50_50(self):
        r = regions_for(_layout(mode="split_horizontal", main_weight=0.5), 1080, 1920)
        assert r.main.x == 0 and r.main.y == 0 and r.main.w == 1080
        assert r.bg is not None
        assert r.bg.x == 0 and r.bg.y == r.main.h
        assert r.main.h + r.bg.h == 1920

    def test_unequal_split(self):
        r = regions_for(_layout(mode="split_horizontal", main_weight=0.7), 1080, 1920)
        assert r.main.h > 1920 / 2
        assert r.bg is not None and r.bg.h < 1920 / 2
        assert r.main.h + r.bg.h == 1920

    def test_min_clamp_prevents_collapse(self):
        """Tiny main_weight still leaves at least 64px so captions remain visible."""
        r = regions_for(_layout(mode="split_horizontal", main_weight=0.30), 200, 200)
        assert r.main.h >= 64
        assert r.bg is not None and r.bg.h >= 64

    def test_even_heights(self):
        r = regions_for(_layout(mode="split_horizontal", main_weight=0.55), 1080, 1920)
        assert r.main.h % 2 == 0
        assert r.bg is not None and r.bg.h % 2 == 0


# ---------------------------------------------------------------------------
# Split vertical — main left, bg right
# ---------------------------------------------------------------------------


class TestSplitVertical:
    def test_default_split(self):
        r = regions_for(_layout(mode="split_vertical", main_weight=0.5), 1920, 1080)
        assert r.main.x == 0 and r.main.y == 0 and r.main.h == 1080
        assert r.bg is not None
        assert r.bg.x == r.main.w and r.bg.y == 0
        assert r.main.w + r.bg.w == 1920

    def test_main_clamped_low(self):
        r = regions_for(_layout(mode="split_vertical", main_weight=0.30), 1920, 1080)
        # 0.30 * 1920 = 576 → above the 64-min clamp
        assert r.main.w == 576
        assert r.bg is not None and r.bg.w == 1920 - 576

    def test_even_widths(self):
        r = regions_for(_layout(mode="split_vertical", main_weight=0.45), 1080, 1920)
        assert r.main.w % 2 == 0
        assert r.bg is not None and r.bg.w % 2 == 0


# ---------------------------------------------------------------------------
# PiP corner — main full, bg corner inset (16:9)
# ---------------------------------------------------------------------------


class TestPipCorner:
    def test_default_br_corner(self):
        r = regions_for(_layout(mode="pip_corner", pip_corner="br", pip_size=0.30), 1080, 1920)
        # Main fills the entire canvas.
        assert r.main == Rect(0, 0, 1080, 1920)
        assert r.bg is not None
        # PiP is 16:9, anchored bottom-right with a margin.
        assert r.bg.w == pytest.approx(int(1080 * 0.30), abs=2)
        assert r.bg.h == pytest.approx(int(r.bg.w * 9 / 16), abs=2)
        # Bottom-right placement.
        assert r.bg.x > 1080 / 2
        assert r.bg.y > 1920 / 2

    @pytest.mark.parametrize("corner,expected_quadrant", [
        ("tl", "top-left"),
        ("tr", "top-right"),
        ("bl", "bottom-left"),
        ("br", "bottom-right"),
    ])
    def test_corner_placement(self, corner, expected_quadrant):
        r = regions_for(_layout(mode="pip_corner", pip_corner=corner, pip_size=0.25), 1080, 1920)
        assert r.bg is not None
        cx = r.bg.x + r.bg.w / 2
        cy = r.bg.y + r.bg.h / 2
        if "left" in expected_quadrant:
            assert cx < 1080 / 2
        else:
            assert cx > 1080 / 2
        if "top" in expected_quadrant:
            assert cy < 1920 / 2
        else:
            assert cy > 1920 / 2

    def test_pip_doesnt_overflow_canvas(self):
        # Large pip_size on a small canvas should still keep the bg inside.
        r = regions_for(_layout(mode="pip_corner", pip_size=0.50), 320, 568)
        assert r.bg is not None
        assert r.bg.x + r.bg.w <= 320
        assert r.bg.y + r.bg.h <= 568

    def test_pip_even_dimensions(self):
        r = regions_for(_layout(mode="pip_corner", pip_size=0.33), 1080, 1920)
        assert r.bg is not None
        assert r.bg.w % 2 == 0
        assert r.bg.h % 2 == 0
        assert r.bg.x % 2 == 0
        assert r.bg.y % 2 == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_landscape_canvas_split_horizontal(self):
        # 16:9 canvas should still split correctly.
        r = regions_for(_layout(mode="split_horizontal", main_weight=0.6), 1920, 1080)
        assert r.main.w == 1920
        assert r.main.h + (r.bg.h if r.bg else 0) == 1080

    def test_layout_regions_is_immutable(self):
        # Dataclass is frozen — mutation should fail (catches regressions
        # where someone accidentally drops the ``frozen=True``).
        r = regions_for(_layout(mode="single"), 100, 200)
        with pytest.raises((AttributeError, TypeError)):
            r.main = Rect(0, 0, 1, 1)  # type: ignore[misc]

    def test_rect_as_tuple(self):
        rect = Rect(10, 20, 100, 200)
        assert rect.as_tuple() == (10, 20, 100, 200)
