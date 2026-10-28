"""Niche benchmarks: percentile interpolation + honest fallback behaviour."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, NicheBenchmark
from src.features.niche_benchmarks import get_benchmark, percentile_for, rank_video


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()
    engine.dispose()


CURVE = dict(p10=100, p25=500, p50=2000, p75=8000, p90=25000, p95=60000, p99=200000)


def _cell(db, niche, is_short=False, checkpoint="24h", n=1000, when=None):
    db.add(NicheBenchmark(computed_at=when or datetime(2026, 8, 5),
                          niche=niche, is_short=is_short, checkpoint=checkpoint,
                          n_videos=n, **CURVE))
    db.commit()


class TestPercentileInterpolation:
    def test_breakpoints_map_exactly(self):
        assert percentile_for(**CURVE, views=2000) == 50
        assert percentile_for(**CURVE, views=25000) == 90
        assert percentile_for(**CURVE, views=200000) == 99

    def test_interpolates_between(self):
        # Halfway between p50 (2000) and p75 (8000) -> ~62nd percentile.
        assert 60 <= percentile_for(**CURVE, views=5000) <= 65

    def test_extremes_clamp(self):
        assert percentile_for(**CURVE, views=0) == 0
        assert percentile_for(**CURVE, views=10_000_000) == 99

    def test_monotonic(self):
        vals = [percentile_for(**CURVE, views=v)
                for v in (50, 300, 1500, 4000, 20000, 80000, 500000)]
        assert vals == sorted(vals)


class TestLookupHonesty:
    def test_falls_back_to_pooled_not_invented(self, db):
        _cell(db, niche=None)                      # pooled cell only
        b = get_benchmark(db, "20", False, "24h")  # Gaming has no cell
        assert b is not None and b["pooled"] is True and b["niche"] is None

    def test_specific_niche_preferred_over_pooled(self, db):
        _cell(db, niche=None)
        _cell(db, niche="20")
        b = get_benchmark(db, "20", False, "24h")
        assert b["niche"] == "20" and b["pooled"] is False

    def test_returns_none_when_nothing_computed(self, db):
        assert get_benchmark(db, "20", False, "24h") is None

    def test_shorts_and_longform_do_not_mix(self, db):
        _cell(db, niche="20", is_short=False)
        assert get_benchmark(db, "20", True, "24h") is None  # no Shorts cell, no pooled

    def test_only_newest_batch_is_read(self, db):
        _cell(db, niche="20", when=datetime(2026, 8, 1), n=111)
        _cell(db, niche="20", when=datetime(2026, 8, 5), n=999)
        assert get_benchmark(db, "20", False, "24h")["n_videos"] == 999


def test_rank_video_reports_percentile_and_multiple(db):
    _cell(db, niche="20")
    r = rank_video(db, 8000, "20", False, "24h")
    assert r["percentile"] == 75
    assert r["vs_median"] == 4.0        # 8000 / p50 2000
    assert r["n_videos"] == 1000
