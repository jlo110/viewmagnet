"""Tests for :mod:`src.queue.telemetry_summary` — render funnel
aggregator (Week 8 P3 polish).

These exercise ``summarize_renders`` end-to-end against an in-memory
SQLite session pre-populated with audit rows so we hit the same
SQL path the admin telemetry endpoint uses in production.

What we pin here:

  * counts split by event type
  * success / failure / cancel rates excluding ``cancelled`` from the
    failure rate
  * top-N error grouping by ``error_type``
  * wait + render duration percentiles using ``render_id`` pairing
  * per-day buckets in UTC
  * lookback window clamping (out-of-window events are excluded)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import AuditEvent, Base
from src.queue.telemetry_summary import summarize_renders


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db() -> Session:
    """Stand up an isolated SQLite DB with just the schema we need.

    Audit aggregations are pure-SQL so we don't need the wider
    application context. A function-scoped fixture means each test
    gets a clean slate without ordering coupling.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


def _evt(
    db: Session,
    *,
    event_type: str,
    when: datetime,
    user_id: int | None = 1,
    details: dict | None = None,
) -> None:
    """Insert one audit row with a fixed ``created_at`` so tests can
    assert window-bound behavior deterministically."""
    row = AuditEvent(
        user_id=user_id,
        event_type=event_type,
        details=json.dumps(details or {}, default=str),
        created_at=when,
    )
    db.add(row)
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyWindow:
    def test_zero_events_returns_zeros(self, db: Session):
        out = summarize_renders(db)
        assert out["counts"]["queued"] == 0
        assert out["counts"]["completed"] == 0
        assert out["rates"]["success_rate"] == 0.0
        assert out["wait_seconds"]["samples"] == 0
        assert out["render_seconds"]["samples"] == 0
        assert out["top_errors"] == []
        assert out["by_day"] == []


class TestCounts:
    def test_queued_completed_failed_are_counted(self, db: Session):
        now = datetime.utcnow()
        for _ in range(3):
            _evt(db, event_type="render.queued", when=now)
        for _ in range(2):
            _evt(db, event_type="render.completed", when=now)
        _evt(db, event_type="render.failed", when=now)

        out = summarize_renders(db)
        assert out["counts"]["queued"] == 3
        assert out["counts"]["completed"] == 2
        assert out["counts"]["failed"] == 1

    def test_dlq_counted_separately(self, db: Session):
        now = datetime.utcnow()
        _evt(db, event_type="render.failed", when=now)
        _evt(db, event_type="render.dlq", when=now)
        out = summarize_renders(db)
        assert out["counts"]["failed"] == 1
        assert out["counts"]["dlq"] == 1


class TestRates:
    def test_success_rate_excludes_cancelled_from_failures(
        self, db: Session
    ):
        """The whole point of splitting ``cancelled`` from
        ``failed`` is to keep cancel counts out of the failure-rate
        chart. Regressing this would put cancellations back into
        the failure bucket and tank our visible health score."""
        now = datetime.utcnow()
        for _ in range(8):
            _evt(db, event_type="render.completed", when=now)
        for _ in range(1):
            _evt(db, event_type="render.failed", when=now)
        for _ in range(1):
            _evt(db, event_type="render.cancelled", when=now)

        out = summarize_renders(db)
        # Denominator = 8 + 1 + 1 = 10 terminal.
        assert out["rates"]["success_rate"] == 0.8
        assert out["rates"]["failure_rate"] == 0.1
        assert out["rates"]["cancel_rate"] == 0.1

    def test_rates_default_to_zero_when_no_terminal_events(
        self, db: Session
    ):
        now = datetime.utcnow()
        # Only ``queued`` events — denominator should fall back to
        # zero, not divide-by-zero.
        _evt(db, event_type="render.queued", when=now)
        out = summarize_renders(db)
        assert out["rates"]["success_rate"] == 0.0


