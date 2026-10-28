"""Tests for the breakout detector engine (remediation 7.3)."""
from __future__ import annotations

import math

from src.features.breakout_detector import (
    BreakoutCalibrator,
    assess,
    breakout_score,
    classify,
    rank_breakouts,
)


def test_breakout_score_is_log_gap():
    # A video at e^2-1 views vs a channel baseline of 1.0 log-views.
    s = breakout_score(math.expm1(2.0), 1.0)
    assert abs(s - 1.0) < 1e-9


def test_breakout_score_floors_negative_views():
    assert breakout_score(-5, 0.0) == 0.0  # log1p(0)


def test_classify_bands():
    assert classify(0.85) == "breakout"
    assert classify(0.50) == "heating_up"
    assert classify(0.10) == "normal"
    assert classify(float("nan")) == "unknown"


def test_calibrator_interpolates_and_clips():
    cal = BreakoutCalibrator(x=[-1.0, 0.0, 1.0, 2.0], y=[0.0, 0.25, 0.7, 0.95], meta={})
    assert abs(cal.probability(0.0) - 0.25) < 1e-9
    assert abs(cal.probability(0.5) - 0.475) < 1e-9   # midpoint interp
    # Out of range clips to the endpoints.
    assert cal.probability(-5.0) == 0.0
    assert cal.probability(9.0) == 0.95


def test_calibrator_roundtrip(tmp_path):
    cal = BreakoutCalibrator(x=[0.0, 1.0], y=[0.2, 0.8], meta={"from_cp": "6h"})
    p = tmp_path / "cal.json"
    cal.save(p)
    loaded = BreakoutCalibrator.load(p)
    assert loaded is not None
    assert loaded.x == [0.0, 1.0] and loaded.meta["from_cp"] == "6h"
    assert abs(loaded.probability(0.5) - 0.5) < 1e-9


def test_load_missing_returns_none(tmp_path):
    assert BreakoutCalibrator.load(tmp_path / "nope.json") is None


def test_assess_with_calibrator():
    cal = BreakoutCalibrator(x=[0.0, 1.0, 2.0], y=[0.2, 0.6, 0.9], meta={})
    a = assess(views=math.expm1(2.5), baseline_log_views=0.5, calibrator=cal)
    assert a.score > 0  # 2.5 - 0.5 = 2.0 ahead
    assert a.probability == 0.9 and a.level == "breakout"


def test_assess_without_calibrator_uses_score_fallback():
    a = assess(views=math.expm1(2.0), baseline_log_views=0.5, calibrator=None)
    assert a.probability is None
    assert a.level == "breakout"  # score 1.5 >= 1.2


def _rows():
    # (video_id, channel_id, title, views, age_hours)
    # Channel A: 4 small videos (~1k) + one spike (50k) -> the spike breaks out.
    rows = [
        ("a1", "A", "small1", 1000, 10),
        ("a2", "A", "small2", 1200, 10),
        ("a3", "A", "small3", 900, 10),
        ("a4", "A", "small4", 1100, 10),
        ("aSPIKE", "A", "spike", 50000, 8),
        # Channel B: only 2 videos -> below min_channel_videos, skipped.
        ("b1", "B", "b1", 80000, 6),
        ("b2", "B", "b2", 1000, 6),
        # tiny absolute views -> below min_views even if channel-relative high.
        ("a5tiny", "A", "tiny", 30, 6),
    ]
    return rows


def test_rank_breakouts_gates_and_ranks():
    cal = BreakoutCalibrator(x=[0.0, 1.0, 3.0], y=[0.1, 0.6, 0.94], meta={})
    res = rank_breakouts(_rows(), "6h", cal, min_probability=0.5, min_views=1000, min_channel_videos=3)
    ids = [r["video_id"] for r in res]
    # The 50k spike on channel A is the breakout; tiny + channel-B (too few vids) excluded.
    assert "aSPIKE" in ids
    assert "a5tiny" not in ids       # below min_views
    assert "b1" not in ids           # channel B has < 3 videos
    # Small in-norm A videos shouldn't clear the probability bar.
    assert "a1" not in ids


def test_calibrator_path_per_checkpoint():
    from pathlib import Path

    from src.features.breakout_detector import DEFAULT_CALIBRATOR, calibrator_path

    assert calibrator_path("6h") == DEFAULT_CALIBRATOR  # legacy name kept
    assert calibrator_path("1h") == Path("data/models/breakout_calibrator_1h.json")


def test_detection_confidence_by_niche():
    from src.features.breakout_detector import detection_confidence

    assert detection_confidence("25")["confidence"] == "high"      # News 0.958
    assert detection_confidence("20")["confidence"] == "lower"     # Gaming 0.843
    assert detection_confidence("27")["confidence"] == "moderate"  # Education 0.873
    # unknown/missing -> global fallback
    fb = detection_confidence(None)
    assert fb["detection_auc"] == 0.933 and fb["confidence"] == "high"


def test_rank_breakouts_min_views_floor():
    cal = BreakoutCalibrator(x=[0.0, 5.0], y=[0.5, 0.99], meta={})
    rows = [("x", "C", "t", 50, 5), ("y", "C", "t", 60, 5), ("z", "C", "t", 70, 5)]
    # All below the 1000 floor → nothing returned even with a generous calibrator.
    assert rank_breakouts(rows, "6h", cal, min_probability=0.0, min_views=1000) == []
