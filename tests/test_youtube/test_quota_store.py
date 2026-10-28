"""Tests for durable YouTube quota accounting (observability).

Pure helpers (status math, alert thresholds, accumulator drain/restore) need no
DB; flush + read are exercised against an in-memory sqlite DB.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base, YouTubeQuotaUsage
from src.youtube import quota as quota_mod
from src.youtube.quota import (
    DAILY_QUOTA_LIMIT,
    drain_pending_usage,
    restore_pending_usage,
)
from src.youtube.quota_store import (
    compute_status,
    evaluate_quota_alert,
    flush_quota_usage,
    get_today_usage,
    get_usage_history,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _clear_accumulator():
    """Each test starts with an empty global accumulator."""
    drain_pending_usage()
    yield
    drain_pending_usage()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_compute_status_aggregates_per_key_and_operation():
    rows = [
        (0, "playlistItems.list", 9000),
        (0, "videos.list", 1000),  # key 0 now at 10000 -> exhausted
        (1, "playlistItems.list", 2000),
    ]
    status = compute_status(rows, num_keys=3)

    assert status["capacity"] == 3 * DAILY_QUOTA_LIMIT
    assert status["total_used"] == 12000
    assert status["total_remaining"] == 3 * DAILY_QUOTA_LIMIT - 12000
    assert status["keys_exhausted"] == 1  # only key 0
    assert status["by_operation"]["playlistItems.list"] == 11000
    # by_key has an entry per key, including the untouched key 2
    by_key = {k["key_index"]: k for k in status["by_key"]}
    assert by_key[0]["exhausted"] is True
    assert by_key[2]["used"] == 0 and by_key[2]["exhausted"] is False


def test_evaluate_quota_alert_levels():
    # plenty left -> no alert
    assert evaluate_quota_alert({"pct_remaining": 0.5, "total_remaining": 5}, 0.15) is None
    # below threshold -> warn
    warn = evaluate_quota_alert(
        {"pct_remaining": 0.10, "total_remaining": 100, "total_used": 900,
         "keys_exhausted": 1, "capacity": 1000},
        0.15,
    )
    assert warn and warn["level"] == "warn"
    # nothing left -> critical (even if pct rounding says >0)
    crit = evaluate_quota_alert({"pct_remaining": 0.0, "total_remaining": 0}, 0.15)
    assert crit and crit["level"] == "critical"


def test_drain_and_restore_roundtrip():
    quota_mod._accumulate_usage(0, "videos.list", 5)
    quota_mod._accumulate_usage(0, "videos.list", 3)
    quota_mod._accumulate_usage(1, "playlistItems.list", 2)

    drained = drain_pending_usage()
    assert sum(drained.values()) == 10
    # drain is one-shot: a second drain is empty
    assert drain_pending_usage() == {}

    # a failed flush restores the deltas for retry
    restore_pending_usage(drained)
    assert sum(drain_pending_usage().values()) == 10


# ---------------------------------------------------------------------------
# DB-backed flush + read
# ---------------------------------------------------------------------------


def test_flush_is_incremental(db, monkeypatch):
    monkeypatch.setattr(quota_mod, "get_settings", lambda: type("S", (), {"youtube_api_keys": ["a", "b"]})())
    # also patch the store's _num_keys source
    import src.youtube.quota_store as store
    monkeypatch.setattr(store, "_num_keys", lambda: 2)

    quota_mod._accumulate_usage(0, "videos.list", 100)
    out1 = flush_quota_usage(db)
    assert out1["flushed"] == 100

    # a second batch on the SAME (date,key,op) must increment, not overwrite
    quota_mod._accumulate_usage(0, "videos.list", 50)
    flush_quota_usage(db)

    rows = db.query(YouTubeQuotaUsage).all()
    assert len(rows) == 1
    assert rows[0].units == 150

    status = get_today_usage(db)
    assert status["total_used"] == 150
    assert status["capacity"] == 2 * DAILY_QUOTA_LIMIT


def test_flush_empty_is_noop(db):
    assert flush_quota_usage(db)["flushed"] == 0


def test_history_returns_per_day_totals(db, monkeypatch):
    import src.youtube.quota_store as store
    monkeypatch.setattr(store, "_num_keys", lambda: 1)

    # Date must be RELATIVE: get_usage_history only looks back `days` from today,
    # so a hardcoded date silently falls out of the window and the test starts
    # failing on a calendar date (this one broke ~2026-07-10). Yesterday is inside
    # every window >= 2 days and avoids any midnight-boundary flake.
    day = (date.today() - timedelta(days=1)).isoformat()
    db.add(YouTubeQuotaUsage(usage_date=day, key_index=0, operation="videos.list", units=400))
    db.add(YouTubeQuotaUsage(usage_date=day, key_index=0, operation="search.list", units=100))
    db.commit()

    hist = get_usage_history(db, days=30)
    today = [h for h in hist if h["date"] == day]
    assert today and today[0]["used"] == 500
    assert today[0]["remaining"] == DAILY_QUOTA_LIMIT - 500