class TestDurations:
    def test_pairs_queued_started_for_wait(self, db: Session):
        now = datetime.utcnow()
        _evt(
            db,
            event_type="render.queued",
            when=now - timedelta(seconds=120),
            details={"render_kind": "session", "render_id": 1},
        )
        _evt(
            db,
            event_type="render.started",
            when=now - timedelta(seconds=60),
            details={"render_kind": "session", "render_id": 1},
        )
        _evt(
            db,
            event_type="render.completed",
            when=now,
            details={"render_kind": "session", "render_id": 1},
        )
        out = summarize_renders(db)
        # Wait: queued→started = 60s. Render: started→completed = 60s.
        assert out["wait_seconds"]["samples"] == 1
        assert out["wait_seconds"]["p50"] == 60
        assert out["render_seconds"]["samples"] == 1
        assert out["render_seconds"]["p50"] == 60

    def test_unmatched_started_is_ignored(self, db: Session):
        # A ``started`` without a matching ``queued`` doesn't
        # contribute to wait. (e.g. worker restarted mid-window
        # and lost the queued event)
        now = datetime.utcnow()
        _evt(
            db,
            event_type="render.started",
            when=now - timedelta(seconds=10),
            details={"render_kind": "session", "render_id": 99},
        )
        _evt(
            db,
            event_type="render.completed",
            when=now,
            details={"render_kind": "session", "render_id": 99},
        )
        out = summarize_renders(db)
        assert out["wait_seconds"]["samples"] == 0
        assert out["render_seconds"]["samples"] == 1


class TestTopErrors:
    def test_top_errors_grouped_by_type(self, db: Session):
        now = datetime.utcnow()
        for _ in range(3):
            _evt(
                db,
                event_type="render.failed",
                when=now,
                details={"error_type": "TimeoutError"},
            )
        for _ in range(2):
            _evt(
                db,
                event_type="render.failed",
                when=now,
                details={"error_type": "RuntimeError"},
            )
        _evt(
            db,
            event_type="render.dlq",
            when=now,
            details={"error_type": "MemoryError"},
        )

        out = summarize_renders(db)
        # most_common preserves insertion order on ties — the order
        # matters for the dashboard so pin it.
        assert out["top_errors"][0] == {
            "error_type": "TimeoutError",
            "count": 3,
        }
        assert out["top_errors"][1] == {
            "error_type": "RuntimeError",
            "count": 2,
        }
        assert {"error_type": "MemoryError", "count": 1} in out[
            "top_errors"
        ]

    def test_top_errors_falls_back_to_unknown(self, db: Session):
        now = datetime.utcnow()
        _evt(db, event_type="render.failed", when=now, details={})
        out = summarize_renders(db)
        assert out["top_errors"][0]["error_type"] == "Unknown"


class TestWindowing:
    def test_events_outside_window_excluded(self, db: Session):
        now = datetime.utcnow()
        # Inside window
        _evt(
            db,
            event_type="render.completed",
            when=now - timedelta(hours=1),
        )
        # Outside window
        _evt(
            db,
            event_type="render.completed",
            when=now - timedelta(days=10),
        )
        out = summarize_renders(
            db, since=now - timedelta(hours=24), until=now
        )
        assert out["counts"]["completed"] == 1

    def test_inverted_window_returns_empty(self, db: Session):
        now = datetime.utcnow()
        _evt(db, event_type="render.completed", when=now)
        # since > until → normalized to empty range.
        out = summarize_renders(
            db, since=now + timedelta(hours=1), until=now
        )
        assert out["counts"]["completed"] == 0


class TestRobustness:
    def test_unparseable_details_is_ignored(self, db: Session):
        now = datetime.utcnow()
        # Write a bad row directly (bypass ``_evt`` JSON-encoding).
        bad = AuditEvent(
            user_id=1,
            event_type="render.failed",
            details="this isn't JSON {",
            created_at=now,
        )
        db.add(bad)
        db.commit()

        # Should still count the failure, just with "Unknown"
        # error_type because we couldn't extract it from the bad
        # details blob.
        out = summarize_renders(db)
        assert out["counts"]["failed"] == 1
        assert out["top_errors"][0]["error_type"] == "Unknown"


class TestDailyBuckets:
    def test_by_day_returns_utc_date_buckets(self, db: Session):
        # Pin events to specific UTC days to assert grouping.
        d1 = datetime(2026, 5, 1, 12, 0, 0)
        d2 = datetime(2026, 5, 2, 12, 0, 0)
        _evt(db, event_type="render.queued", when=d1)
        _evt(db, event_type="render.completed", when=d1)
        _evt(db, event_type="render.completed", when=d2)
        _evt(db, event_type="render.failed", when=d2)

        out = summarize_renders(
            db,
            since=d1 - timedelta(hours=1),
            until=d2 + timedelta(hours=1),
        )
        by_day = {b["date"]: b for b in out["by_day"]}
        assert by_day["2026-05-01"]["queued"] == 1
        assert by_day["2026-05-01"]["completed"] == 1
        assert by_day["2026-05-02"]["completed"] == 1
        assert by_day["2026-05-02"]["failed"] == 1
