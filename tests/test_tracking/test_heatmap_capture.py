"""Tests for Most-Replayed heatmap capture (Phase 8.1) — pure logic + job flow."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base, TrackedVideo, VideoHeatmap
from src.tracking import heatmap_capture as hc


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# eligible_attempt
# ---------------------------------------------------------------------------


def test_eligibility_schedule():
    assert not hc.eligible_attempt(age_days=5, attempts=0)    # too young
    assert hc.eligible_attempt(age_days=14, attempts=0)       # first probe
    assert not hc.eligible_attempt(age_days=20, attempts=1)   # retry only after 31d
    assert hc.eligible_attempt(age_days=32, attempts=1)       # final retry
    assert not hc.eligible_attempt(age_days=99, attempts=2)   # exhausted


# ---------------------------------------------------------------------------
# heatmap_features
# ---------------------------------------------------------------------------


def _points(values):
    step = 2.0
    return [
        {"start_time": i * step, "end_time": (i + 1) * step, "value": v}
        for i, v in enumerate(values)
    ]


def test_features_flat_curve_has_no_dropoff():
    f = hc.heatmap_features(_points([1.0] + [0.5] * 99))
    assert f["dropoff_slope"] == pytest.approx(0.0, abs=1e-6)
    assert f["rewatch_peaks"] == 0


def test_features_decaying_curve_has_positive_dropoff_and_detects_peak():
    # Steady decay 0.9 -> 0.1 with one big interior rewatch spike.
    vals = [1.0] + [0.9 - 0.8 * (i / 98) for i in range(99)]
    vals[50] = 0.95  # rewatch moment
    f = hc.heatmap_features(_points(vals))
    assert f["dropoff_slope"] > 0.3
    assert f["rewatch_peaks"] >= 1


def test_features_too_few_points_returns_none():
    assert hc.heatmap_features(_points([1.0, 0.5])) is None
    assert hc.heatmap_features([]) is None


# ---------------------------------------------------------------------------
# capture job (network stubbed)
# ---------------------------------------------------------------------------


def _tracked(db, vid: str, age_days: float):
    db.add(
        TrackedVideo(
            video_id=vid,
            channel_id="UCx",
            title="t",
            published_at=datetime.utcnow() - timedelta(days=age_days),
        )
    )
    db.commit()


def test_capture_stores_hit_and_miss_and_respects_age(db, monkeypatch):
    monkeypatch.setattr(hc, "FETCH_SLEEP_SECONDS", 0)
    _tracked(db, "old00000001", age_days=15)   # eligible, heatmap + transcript
    _tracked(db, "old00000002", age_days=15)   # eligible, neither (miss)
    _tracked(db, "yng00000001", age_days=3)    # too young, untouched

    fake = {
        "old00000001": {
            "heatmap": _points([1.0] + [0.5] * 99),
            "transcript": "What if I told you everything is wrong?",
            "transcript_lang": "en",
            "transcript_source": "auto",
        },
    }
    empty = {"heatmap": None, "transcript": None}
    monkeypatch.setattr(hc, "fetch_video_extras", lambda vid: fake.get(vid, empty))

    out = hc.capture_heatmaps(db)
    assert out == {"captured": 1, "missed": 1, "errors": 0, "eligible": 2, "transcripts": 1}

    hit = db.query(VideoHeatmap).filter_by(video_id="old00000001").one()
    assert hit.has_heatmap and hit.n_points == 100
    assert len(json.loads(hit.points)) == 100
    assert hit.opening_transcript.startswith("What if")
    assert hit.transcript_lang == "en" and hit.transcript_source == "auto"
    miss = db.query(VideoHeatmap).filter_by(video_id="old00000002").one()
    assert not miss.has_heatmap and miss.attempts == 1
    assert miss.opening_transcript is None
    assert db.query(VideoHeatmap).filter_by(video_id="yng00000001").count() == 0

    # Second run: the hit is terminal (has_heatmap), the miss waits for its 31d
    # retry, the young one is still too young — nothing eligible.
    out2 = hc.capture_heatmaps(db)
    assert out2["eligible"] == 0


def test_capture_fetch_error_counts_and_records_attempt(db, monkeypatch):
    monkeypatch.setattr(hc, "FETCH_SLEEP_SECONDS", 0)
    _tracked(db, "err00000001", age_days=15)

    def _boom(vid):
        raise RuntimeError("network")

    monkeypatch.setattr(hc, "fetch_video_extras", _boom)
    out = hc.capture_heatmaps(db)
    assert out["errors"] == 1 and out["missed"] == 1
    row = db.query(VideoHeatmap).filter_by(video_id="err00000001").one()
    assert row.attempts == 1 and not row.has_heatmap


def test_parse_json3_transcript_window_and_flatten():
    data = {
        "events": [
            {"tStartMs": 0, "segs": [{"utf8": "What if I told you"}, {"utf8": " everything"}]},
            {"tStartMs": 30_000, "segs": [{"utf8": "is wrong?\n"}]},
            {"tStartMs": 61_000, "segs": [{"utf8": "PAST THE WINDOW"}]},
        ]
    }
    text = hc.parse_json3_transcript(data, max_ms=60_000)
    assert text == "What if I told you everything is wrong?"
    assert "PAST" not in text


def test_parse_json3_transcript_empty():
    assert hc.parse_json3_transcript({"events": []}) is None
    assert hc.parse_json3_transcript({}) is None
