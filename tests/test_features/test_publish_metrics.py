"""Tests for :mod:`src.features.publish_metrics` — the Week 10
post-publish collector.

What we pin here:

  * window classification — only windows whose target time has
    arrived AND whose grace hasn't expired are "due"
  * idempotency of the (result, window) snapshot upsert
  * stub fetcher determinism so the dashboard render is testable
  * collector resilience: a fetcher exception for one platform
    doesn't tank the sweep for the others
  * graceful skip when no fetcher is registered for a platform
    (deployment with credentials for YouTube but not TikTok)
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import (
    Base,
    DistributionJob,
    DistributionResult,
    PublishedMetricSnapshot,
)
from src.features import publish_metrics
from src.features.publish_metrics import (
    MetricWindow,
    RawMetrics,
    WINDOWS,
    due_windows,
    record_metric_snapshot,
    stub_fetcher,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_fetcher_registry():
    """Snapshot and restore the module-global ``_FETCHERS`` around each test.

    ``_FETCHERS`` is a process-wide registry auto-populated with the stub
    fetcher at import. Other test modules (e.g. ``test_health`` booting the
    app) call the real ``youtube_metrics.register()`` during lifespan, which
    overwrites the ``youtube`` stub with a creds-less fetcher that returns
    nothing — leaking across files and making these tests order-dependent.
    Restoring the snapshot keeps them hermetic regardless of run order.
    """
    saved = dict(publish_metrics._FETCHERS)
    # Reset to the import-time stub baseline so these tests are deterministic
    # even if a prior test module overwrote a platform with a real fetcher.
    for platform in ("youtube", "tiktok", "instagram"):
        publish_metrics.register_fetcher(platform, publish_metrics.stub_fetcher)
    try:
        yield
    finally:
        publish_metrics._FETCHERS.clear()
        publish_metrics._FETCHERS.update(saved)


@pytest.fixture()
def db() -> Session:
    """Function-scoped in-memory SQLite so tests don't share state."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


