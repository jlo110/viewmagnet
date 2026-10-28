"""Tests for the pure helpers in the breakout-classification harness."""
from __future__ import annotations

import numpy as np

from scripts.evaluate_breakout import breakout_labels, early_feature_cols


def test_breakout_labels_top_quartile():
    overperf = np.arange(100, dtype=float)  # 0..99
    y = breakout_labels(overperf, top_q=0.75)
    # Top 25% (values >= the 75th percentile) are breakouts.
    assert y.sum() >= 24 and y.sum() <= 26
    assert y[-1] == 1 and y[0] == 0


def test_breakout_labels_top_decile_is_rarer():
    overperf = np.arange(1000, dtype=float)
    q75 = breakout_labels(overperf, 0.75).sum()
    q90 = breakout_labels(overperf, 0.90).sum()
    assert q90 < q75  # rarer threshold -> fewer positives


def test_early_features_exclude_future_checkpoints():
    # At 1h only 1h-stage features are allowed (no 24h/3d leakage).
    cols = early_feature_cols("1h")
    assert any("_1h" in c for c in cols)
    assert not any(s in c for c in cols for s in ("_6h", "_24h", "_3d"))


def test_early_features_accumulate_with_stage():
    # At 6h, both 1h and 6h features are available, still nothing later.
    cols = early_feature_cols("6h")
    assert any("_1h" in c for c in cols) and any("_6h" in c for c in cols)
    assert not any(s in c for c in cols for s in ("_24h", "_3d", "_7d"))
