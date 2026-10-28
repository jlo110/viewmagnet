"""Tests for :mod:`src.features.publish_outcomes` — the Week 10
rollup that powers the Outcomes page + the "recommendation
effectiveness" card.

What we pin here:

  * latest-window selection — prefers 30d > 7d > 24h > 1h so the
    rollup averages apples-to-apples
  * CTA attribution chain via ``EditSession.source_video_url``
  * "first attribution wins" — re-edit of the same source under a
    different CTA still attributes to the original recommendation
    (covered indirectly via the most-recent-session-by-id picker)
  * baseline ordering: baseline always first in the rollup
  * NULL-respecting averages: a metric missing from every sample
    yields ``None`` for the average, not ``0``
  * empty-input behavior (no published posts, no panic)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import (
    Base,
    DistributionJob,
    DistributionResult,
    EditSession,
    PublishedMetricSnapshot,
)
from src.features.publish_outcomes import (
    PublishedOutcome,
    list_user_outcomes,
    rollup_recommendation_effectiveness,
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


def _create_published(
    db: Session,
    *,
    user_id: int = 1,
    platform: str = "youtube",
    source_video_url: str | None = None,
    completed_at: datetime | None = None,
    posted_id: str = "abc",
    title: str = "A clip",
) -> DistributionResult:
    completed_at = completed_at or datetime.utcnow()
    job = DistributionJob(
        user_id=user_id,
        title=title,
        source_video_url=source_video_url,
        target_count=1,
        success_count=1,
        failure_count=0,
        created_at=completed_at,
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
        created_at=completed_at,
        completed_at=completed_at,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def _add_snapshot(
    db: Session,
    result: DistributionResult,
    *,
    window_key: str,
    views: int | None = None,
    likes: int | None = None,
    comments: int | None = None,
    avg_view_percentage: float | None = None,
    sampled_at: datetime | None = None,
) -> PublishedMetricSnapshot:
    snap = PublishedMetricSnapshot(
        distribution_result_id=result.id,
        user_id=1,
        platform=result.platform,
        posted_url=result.posted_url,
        window_key=window_key,
        published_at=result.completed_at,
        sampled_at=sampled_at or datetime.utcnow(),
        views=views,
        likes=likes,
        comments=comments,
        avg_view_percentage=avg_view_percentage,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def _add_session(
    db: Session,
    *,
    user_id: int = 1,
    source_video_url: str,
    cta: dict | None,
) -> EditSession:
    row = EditSession(
        user_id=user_id,
        clip_key=f"k_{source_video_url}"[-60:],
        source_video_url=source_video_url,
        source_clip_index=0,
        spec="{}",
        cta_provenance=json.dumps(cta) if cta else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# list_user_outcomes
# ---------------------------------------------------------------------------


class TestListUserOutcomes:

    def test_returns_nothing_when_user_has_no_publishes(
        self, db: Session
    ) -> None:
        assert list_user_outcomes(db, user_id=1) == []

    def test_includes_only_successful_results(self, db: Session) -> None:
        success_result = _create_published(db, posted_id="ok")
        # Manually add a failed result by mutating an extra job.
        job = DistributionJob(
            user_id=1,
            title="failed",
            target_count=1,
            success_count=0,
            failure_count=1,
        )
        db.add(job)
        db.flush()
        db.add(
            DistributionResult(
                job_id=job.id,
                account_id=1,
                platform="youtube",
                status="failed",
                posted_id="nope",
                error_message="boom",
            )
        )
        db.commit()

        rows = list_user_outcomes(db, user_id=1)
        assert len(rows) == 1
        assert rows[0].distribution_result_id == success_result.id

    def test_latest_prefers_longest_window(self, db: Session) -> None:
        """We prefer the 30d snapshot over the 1h snapshot for the
        ``latest`` field because 30d carries more signal for the
        rollup. Without this rule, a fresh 1h sample on an old post
        would mask the user's better 30d number."""
        result = _create_published(db)
        _add_snapshot(db, result, window_key="1h", views=10)
        _add_snapshot(db, result, window_key="30d", views=5_000)

        rows = list_user_outcomes(db, user_id=1)
        assert rows[0].latest is not None
        assert rows[0].latest.window_key == "30d"
        assert rows[0].latest.views == 5_000

    def test_attribution_attached_via_source_url(
        self, db: Session
    ) -> None:
        """When a session exists for the same source URL, its CTA
        provenance flows through to the outcome row."""
        source_url = "https://r2.example/out.mp4"
        _add_session(
            db,
            source_video_url=source_url,
            cta={"tool": "hook_lab", "from": "analyzer"},
        )
        _create_published(
            db, source_video_url=source_url, posted_id="a1"
        )

        rows = list_user_outcomes(db, user_id=1)
        assert rows[0].cta_provenance == {
            "tool": "hook_lab",
            "from": "analyzer",
        }

    def test_no_session_means_no_attribution(self, db: Session) -> None:
        """No EditSession exists for this source URL — the outcome
        falls through to the "baseline" bucket."""
        _create_published(
            db, source_video_url="https://r2.example/no-session.mp4"
        )
        rows = list_user_outcomes(db, user_id=1)
        assert rows[0].cta_provenance is None

    def test_user_isolation(self, db: Session) -> None:
        _create_published(db, user_id=1, posted_id="u1")
        _create_published(db, user_id=2, posted_id="u2")
        rows = list_user_outcomes(db, user_id=1)
        assert len(rows) == 1
        assert rows[0].posted_url and "u1" in rows[0].posted_url


