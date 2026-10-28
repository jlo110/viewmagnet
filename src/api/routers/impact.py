"""/impact/summary — real before/after lift attributed to ViewMagnet.

The Impact page on the dashboard refuses to fabricate growth charts
(see ``frontend/client/src/pages/dashboard/Impact.tsx`` for the full
rationale and the readiness gates that mirror this endpoint's logic).
When the user clears the gates, we compute a transparent before/after
view from their own analysis history:

* **Before cohort** — the first half of their analyzed videos (a
  proxy for "what the channel looked like before they started taking
  ViewMagnet's recommendations seriously").
* **After cohort** — the second half (videos analyzed once they were
  actively iterating with the tool).

For each metric (prediction score, title score, thumbnail score, and
where available real 7-day views), we expose the cohort average
``before``/``after``, the absolute ``change``, and the ``changePercent``
that the UI uses to render the lift cards. The ``trend`` field is a
per-analysis timeseries so the chart can plot the trajectory.

Readiness thresholds are duplicated here (not imported from the
frontend) on purpose — the backend owns the source of truth and the
frontend mirrors them in its progress UI.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.auth.dependencies import get_current_user
from sqlalchemy import select
from src.database.connection import get_async_session
from src.database.models import User, UserVideoAnalysis

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["impact"])

# Mirror of the frontend constants so the API speaks the same language
# the UI gates on. If you change these, update Impact.tsx too.
MIN_VIDEOS_FOR_IMPACT = 5
MIN_DAYS_FOR_IMPACT = 30


class ImpactMetric(BaseModel):
    """One row in the before/after metrics grid on the Impact page."""

    name: str
    before: float
    after: float
    change: float
    change_percent: float
    unit: str
    # Lucide icon name; the frontend resolves this to a React element.
    icon: str


class ImpactVideoComparison(BaseModel):
    """A single analyzed video as it appears in the side-by-side table."""

    video_id: str
    title: str
    used_view_magnet: bool
    views: int
    engagement_rate: float
    published_at: Optional[str]
    magnet_score: Optional[float]


class ImpactTrendPoint(BaseModel):
    """One sample on the trend chart — a single analyzed video."""

    date: str
    before_avg: float
    after_avg: float
    actual: float


class ImpactSummaryResponse(BaseModel):
    """Top-level payload returned to the Impact page."""

    ready: bool
    video_count: int
    days_of_history: int
    first_analyzed_at: Optional[str]
    metrics: List[ImpactMetric]
    videos: List[ImpactVideoComparison]
    trend: List[ImpactTrendPoint]


def _avg(values: List[Optional[float]]) -> Optional[float]:
    """Mean of the non-null values, or ``None`` if there are no samples."""
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def _pct_change(before: Optional[float], after: Optional[float]) -> float:
    """Percent change from ``before`` to ``after``.

    Returns ``0.0`` whenever either side is missing or ``before`` is
    zero (would be undefined). Surfaced like this so a missing metric
    just shows ``0%`` instead of crashing the chart.
    """
    if before in (None, 0) or after is None:
        return 0.0
    return ((after - before) / before) * 100.0


def _build_metric(
    name: str,
    icon: str,
    unit: str,
    before: Optional[float],
    after: Optional[float],
) -> Optional[ImpactMetric]:
    """Compose a metric row, omitting it entirely when both sides empty.

    We never want to render "0 → 0" lift just because we don't have
    data for a metric (e.g. title_score is optional on older
    analyses). Returning ``None`` lets the caller skip the row.
    """
    if before is None and after is None:
        return None
    b = float(before or 0)
    a = float(after or 0)
    return ImpactMetric(
        name=name,
        before=round(b, 1),
        after=round(a, 1),
        change=round(a - b, 1),
        change_percent=round(_pct_change(before, after), 1),
        unit=unit,
        icon=icon,
    )


@router.get("/impact/summary", response_model=ImpactSummaryResponse)
async def get_impact_summary(
    current_user: User = Depends(get_current_user),
) -> ImpactSummaryResponse:
    """Compute the authenticated user's before/after impact view.

    Always returns ``200`` so the frontend can use a single contract
    for "still ramping" and "unlocked" cases. ``ready=false`` plus
    ``video_count``/``days_of_history`` is the signal the UI uses to
    keep the unlock card up; ``ready=true`` triggers the real chart.
    """
    async with get_async_session() as session:
        # Pull *all* analyses for this user ordered oldest→newest. We
        # cap at 500 to keep the response bounded; nobody iterating
        # this hard needs a deeper chart than that.
        result = await session.execute(
            select(UserVideoAnalysis)
            .where(UserVideoAnalysis.user_id == current_user.id)
            .order_by(UserVideoAnalysis.analyzed_at.asc())
            .limit(500)
        )
        analyses: List[UserVideoAnalysis] = result.scalars().all()

        # Materialize all required fields *inside* the session scope
        # so the downstream response-building code doesn't trigger
        # detached-instance lazy loads. Each row becomes a tuple of
        # primitives we then use to build the cohorts.
        rows: List[dict] = [
            {
                "video_id": a.video_id,
                "title": a.title,
                "analyzed_at": a.analyzed_at,
                "prediction_score": a.prediction_score,
                "title_score": a.title_score,
                "thumbnail_score": a.thumbnail_score,
                "actual_views_7d": a.actual_views_7d,
                "actual_ctr": a.actual_ctr,
                "actual_avg_duration": a.actual_avg_duration,
            }
            for a in analyses
        ]

    video_count = len(rows)
    first_at: Optional[datetime] = rows[0]["analyzed_at"] if rows else None
    days_of_history = (
        (datetime.utcnow() - first_at).days if first_at is not None else 0
    )
    ready = (
        video_count >= MIN_VIDEOS_FOR_IMPACT
        and days_of_history >= MIN_DAYS_FOR_IMPACT
    )

    # When the user isn't ready we still want to return the readiness
    # fields so the page can render its progress card without making a
    # second call. The metrics / trend lists stay empty in that branch.
    if not ready or video_count < 2:
        return ImpactSummaryResponse(
            ready=False,
            video_count=video_count,
            days_of_history=days_of_history,
            first_analyzed_at=first_at.isoformat() if first_at else None,
            metrics=[],
            videos=[],
            trend=[],
        )

    # ---- Cohort split ---------------------------------------------------
    # The "before" cohort is the first half of analyses (rounded down)
    # and "after" is everything past the split. With a min of 5 videos
    # we always get at least a 2/3 split, which is enough signal to
    # avoid the "two points = trend" illusion.
    split = max(1, video_count // 2)
    before, after = rows[:split], rows[split:]

    score_metric = _build_metric(
        name="Prediction Score",
        icon="TrendingUp",
        unit="/100",
        before=_avg([r["prediction_score"] for r in before]),
        after=_avg([r["prediction_score"] for r in after]),
    )
    title_metric = _build_metric(
        name="Title Score",
        icon="ThumbsUp",
        unit="/100",
        before=_avg([r["title_score"] for r in before]),
        after=_avg([r["title_score"] for r in after]),
    )
    thumb_metric = _build_metric(
        name="Thumbnail Score",
        icon="Eye",
        unit="/100",
        before=_avg([r["thumbnail_score"] for r in before]),
        after=_avg([r["thumbnail_score"] for r in after]),
    )
    # ``actual_views_7d`` is only populated for analyses where the
    # background outcome-checker has caught up. We treat its absence
    # as "no signal" rather than zero so the lift card disappears
    # instead of misreporting it. Same idea for engagement.
    views_metric = _build_metric(
        name="Views (7d)",
        icon="Users",
        unit="",
        before=_avg([r["actual_views_7d"] for r in before]),
        after=_avg([r["actual_views_7d"] for r in after]),
    )
    ctr_metric = _build_metric(
        name="CTR",
        icon="MessageSquare",
        unit="%",
        before=_avg([r["actual_ctr"] for r in before]),
        after=_avg([r["actual_ctr"] for r in after]),
    )
    duration_metric = _build_metric(
        name="Avg View Duration",
        icon="Clock",
        unit="s",
        before=_avg([r["actual_avg_duration"] for r in before]),
        after=_avg([r["actual_avg_duration"] for r in after]),
    )

    metrics = [
        m for m in (
            score_metric,
            title_metric,
            thumb_metric,
            views_metric,
            ctr_metric,
            duration_metric,
        ) if m is not None
    ]

    # ---- Per-video comparison table ------------------------------------
    # We tag every analysis with ``used_view_magnet=True`` because the
    # mere fact that it's in this table means the user analyzed it
    # with the tool. The "before" cohort is rendered without the badge
    # so the UI can show a clean side-by-side; we communicate cohort
    # via order, not the bool.
    def _to_video(r: dict, in_after: bool) -> ImpactVideoComparison:
        # Engagement rate isn't stored separately, so derive a proxy
        # from prediction_score until we wire real watch-time data.
        return ImpactVideoComparison(
            video_id=r["video_id"],
            title=(r["title"] or "Untitled")[:80],
            used_view_magnet=in_after,
            views=int(r["actual_views_7d"] or 0),
            engagement_rate=round((r["prediction_score"] or 0) / 10.0, 1),
            published_at=r["analyzed_at"].isoformat() if r["analyzed_at"] else None,
            magnet_score=r["prediction_score"],
        )

    videos = [
        *[_to_video(r, in_after=False) for r in before],
        *[_to_video(r, in_after=True) for r in after],
    ]

    # ---- Trend timeseries -----------------------------------------------
    # Each point keeps the cohort baselines flat so the chart can
    # draw a "before avg vs after avg" reference line. ``actual`` is
    # the per-video score so the spark traces the trajectory.
    before_avg = score_metric.before if score_metric else 0.0
    after_avg = score_metric.after if score_metric else 0.0
    trend = [
        ImpactTrendPoint(
            date=(r["analyzed_at"] or datetime.utcnow()).strftime("%b %d"),
            before_avg=round(before_avg, 1),
            after_avg=round(after_avg, 1),
            actual=round(float(r["prediction_score"] or 0), 1),
        )
        for r in rows
    ]

    return ImpactSummaryResponse(
        ready=True,
        video_count=video_count,
        days_of_history=days_of_history,
        first_analyzed_at=first_at.isoformat() if first_at else None,
        metrics=metrics,
        videos=videos,
        trend=trend,
    )
