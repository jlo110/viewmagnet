"""Tests for src.features.billing.render_budget.

The DB layer is mocked so every test is hermetic and runs without a
live database.  The full integration (DB upsert + read) is covered by
the studio render-budget API tests.
"""
from __future__ import annotations

import math
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

import src.features.billing.render_budget as rb


# ---------------------------------------------------------------------------
# budget_for_plan
# ---------------------------------------------------------------------------

class TestBudgetForPlan:
    @pytest.mark.parametrize("plan,expected", [
        ("free", 30.0),
        ("starter", 300.0),
        ("pro", math.inf),
        ("agency", math.inf),
        ("enterprise", math.inf),   # legacy alias
    ])
    def test_known_plans(self, plan, expected):
        assert rb.budget_for_plan(plan) == expected

    def test_unknown_plan_defaults_to_free(self):
        assert rb.budget_for_plan("hobbyist") == 30.0

    def test_none_plan_defaults_to_free(self):
        assert rb.budget_for_plan(None) == 30.0

    def test_empty_string_defaults_to_free(self):
        assert rb.budget_for_plan("") == 30.0


# ---------------------------------------------------------------------------
# estimate_render_minutes
# ---------------------------------------------------------------------------

class TestEstimateRenderMinutes:
    @pytest.mark.parametrize("secs,expected", [
        (60.0, 1.0),
        (30.0, 0.5),
        (120.0, 2.0),
    ])
    def test_converts_correctly(self, secs, expected):
        assert abs(rb.estimate_render_minutes(secs) - expected) < 1e-9

    def test_zero_returns_zero(self):
        assert rb.estimate_render_minutes(0) == 0.0

    def test_negative_returns_zero(self):
        assert rb.estimate_render_minutes(-5.0) == 0.0

    def test_inf_returns_zero(self):
        assert rb.estimate_render_minutes(math.inf) == 0.0


# ---------------------------------------------------------------------------
# _current_month_start
# ---------------------------------------------------------------------------

class TestCurrentMonthStart:
    def test_first_of_month(self):
        now = datetime(2025, 6, 15, 14, 30, 0)
        start = rb._current_month_start(now)
        assert start == datetime(2025, 6, 1, 0, 0, 0)

    def test_uses_utcnow_when_no_arg(self):
        start = rb._current_month_start()
        today = datetime.utcnow()
        assert start.year == today.year
        assert start.month == today.month
        assert start.day == 1


# ---------------------------------------------------------------------------
# BudgetSnapshot
# ---------------------------------------------------------------------------

class TestBudgetSnapshot:
    def _snap(self, plan="free", used=10.0):
        limit = rb.budget_for_plan(plan)
        remaining = max(0.0, limit - used) if not math.isinf(limit) else math.inf
        return rb.BudgetSnapshot(
            plan=plan, minutes_used=used,
            minutes_limit=limit, minutes_remaining=remaining,
            month_start=datetime(2025, 6, 1),
        )

    def test_unlimited_for_pro(self):
        snap = self._snap("pro")
        assert snap.unlimited is True

    def test_not_unlimited_for_free(self):
        snap = self._snap("free")
        assert snap.unlimited is False

    def test_percent_used_free(self):
        snap = self._snap("free", used=15.0)
        assert abs(snap.percent_used - 50.0) < 0.01

    def test_percent_used_unlimited_is_zero(self):
        snap = self._snap("pro")
        assert snap.percent_used == 0.0

    def test_percent_used_capped_at_100(self):
        # Over budget
        snap = rb.BudgetSnapshot(
            plan="free", minutes_used=40.0, minutes_limit=30.0,
            minutes_remaining=0.0, month_start=datetime(2025, 6, 1),
        )
        assert snap.percent_used == 100.0


# ---------------------------------------------------------------------------
# would_exceed_budget — mocking get_budget_snapshot
# ---------------------------------------------------------------------------

class TestWouldExceedBudget:
    def _mock_snap(self, used, plan="free"):
        limit = rb.budget_for_plan(plan)
        remaining = max(0.0, limit - used)
        return rb.BudgetSnapshot(
            plan=plan, minutes_used=used, minutes_limit=limit,
            minutes_remaining=remaining, month_start=datetime(2025, 6, 1),
        )

    def test_pro_never_exceeds(self):
        snap = self._mock_snap(999_999, plan="pro")
        with patch.object(rb, "get_budget_snapshot", return_value=snap):
            assert rb.would_exceed_budget(1, 9999) is False

    def test_free_within_budget(self):
        snap = self._mock_snap(5.0, plan="free")
        with patch.object(rb, "get_budget_snapshot", return_value=snap):
            assert rb.would_exceed_budget(1, 10.0) is False

    def test_free_exceeds_budget(self):
        snap = self._mock_snap(28.0, plan="free")
        with patch.object(rb, "get_budget_snapshot", return_value=snap):
            assert rb.would_exceed_budget(1, 5.0) is True

    def test_exactly_at_limit_does_not_exceed(self):
        # 30 used + 0 projected = exactly at cap, should not exceed
        snap = self._mock_snap(30.0, plan="free")
        with patch.object(rb, "get_budget_snapshot", return_value=snap):
            # tolerance of 1e-6 so exactly 30+0 = 30 is fine
            assert rb.would_exceed_budget(1, 0.0) is False


# ---------------------------------------------------------------------------
# get_remaining_minutes convenience wrapper
# ---------------------------------------------------------------------------

class TestGetRemainingMinutes:
    def test_returns_snapshot_remaining(self):
        snap = rb.BudgetSnapshot(
            plan="free", minutes_used=10.0, minutes_limit=30.0,
            minutes_remaining=20.0, month_start=datetime(2025, 6, 1),
        )
        with patch.object(rb, "get_budget_snapshot", return_value=snap):
            assert rb.get_remaining_minutes(99) == 20.0
