"""Tests for model-drift detection (Phase 3.2)."""
from src.ml.drift import (
    DriftReport,
    detect_drift,
    evaluate_backtest_drift,
)


def test_stable_metric_no_drift():
    r = detect_drift(0.52, 0.50)  # +4% — within noise
    assert r.drifted is False and r.severity == "none"


def test_warn_threshold():
    r = detect_drift(0.60, 0.50)  # +20%
    assert r.drifted is True and r.severity == "warn"


def test_alert_threshold():
    r = detect_drift(0.70, 0.50)  # +40%
    assert r.drifted is True and r.severity == "alert"


def test_improvement_is_not_drift():
    r = detect_drift(0.40, 0.50)  # error dropped — good
    assert r.drifted is False and r.severity == "none"
    assert r.relative_change < 0


def test_zero_reference_is_safe():
    r = detect_drift(0.5, 0.0)
    assert r.drifted is False  # no division blow-up


def test_evaluate_falls_back_to_best_baseline_when_no_model():
    rows = [{
        "horizon": "1h->6h",
        "baseline_persist_mape": 0.80,
        "baseline_growth_mape": 0.60,  # best baseline = 0.60
    }]
    # reference says this horizon used to be 0.45 → +33% degradation → alert
    out = evaluate_backtest_drift(rows, {"1h->6h": 0.45})
    assert len(out) == 1 and out[0].severity == "alert"


def test_evaluate_skips_horizons_without_reference():
    rows = [{"horizon": "new->later", "model_mape": 0.9}]
    assert evaluate_backtest_drift(rows, {"1h->6h": 0.5}) == []


def test_report_summary_counts():
    rows = [
        {"horizon": "a", "model_mape": 0.70},  # vs 0.50 ref → alert
        {"horizon": "b", "model_mape": 0.58},  # vs 0.50 ref → warn
        {"horizon": "c", "model_mape": 0.50},  # vs 0.50 ref → none
    ]
    ref = {"a": 0.50, "b": 0.50, "c": 0.50}
    report = DriftReport(evaluate_backtest_drift(rows, ref))
    s = report.summary()
    assert report.drifted is True
    assert s["n_alerts"] == 1 and s["n_warnings"] == 1
    assert s["horizons_checked"] == 3
