"""Tests for collection QA: window hit-rate monitoring (remediation 7.6)."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.tracking.collection_health import (
    VideoWindowRow,
    evaluate_health_alert,
    summarize_collection_health,
)

NOW = datetime(2026, 6, 11, 12, 0, 0)
ALL_KEYS = ["1h", "6h", "24h", "3d", "7d", "14d", "30d"]


def _row(age_hours: float, flags: dict, tracked_from_hours: float = None) -> VideoWindowRow:
    """A video published ``age_hours`` ago; tracked since publish unless given."""
    pub = NOW - timedelta(hours=age_hours)
    ts = NOW - timedelta(hours=tracked_from_hours) if tracked_from_hours else pub
    full = {k: False for k in ALL_KEYS}
    full.update(flags)
    return VideoWindowRow(published_at=pub, tracking_started=ts, flags=full)


def test_open_windows_are_undecided():
    # 2h-old video: 1h window (closes at 3h) is still open -> not counted.
    row = _row(2, {"1h": False})
    s = summarize_collection_health([row], now=NOW)
    cp = {c["checkpoint"]: c for c in s["checkpoints"]}
    assert cp["1h"]["eligible"] == 0  # window not closed yet
    assert s["overall_eligible"] == 0


def test_closed_window_hit_and_miss():
    # 1h window closes at 3h. Two 5h-old videos: one captured, one not.
    hit = _row(5, {"1h": True})
    miss = _row(5, {"1h": False})
    s = summarize_collection_health([hit, miss], now=NOW)
    cp = {c["checkpoint"]: c for c in s["checkpoints"]}
    assert cp["1h"]["eligible"] == 2
    assert cp["1h"]["hit"] == 1
    assert cp["1h"]["hit_rate"] == 0.5


def test_late_discovered_video_excluded_from_eligible():
    # 5h-old video, but tracking only started 1h ago (after the 1h window closed
    # at 3h) -> never eligible for 1h, must not count as a miss.
    late = _row(5, {"1h": False}, tracked_from_hours=1)
    s = summarize_collection_health([late], now=NOW)
    cp = {c["checkpoint"]: c for c in s["checkpoints"]}
    assert cp["1h"]["eligible"] == 0


def test_recent_slice_tracks_fresh_degradation():
    # Old miss (window closed 10 days ago) vs recent miss (closed yesterday).
    old_miss = _row(24 * 12, {"1h": False})       # 1h window closed ~12d ago
    recent_miss = _row(5, {"1h": False})           # closed ~2h ago
    s = summarize_collection_health(
        [old_miss, recent_miss], now=NOW, recent_hours=168
    )
    cp = {c["checkpoint"]: c for c in s["checkpoints"]}
    assert cp["1h"]["eligible"] == 2
    assert cp["1h"]["recent_eligible"] == 1  # only the fresh one
    assert cp["1h"]["recent_hit_rate"] == 0.0


def test_view_monotonicity_counts_decreases():
    from src.tracking.collection_health import summarize_view_monotonicity

    rows = [
        # video A: 1h=100 -> 6h=200 -> 24h=150 (one decrease)
        ("A", "1h", 100), ("A", "6h", 200), ("A", "24h", 150),
        # video B: clean growth
        ("B", "1h", 10), ("B", "6h", 30),
        # video C: single checkpoint -> no pairs
        ("C", "1h", 5),
    ]
    out = summarize_view_monotonicity(rows)
    assert out["checkpoint_pairs"] == 3
    assert out["view_decreases"] == 1
    assert out["decrease_rate"] == round(1 / 3, 4)
    assert out["examples"][0]["video_id"] == "A"
    assert out["examples"][0]["drop_pct"] == 25.0


def test_view_monotonicity_order_is_checkpoint_not_insertion():
    from src.tracking.collection_health import summarize_view_monotonicity

    # Rows arrive out of order; pairs must follow checkpoint order (1h->6h->24h).
    rows = [("A", "24h", 300), ("A", "1h", 100), ("A", "6h", 200)]
    out = summarize_view_monotonicity(rows)
    assert out["checkpoint_pairs"] == 2
    assert out["view_decreases"] == 0


def test_view_monotonicity_empty():
    from src.tracking.collection_health import summarize_view_monotonicity

    out = summarize_view_monotonicity([])
    assert out["checkpoint_pairs"] == 0 and out["decrease_rate"] is None


def test_evaluate_health_alert_respects_min_sample():
    summary = {
        "checkpoints": [
            {"checkpoint": "1h", "recent_hit_rate": 0.4, "recent_eligible": 100},
            {"checkpoint": "6h", "recent_hit_rate": 0.4, "recent_eligible": 5},  # tiny
            {"checkpoint": "24h", "recent_hit_rate": 0.95, "recent_eligible": 100},
        ]
    }
    alerts = evaluate_health_alert(summary, min_hit_rate=0.7, min_sample=50)
    flagged = {a["checkpoint"] for a in alerts}
    assert flagged == {"1h"}  # 6h below sample floor, 24h healthy
