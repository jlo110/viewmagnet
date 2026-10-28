"""Unit tests for the pure niche-coverage logic (no DB / no API)."""
from src.features.niche_coverage import classify_tier, is_starved


class TestClassifyTier:
    def test_tiers(self):
        assert classify_tier(500) == "nano"
        assert classify_tier(9_999) == "nano"
        assert classify_tier(10_000) == "micro"
        assert classify_tier(99_999) == "micro"
        assert classify_tier(100_000) == "mid"
        assert classify_tier(999_999) == "mid"
        assert classify_tier(1_000_000) == "large"
        assert classify_tier(50_000_000) == "large"

    def test_unknown_when_none(self):
        assert classify_tier(None) is None


class TestStarved:
    def test_starved_on_thin_channels(self):
        assert is_starved(tracked_channels=10, breakouts_7d=50, active_formats=5, deficit=0) is True

    def test_starved_on_no_breakouts(self):
        assert is_starved(tracked_channels=500, breakouts_7d=0, active_formats=5, deficit=0) is True

    def test_starved_on_no_formats(self):
        assert is_starved(tracked_channels=500, breakouts_7d=20, active_formats=0, deficit=0) is True

    def test_starved_on_deficit(self):
        assert is_starved(tracked_channels=500, breakouts_7d=20, active_formats=5, deficit=100) is True

    def test_healthy_niche_not_starved(self):
        assert is_starved(tracked_channels=3300, breakouts_7d=40, active_formats=8, deficit=0) is False
