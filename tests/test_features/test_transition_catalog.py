"""Tests for src/features/studio/transition_catalog.py.

The catalog is the single source of truth for visual transitions — both
the ffmpeg-side recipes and the metadata the frontend Effects panel
consumes. This suite verifies:

  - Every TransitionType enum value has a matching catalog entry
  - Every recipe produces a parseable ffmpeg expression for sample ctx
  - SFX filenames + thumbnail filenames are present where promised
  - ``list_for_frontend`` produces JSON-safe rows
"""
from __future__ import annotations

import os
import pytest

from src.features.studio.spec import TransitionType
from src.features.studio.transition_catalog import (
    TRANSITION_CATALOG,
    TransitionDef,
    get_transition,
    list_for_frontend,
)


# ---------------------------------------------------------------------------
# Coverage: every TransitionType has a catalog entry
# ---------------------------------------------------------------------------


def test_every_transition_type_in_catalog():
    """If we add a new TransitionType, the catalog must define it.

    Catches the bug where someone adds a new enum value but forgets to
    wire it up — the renderer would crash mid-render when it tried to
    look up the missing entry.
    """
    catalog_keys = set(TRANSITION_CATALOG.keys())
    enum_values = {t.value for t in TransitionType}
    missing = enum_values - catalog_keys
    extra = catalog_keys - enum_values
    assert not missing, f"TransitionType values not in catalog: {missing}"
    assert not extra, f"Catalog entries with no TransitionType: {extra}"


def test_catalog_size_is_15():
    """Sanity: the Week 6 plan committed to 15 transitions ("lean")."""
    assert len(TRANSITION_CATALOG) == 15


def test_get_transition_returns_def():
    for name in TRANSITION_CATALOG:
        d = get_transition(name)
        assert isinstance(d, TransitionDef)
        assert d.name == name


def test_get_transition_unknown_falls_back_to_cut():
    """Legacy specs with old type names should render as a hard cut rather
    than crashing — get_transition is documented to fall back to 'cut'."""
    d = get_transition("does_not_exist")
    assert d.name == "cut"


# ---------------------------------------------------------------------------
# Metadata sanity
# ---------------------------------------------------------------------------


def test_categories_are_known():
    allowed = {"basic", "slide", "zoom", "glitch", "cinematic"}
    for d in TRANSITION_CATALOG.values():
        assert d.category in allowed, f"{d.name}: unknown category {d.category}"


def test_duration_is_reasonable():
    for d in TRANSITION_CATALOG.values():
        assert 0 <= d.default_duration_ms <= 800, d.name


def test_thumbnail_filenames_are_webm():
    for d in TRANSITION_CATALOG.values():
        assert d.thumbnail.endswith(".webm"), d.name


def test_sfx_files_are_wav_when_present():
    for d in TRANSITION_CATALOG.values():
        if d.sfx_file is not None:
            assert d.sfx_file.endswith(".wav"), d.name


# ---------------------------------------------------------------------------
# Recipe smoke — every entry produces SOMETHING for a typical ctx
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_ctx():
    """Realistic context that every recipe should accept."""
    return {
        "start": 1.0,
        "end": 3.0,
        "win": 2.0,
        "duration_s": 0.3,
        "out_w": 1080,
        "out_h": 1920,
    }


def test_every_recipe_returns_string(sample_ctx):
    """Each callback is required to return a string (possibly empty for cut)."""
    for d in TRANSITION_CATALOG.values():
        assert isinstance(d.broll_filter_extension(sample_ctx), str), d.name
        assert isinstance(d.overlay_x_expr(sample_ctx), str), d.name
        assert isinstance(d.overlay_y_expr(sample_ctx), str), d.name


def test_cut_is_truly_a_noop(sample_ctx):
    """``cut`` should emit no filter chain and no overlay motion."""
    cut = get_transition("cut")
    assert cut.broll_filter_extension(sample_ctx) == ""
    assert cut.overlay_x_expr(sample_ctx) == "0"
    assert cut.overlay_y_expr(sample_ctx) == "0"


def test_recipes_with_zero_duration_no_op(sample_ctx):
    """A 0-duration ctx should produce empty filter strings rather than blow up."""
    ctx = {**sample_ctx, "duration_s": 0.0}
    for d in TRANSITION_CATALOG.values():
        # broll_filter_extension may still return "" — important is that
        # it doesn't crash on a 0-duration request.
        d.broll_filter_extension(ctx)
        d.overlay_x_expr(ctx)
        d.overlay_y_expr(ctx)


@pytest.mark.parametrize("name", list(TRANSITION_CATALOG.keys()))
def test_recipe_no_crash_with_tiny_window(name):
    """A clip window smaller than the requested duration shouldn't crash —
    the recipe clamps duration to ``win * 0.4`` internally."""
    ctx = {
        "start": 0.0,
        "end": 0.2,
        "win": 0.2,
        "duration_s": 0.5,
        "out_w": 720,
        "out_h": 1280,
    }
    d = get_transition(name)
    d.broll_filter_extension(ctx)
    d.overlay_x_expr(ctx)
    d.overlay_y_expr(ctx)


# ---------------------------------------------------------------------------
# Frontend payload
# ---------------------------------------------------------------------------


def test_list_for_frontend_round_trip():
    rows = list_for_frontend()
    assert len(rows) == len(TRANSITION_CATALOG)
    # Each row must serialize to JSON cleanly — values must be primitives.
    import json

    json.dumps(rows)
    # Keys check matches the frontend's ``TransitionInfo`` interface.
    required = {"name", "category", "label", "description", "default_duration_ms", "has_sfx", "thumbnail"}
    for row in rows:
        assert required.issubset(row.keys()), row


# ---------------------------------------------------------------------------
# SFX file presence (best-effort — skip when assets aren't checked in)
# ---------------------------------------------------------------------------


@pytest.fixture
def sfx_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "src",
        "assets",
        "sfx",
    )


def test_sfx_assets_match_catalog(sfx_dir):
    if not os.path.isdir(sfx_dir):
        pytest.skip(f"sfx dir missing at {sfx_dir}")
    for d in TRANSITION_CATALOG.values():
        if d.sfx_file is None:
            continue
        path = os.path.join(sfx_dir, d.sfx_file)
        assert os.path.exists(path), f"{d.name}: sfx file missing {path}"
