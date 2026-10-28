"""Publish-timing curves + topic-wave chaining."""
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, TimingBenchmark, TopicMomentum
from src.features.timing_insights import get_timing, wave_stats


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()
    engine.dispose()


def _cell(db, bucket, hit, niche=None, dim="hour", when=None, n=1000):
    db.add(TimingBenchmark(computed_at=when or datetime(2026, 8, 5), dimension=dim,
                           bucket=bucket, niche=niche, is_short=False,
                           n_videos=n, hit_rate=hit))
    db.commit()


class TestTimingCurve:
    def test_reports_best_worst_and_spread(self, db):
        _cell(db, 1, 0.241); _cell(db, 12, 0.205); _cell(db, 17, 0.193)
        t = get_timing(db, "hour")
        assert t["best"]["bucket"] == 1 and t["worst"]["bucket"] == 17
        assert t["spread_points"] == pytest.approx(4.8, abs=0.1)
        assert t["baseline_hit_rate"] == 0.2

    def test_caveat_is_always_present(self, db):
        """The correlational limit must ship with the number, not beside it."""
        _cell(db, 1, 0.24)
        t = get_timing(db, "hour")
        assert "Correlational" in t["caveat"] and "UTC" in t["caveat"]

    def test_falls_back_to_pooled_flagged(self, db):
        _cell(db, 1, 0.24, niche=None)
        t = get_timing(db, "hour", niche="20")
        assert t["pooled"] is True and t["niche"] is None

    def test_none_when_not_computed(self, db):
        assert get_timing(db, "hour") is None

    def test_only_newest_batch(self, db):
        _cell(db, 1, 0.10, when=datetime(2026, 8, 1))
        _cell(db, 1, 0.30, when=datetime(2026, 8, 5))
        assert get_timing(db, "hour")["buckets"][0]["hit_rate"] == 0.30


def _mom(db, when, vids):
    db.add(TopicMomentum(computed_at=when, window_hours=48.0, label="t",
                         topic_size=len(vids), breakout_count=0, breakout_rate=0.0,
                         total_views=0, channel_count=2, trend="new",
                         video_ids=json.dumps(vids)))
    db.commit()


class TestWaveChaining:
    def test_chains_across_batches_despite_label_drift(self, db):
        """Same videos across batches = one wave, even though labels drift."""
        t0 = datetime(2026, 8, 1)
        _mom(db, t0, ["a", "b", "c", "d"])
        _mom(db, t0 + timedelta(hours=6), ["a", "b", "c", "e"])   # high overlap
        _mom(db, t0 + timedelta(hours=12), ["a", "b", "c", "f"])
        w = wave_stats(db)
        assert w["waves_lasting_multiple_batches"] == 1
        assert w["median_days"] == pytest.approx(0.5, abs=0.01)   # 12h

    def test_disjoint_topics_do_not_chain(self, db):
        """No shared videos = separate waves, so nothing persisted and there is
        no duration to report (None rather than a fabricated zero)."""
        t0 = datetime(2026, 8, 1)
        _mom(db, t0, ["a", "b", "c"])
        _mom(db, t0 + timedelta(hours=6), ["x", "y", "z"])        # no overlap
        assert wave_stats(db) is None

    def test_none_without_history(self, db):
        assert wave_stats(db) is None

    def test_window_caveat_present(self, db):
        t0 = datetime(2026, 8, 1)
        _mom(db, t0, ["a", "b"]); _mom(db, t0 + timedelta(hours=6), ["a", "b"])
        assert "48h window" in wave_stats(db)["caveat"]
