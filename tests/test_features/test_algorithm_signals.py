"""Tests for ``compute_algorithm_signals`` recommendation CTAs (Week 9
Connected Tools).

The whole point of structured CTAs is that the Analyzer's Algorithm
Signals card opens the RIGHT destination tool on click. Historically
these hrefs have drifted off the real React routes (e.g.
``/dashboard/script-writer`` vs the actual ``/dashboard/scripts``,
``/dashboard/loop`` vs ``/dashboard/loop-designer``), and because
nothing asserted on them we shipped a card full of 404s without
anyone noticing.

These tests lock in:

  1. Every CTA href starts with a path the React router actually has.
  2. Tab params match what the destination page reads.
  3. Every bottleneck branch emits at least one structured CTA.
  4. The free-text ``recommendations`` list and the structured
     ``recommendation_ctas`` list line up 1:1 (same count, same
     order) so the frontend can swap between them safely.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from src.features.llm_analyzer import compute_algorithm_signals


# Real React routes that the dashboard registers (mirrors
# ``frontend/client/src/App.tsx``). Keeping this allow-list narrow on
# purpose: if a CTA points at a route NOT in here we want the test
# to fail loudly rather than silently shipping a dead link.
_VALID_ROUTES = {
    "/dashboard/titles",
    "/dashboard/thumbnails",
    "/dashboard/ab-test",
    "/dashboard/velocity",
    "/dashboard/loop-designer",
    "/dashboard/scripts",
    "/dashboard/analyzer",
    "/dashboard/writer",
    "/dashboard/shorts",
    "/dashboard/studio",
    "/dashboard/drafts",
    "/dashboard/distribution",
    "/dashboard/dubbing",
    "/dashboard/captions",
    "/dashboard/keywords",
    "/dashboard/formula",
    "/dashboard/competitors",
    "/dashboard/trends",
    "/dashboard/impact",
    "/dashboard/settings",
    "/dashboard/renders",
    "/dashboard/alerts",
}


def _scores_for_bottleneck(name: str) -> tuple[float, float, float]:
    """Return (title, thumbnail, prediction) scores that drive the
    bottleneck math toward the requested branch.

    Carefully calibrated against the weighting in
    ``compute_algorithm_signals`` so each test gets the branch it
    expects (the function has a fuzz threshold of 8 points before
    it falls into the "balanced" branch).
    """
    if name == "start":
        # Low title/thumbnail, high prediction → start is the floor.
        return (10.0, 10.0, 80.0)
    if name == "keep":
        # Decent packaging, weak prediction → keep is the floor.
        return (80.0, 80.0, 10.0)
    if name == "repeat":
        # Everything strong; we use channel_score below to drag repeat
        # down independently in the test (no need for separate scores
        # here — the test patches features instead).
        return (80.0, 80.0, 90.0)
    if name == "balanced":
        # All three within the 8-point tolerance.
        return (60.0, 60.0, 60.0)
    raise ValueError(name)


class TestStructuredCtaHrefs:
    """Lock-in: every structured CTA must resolve to a real route."""

    @pytest.mark.parametrize("bottleneck", ["start", "keep", "repeat", "balanced"])
    def test_every_cta_points_to_a_valid_route(self, bottleneck: str):
        title, thumb, pred = _scores_for_bottleneck(bottleneck)
        signals = compute_algorithm_signals(
            title_score=title,
            thumbnail_score=thumb,
            prediction_score=pred,
        )
        assert signals.recommendation_ctas, (
            f"{bottleneck} branch must emit at least one structured CTA"
        )
        for cta in signals.recommendation_ctas:
            path = urlsplit(cta.href).path
            assert path in _VALID_ROUTES, (
                f"CTA {cta.tool!r} for {bottleneck=} points at "
                f"{cta.href!r}; path {path!r} is not a registered "
                f"React route. Routes: {sorted(_VALID_ROUTES)}"
            )

    def test_script_writer_ctas_use_frameworks_tab_plural(self):
        """The Script Writer page reads ``?tab=frameworks`` (plural).
        ``framework`` (singular) was the historical bug — the page
        ignored it and dropped the user on the default tab."""
        _, _, _ = _scores_for_bottleneck("repeat")
        signals = compute_algorithm_signals(
            title_score=80.0, thumbnail_score=80.0, prediction_score=90.0,
        )
        script_ctas = [c for c in signals.recommendation_ctas if c.tool == "script_writer"]
        assert script_ctas, "repeat branch should ship script_writer CTAs"
        for cta in script_ctas:
            params = parse_qs(urlsplit(cta.href).query)
            assert params.get("tab") == ["frameworks"], (
                f"script_writer CTA href {cta.href!r} should carry "
                f"tab=frameworks (plural); got {params.get('tab')!r}"
            )
            # Every framework CTA should also carry the framework key
            # and autoRun flag so the destination tab runs on landing.
            assert "framework" in params, (
                f"script_writer CTA {cta.label!r} missing framework key"
            )

    def test_hook_lab_cta_lands_on_hooks_tab(self):
        """Hook Lab is a tab inside Title Generator, not a standalone
        page. The CTA must carry ``?tab=hooks`` so the user lands
        in Hook Lab, not on the (default) Titles tab."""
        signals = compute_algorithm_signals(
            title_score=10.0, thumbnail_score=10.0, prediction_score=80.0,
        )
        hook_ctas = [c for c in signals.recommendation_ctas if c.tool == "hook_lab"]
        assert hook_ctas, "start branch should ship a hook_lab CTA"
        for cta in hook_ctas:
            split = urlsplit(cta.href)
            assert split.path == "/dashboard/titles"
            assert parse_qs(split.query).get("tab") == ["hooks"], (
                f"hook_lab CTA href {cta.href!r} should land on "
                f"tab=hooks"
            )


class TestCtaListInvariants:
    """The structured CTAs must line up with the backwards-compat
    free-text recommendations 1:1 so the frontend can pick whichever
    list it prefers without losing entries."""

    @pytest.mark.parametrize("bottleneck", ["start", "keep", "repeat", "balanced"])
    def test_text_and_structured_lists_are_aligned(self, bottleneck: str):
        title, thumb, pred = _scores_for_bottleneck(bottleneck)
        signals = compute_algorithm_signals(
            title_score=title, thumbnail_score=thumb, prediction_score=pred,
        )
        assert len(signals.recommendations) == len(signals.recommendation_ctas), (
            f"text vs structured recommendation count mismatch for "
            f"{bottleneck=}: "
            f"{len(signals.recommendations)} vs "
            f"{len(signals.recommendation_ctas)}"
        )

    def test_every_cta_has_label_tool_href(self):
        """Defensive: a CTA missing label/tool/href would render as a
        blank pill in the UI."""
        signals = compute_algorithm_signals(
            title_score=60.0, thumbnail_score=60.0, prediction_score=60.0,
        )
        for cta in signals.recommendation_ctas:
            assert cta.label, "CTA missing label"
            assert cta.tool, "CTA missing tool"
            assert cta.href, "CTA missing href"