# ---------------------------------------------------------------------------
# rollup_recommendation_effectiveness
# ---------------------------------------------------------------------------


def _outcome(
    *,
    tool: str | None,
    views: int | None = 100,
    likes: int | None = 5,
    comments: int | None = 1,
    retention: float | None = 50.0,
) -> PublishedOutcome:
    """Tiny factory so each rollup test can build a fixture in one
    line and keep the focus on the assertions."""
    from src.features.publish_outcomes import SnapshotPoint

    latest = (
        SnapshotPoint(
            window_key="24h",
            sampled_at="2026-01-01T00:00:00Z",
            views=views,
            likes=likes,
            comments=comments,
            shares=None,
            watch_time_seconds=None,
            avg_view_percentage=retention,
            click_through_rate=None,
        )
        if views is not None
        else None
    )
    return PublishedOutcome(
        distribution_job_id=1,
        distribution_result_id=1,
        platform="youtube",
        posted_url=None,
        published_at="2026-01-01T00:00:00Z",
        title="t",
        source_video_url=None,
        snapshots={"24h": latest} if latest else {},
        latest=latest,
        cta_provenance={"tool": tool} if tool else None,
    )


class TestRollup:

    def test_empty_list_returns_empty(self) -> None:
        assert rollup_recommendation_effectiveness([]) == []

    def test_baseline_is_first(self) -> None:
        groups = rollup_recommendation_effectiveness(
            [
                _outcome(tool="hook_lab"),
                _outcome(tool=None),
                _outcome(tool="script_writer"),
            ]
        )
        assert groups[0].tool == "baseline"
        # Each other tool gets its own group, ordered by sample size.
        assert {g.tool for g in groups[1:]} == {
            "hook_lab",
            "script_writer",
        }

    def test_sample_count_includes_outcomes_without_metrics(
        self,
    ) -> None:
        """A published post that hasn't had its first window
        sampled yet should still count as a member of its
        attribution group — otherwise an empty 1h window would
        make a Hook Lab edit invisible until its 24h sample."""
        groups = rollup_recommendation_effectiveness(
            [
                _outcome(tool="hook_lab", views=None),
                _outcome(tool="hook_lab"),
            ]
        )
        hook_lab = next(g for g in groups if g.tool == "hook_lab")
        # Sample count is 2 even though only one has metrics.
        assert hook_lab.sample_count == 2
        # Average views computed only from the one with metrics.
        assert hook_lab.avg_views == 100

    def test_engagement_rate_uses_likes_plus_comments_over_views(
        self,
    ) -> None:
        groups = rollup_recommendation_effectiveness(
            [
                _outcome(
                    tool="hook_lab",
                    views=100,
                    likes=10,
                    comments=2,
                )
            ]
        )
        hook_lab = next(g for g in groups if g.tool == "hook_lab")
        assert hook_lab.avg_engagement_rate is not None
        assert (
            abs(hook_lab.avg_engagement_rate - 0.12) < 1e-9
        )

    def test_metric_missing_everywhere_yields_none_not_zero(
        self,
    ) -> None:
        """If every sample has no retention reading, the average must
        be ``None`` so the UI renders ``—`` instead of misleading
        the user with a 0%."""
        groups = rollup_recommendation_effectiveness(
            [
                _outcome(tool="script_writer", retention=None),
                _outcome(tool="script_writer", retention=None),
            ]
        )
        sw = next(g for g in groups if g.tool == "script_writer")
        assert sw.avg_retention is None

    def test_groups_sorted_by_sample_count_desc(self) -> None:
        groups = rollup_recommendation_effectiveness(
            [
                _outcome(tool="hook_lab"),
                _outcome(tool="hook_lab"),
                _outcome(tool="hook_lab"),
                _outcome(tool="script_writer"),
                _outcome(tool=None),  # baseline
            ]
        )
        # baseline still first; then hook_lab (3 samples) > script_writer (1).
        assert [g.tool for g in groups] == [
            "baseline",
            "hook_lab",
            "script_writer",
        ]