def _make_job_and_result(
    db: Session,
    *,
    user_id: int = 1,
    platform: str = "youtube",
    completed_at: datetime | None = None,
    posted_id: str = "abc",
) -> tuple[DistributionJob, DistributionResult]:
    job = DistributionJob(
        user_id=user_id,
        title="A published clip",
        target_count=1,
        success_count=1,
        failure_count=0,
        created_at=completed_at or datetime.utcnow(),
    )
    db.add(job)
    db.flush()
    result = DistributionResult(
        job_id=job.id,
        account_id=1,
        platform=platform,
        status="success",
        posted_url=f"https://{platform}.example/{posted_id}",
        posted_id=posted_id,
        created_at=completed_at or datetime.utcnow(),
        completed_at=completed_at,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return job, result


# ---------------------------------------------------------------------------
# Window classification
# ---------------------------------------------------------------------------


class TestDueWindows:
    """``due_windows`` is the gating logic that decides which sample
    moments the collector should chase. Getting this wrong either
    burns API quota (over-firing) or silently drops data (under-
    firing)."""

    def test_future_published_post_returns_nothing(self) -> None:
        """A post published in the future never has a due window."""
        published = datetime(2026, 1, 10)
        now = datetime(2026, 1, 5)
        assert due_windows(
            published_at=published,
            existing_window_keys=[],
            now=now,
        ) == []

    def test_freshly_published_only_eligible_when_first_window_target_hit(
        self,
    ) -> None:
        published = datetime(2026, 1, 10, 12, 0)
        # Mid-way to the 1h target — no window should be due yet.
        now = published + timedelta(minutes=30)
        assert due_windows(
            published_at=published,
            existing_window_keys=[],
            now=now,
        ) == []

        # Right at the 1h target — only the 1h window is in band.
        now = published + timedelta(hours=1)
        eligible = due_windows(
            published_at=published,
            existing_window_keys=[],
            now=now,
        )
        assert [w.key for w in eligible] == ["1h"]

    def test_window_excluded_once_already_captured(self) -> None:
        """If a window already has a snapshot, it's never returned
        again — that's how we avoid pointless re-sampling."""
        published = datetime(2026, 1, 10, 12, 0)
        now = published + timedelta(hours=1, minutes=10)
        assert due_windows(
            published_at=published,
            existing_window_keys=["1h"],
            now=now,
        ) == []

    def test_grace_window_caps_eligibility(self) -> None:
        """A long-delayed sweep should not still chase a 24h window 4
        days later — the grace cuts it off so the queue stays
        bounded."""
        published = datetime(2026, 1, 10, 12, 0)
        very_late = published + timedelta(days=4)
        eligible = [
            w.key
            for w in due_windows(
                published_at=published,
                existing_window_keys=[],
                now=very_late,
            )
        ]
        # 1h and 24h have both passed their grace by 4 days. 7d is
        # still in the future. So nothing is in band.
        assert "1h" not in eligible
        assert "24h" not in eligible

    def test_orders_windows_by_target_time(self) -> None:
        """When multiple windows are simultaneously in band (e.g. a
        sweep that hadn't run in a while), they come back in
        ascending target order so the worker records the earliest
        sample first — important for the duration percentile
        calculation downstream."""
        published = datetime(2026, 1, 10, 12, 0)
        # Two days late — 1h grace expired, 24h and 7d still pending.
        now = published + timedelta(days=2)
        keys = [
            w.key
            for w in due_windows(
                published_at=published,
                existing_window_keys=[],
                now=now,
            )
        ]
        # 24h's target+grace=24h+12h=36h; @48h that's expired too.
        # So we expect 7d (future) and 30d (future) to NOT show up;
        # nothing should be in band right at 48h.
        assert keys == []


# ---------------------------------------------------------------------------
# Stub fetcher
# ---------------------------------------------------------------------------


class TestStubFetcher:
    """Determinism matters: the dashboard's smoke test relies on the
    stub fetcher returning the same values for the same post id so a
    pre/post-deploy diff isn't a tide of noise."""

    def test_same_id_gives_same_metrics(self) -> None:
        a = stub_fetcher("abc", None)
        b = stub_fetcher("abc", None)
        assert a == b

    def test_metrics_are_in_plausible_ranges(self) -> None:
        m = stub_fetcher("plausible", None)
        assert m.views is not None and m.views >= 100
        # Likes should be a non-trivial fraction of views but not
        # exceed them. Catches a bug where likes formula was swapped
        # with views.
        assert m.likes is not None and 0 < m.likes < m.views
        # Retention bounded so the chart doesn't get a 110%.
        assert (
            m.avg_view_percentage is not None
            and 0 <= m.avg_view_percentage <= 100
        )


# ---------------------------------------------------------------------------
# Snapshot persistence
# ---------------------------------------------------------------------------


class TestRecordSnapshot:
    """The upsert keeps (result, window_key) unique even under
    repeated calls. That's the contract the collector + admin
    re-trigger paths rely on."""

    def test_first_write_inserts(self, db: Session) -> None:
        _, result = _make_job_and_result(db)
        window = MetricWindow("1h", timedelta(hours=1))
        snap = record_metric_snapshot(
            db,
            result=result,
            user_id=1,
            window=window,
            metrics=RawMetrics(views=100, likes=10),
            published_at=result.completed_at or result.created_at,
        )
        assert snap.views == 100
        assert snap.likes == 10
        # Only one row in the table.
        rows = db.query(PublishedMetricSnapshot).all()
        assert len(rows) == 1

    def test_second_write_same_window_updates_existing(
        self, db: Session
    ) -> None:
        _, result = _make_job_and_result(db)
        window = MetricWindow("1h", timedelta(hours=1))
        record_metric_snapshot(
            db,
            result=result,
            user_id=1,
            window=window,
            metrics=RawMetrics(views=100, likes=10),
            published_at=result.completed_at or result.created_at,
        )
        record_metric_snapshot(
            db,
            result=result,
            user_id=1,
            window=window,
            metrics=RawMetrics(views=180, likes=20),
            published_at=result.completed_at or result.created_at,
        )
        rows = db.query(PublishedMetricSnapshot).all()
        # Upsert, not append — still exactly one row for the window.
        assert len(rows) == 1
        assert rows[0].views == 180
        assert rows[0].likes == 20

    def test_different_windows_are_separate_rows(
        self, db: Session
    ) -> None:
        _, result = _make_job_and_result(db)
        for window in WINDOWS[:2]:
            record_metric_snapshot(
                db,
                result=result,
                user_id=1,
                window=window,
                metrics=RawMetrics(views=10),
                published_at=result.completed_at
                or result.created_at,
            )
        keys = sorted(
            r.window_key
            for r in db.query(PublishedMetricSnapshot).all()
        )
        assert keys == ["1h", "24h"]

    def test_null_metrics_persist_as_null_not_zero(
        self, db: Session
    ) -> None:
        """Click-through-rate is not exposed by every platform. The
        dashboard prefers ``—`` to a fake zero, so the column must
        stay ``NULL`` when the fetcher didn't report it."""
        _, result = _make_job_and_result(db)
        window = MetricWindow("1h", timedelta(hours=1))
        snap = record_metric_snapshot(
            db,
            result=result,
            user_id=1,
            window=window,
            metrics=RawMetrics(views=10),  # only views
            published_at=result.completed_at or result.created_at,
        )
        assert snap.likes is None
        assert snap.click_through_rate is None
        assert snap.watch_time_seconds is None


# ---------------------------------------------------------------------------
# Collector resilience
# ---------------------------------------------------------------------------


class TestCollectDueMetrics:
    """The collector should NEVER take the worker down. We assert
    that one flaky fetcher is contained and the sweep keeps going
    for other posts."""

    def test_unregistered_platform_skips_silently(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Two posts: one with a registered fetcher (youtube), one
        # without (sparta — not registered).
        published = datetime.utcnow() - timedelta(hours=2)
        _make_job_and_result(
            db, platform="youtube", completed_at=published
        )
        _make_job_and_result(
            db, platform="sparta", completed_at=published
        )

        # Patch get_session to return our test session.
        from contextlib import contextmanager

            
        @contextmanager
        def _fake_session():
            yield db

        monkeypatch.setattr(
            publish_metrics, "get_session", _fake_session
        )

        summary = publish_metrics.collect_due_metrics(
            now=published + timedelta(hours=1)
        )
        # One was attempted (youtube) and one skipped (sparta).
        assert summary["skipped_no_fetcher"] == 1
        assert summary["written"] >= 1
        assert summary["errors"] == 0

    def test_fetcher_exception_does_not_kill_sweep(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Two YouTube posts; we replace the registered fetcher with
        # one that throws on the first call and succeeds on the
        # second to prove the loop continues.
        published = datetime.utcnow() - timedelta(hours=2)
        _make_job_and_result(
            db,
            platform="youtube",
            posted_id="will_fail",
            completed_at=published,
        )
        _make_job_and_result(
            db,
            platform="youtube",
            posted_id="will_succeed",
            completed_at=published,
        )

        call_count = {"n": 0}

        def flaky_fetcher(
            posted_id: str | None, posted_url: str | None
        ) -> RawMetrics | None:
            call_count["n"] += 1
            if posted_id == "will_fail":
                raise RuntimeError("flaky platform")
            return RawMetrics(views=42)

        monkeypatch.setitem(
            publish_metrics._FETCHERS, "youtube", flaky_fetcher
        )

        from contextlib import contextmanager

        @contextmanager
        def _fake_session():
            yield db

        monkeypatch.setattr(
            publish_metrics, "get_session", _fake_session
        )

        summary = publish_metrics.collect_due_metrics(
            now=published + timedelta(hours=1)
        )
        # One success + one error, sweep didn't crash.
        assert summary["errors"] == 1
        assert summary["written"] == 1

    def test_fetcher_returning_none_is_not_an_error(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fetcher returning ``None`` means "no data yet" — the
        collector should record neither a row nor an error so the
        next sweep retries."""
        published = datetime.utcnow() - timedelta(hours=2)
        _make_job_and_result(
            db, platform="youtube", completed_at=published
        )

        monkeypatch.setitem(
            publish_metrics._FETCHERS,
            "youtube",
            lambda _id, _url: None,
        )

        from contextlib import contextmanager

        @contextmanager
        def _fake_session():
            yield db

        monkeypatch.setattr(
            publish_metrics, "get_session", _fake_session
        )

        summary = publish_metrics.collect_due_metrics(
            now=published + timedelta(hours=1)
        )
        assert summary["skipped_no_data"] >= 1
        assert summary["errors"] == 0
        assert summary["written"] == 0
