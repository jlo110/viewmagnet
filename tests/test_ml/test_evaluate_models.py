"""Unit tests for the pure helpers in ``scripts.evaluate_models``.

These verify the metric, baseline, and lift math without touching a database,
so the evaluation logic is trustworthy before it's ever run against real data.
"""
import numpy as np
import pytest

from scripts.evaluate_models import lift, mape, naive_persistence, r2


class TestMape:
    def test_perfect_prediction_is_zero(self):
        y = np.array([100.0, 200.0, 300.0])
        assert mape(y, y) == pytest.approx(0.0)

    def test_known_value(self):
        # 10% off on every row → 10% MAPE.
        y_true = np.array([100.0, 200.0])
        y_pred = np.array([110.0, 220.0])
        assert mape(y_true, y_pred) == pytest.approx(10.0)

    def test_ignores_zero_truth_rows(self):
        # The zero-truth row would divide-by-zero; it must be skipped.
        y_true = np.array([0.0, 100.0])
        y_pred = np.array([50.0, 100.0])
        assert mape(y_true, y_pred) == pytest.approx(0.0)

    def test_all_zero_truth_is_nan(self):
        assert np.isnan(mape(np.array([0.0, 0.0]), np.array([1.0, 2.0])))


class TestR2:
    def test_perfect_is_one(self):
        y = np.array([1.0, 2.0, 3.0, 4.0])
        assert r2(y, y) == pytest.approx(1.0)

    def test_mean_predictor_is_zero(self):
        y = np.array([1.0, 2.0, 3.0, 4.0])
        pred = np.full_like(y, y.mean())
        assert r2(y, pred) == pytest.approx(0.0)


class TestNaivePersistence:
    def test_pure_persistence_returns_input(self):
        v = np.array([10.0, 20.0])
        assert np.allclose(naive_persistence(v, 1.0), v)

    def test_growth_multiplier(self):
        v = np.array([10.0, 20.0])
        assert np.allclose(naive_persistence(v, 1.5), [15.0, 30.0])


class TestLift:
    def test_model_beats_baseline_is_positive(self):
        # baseline 40% MAPE, model 20% → 0.5 lift.
        assert lift(40.0, 20.0) == pytest.approx(0.5)

    def test_model_equals_baseline_is_zero(self):
        assert lift(30.0, 30.0) == pytest.approx(0.0)

    def test_model_worse_than_baseline_is_negative(self):
        assert lift(20.0, 30.0) == pytest.approx(-0.5)

    def test_zero_baseline_is_nan(self):
        assert np.isnan(lift(0.0, 10.0))


def test_persistence_baseline_is_strong_for_autocorrelated_target():
    """Demonstrates the harness's core point: when the target barely changes
    from the input (high autocorrelation), pure persistence already has a low
    MAPE — so a model must be measured by *lift*, not raw MAPE/R²."""
    rng = np.random.default_rng(0)
    views_from = rng.uniform(1_000, 100_000, size=500)
    # day-30 ≈ day-14 * ~1.05 with small noise.
    y_true = views_from * rng.normal(1.05, 0.03, size=500)
    baseline_mape = mape(y_true, naive_persistence(views_from, 1.0))
    # Persistence alone should already be within a few percent.
    assert baseline_mape < 8.0
