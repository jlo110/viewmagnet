"""Post-publish outcomes rollup (Week 10).

Reads ``PublishedMetricSnapshot`` rows that
:mod:`src.features.publish_metrics` writes and rolls them up into the
shapes the Distribution Hub "Outcomes" tab + the Video Analyzer
"Recommendation effectiveness" card consume:

  * :func:`list_user_outcomes` — per-published-post timeline of
    snapshots, latest first. Powers the Outcomes tab list view.
  * :func:`rollup_recommendation_effectiveness` — groups outcomes
    by the originating CTA (read from
    :attr:`src.database.models.EditSession.cta_provenance`) so the
    user can see "videos that took the Lead Magnet advice averaged
    +28% retention vs your channel baseline".

Why split the rollup from the collector module: the collector is
write-heavy and runs from the RQ worker; the rollup is read-heavy
and runs on the API request path. Keeping them in separate modules
means tests for either don't have to load the other's dependencies
(e.g. the request can compute a rollup without importing the
fetcher registry).

Attribution chain:

  * DistributionJob.source_video_url is the published render's source
    (an R2 / local file URL). When the user kicked off the render
    from a Studio EditSession, that same URL appears on the
    EditSession (and on StudioProjectClips → EditSessions for a
    project render). We use the URL as a join key — coarse but
    reliable, since each render emits a unique R2 path.
  * The EditSession's ``cta_provenance`` JSON dict (set when the
    user landed via a deep link with ``?cta=...``) gives us the
    originating recommendation. Sessions opened directly contribute
    to the "no recommendation" baseline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import structlog
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.database.models import (
    DistributionJob,
    DistributionResult,
    EditSession,
    PublishedMetricSnapshot,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_cta(raw: Optional[str]) -> Optional[dict]:
    """Decode an EditSession.cta_provenance JSON blob.

    Returns ``None`` for missing / unparseable rows so callers can
    treat "no attribution" uniformly regardless of whether the
    column was empty or had corrupt JSON."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    return parsed if isinstance(parsed, dict) else None


def _attribution_for_source(
    db: Session, *, user_id: int, source_video_url: Optional[str]
) -> Optional[dict]:
    """Return the CTA provenance for the EditSession that produced
    a render with ``source_video_url``, if any.

    The match is naive (string equality on the source URL) which is
    fine because each rendered MP4 lives at a unique R2 path. When
    the same source URL has multiple sessions (a user re-edits the
    same clip with different CTAs), we pick the most recently
    updated session to bias toward the actual edit that produced
    the published render.
    """
    if not source_video_url:
        return None
    stmt = (
        select(EditSession)
        .where(EditSession.user_id == user_id)
        .where(EditSession.source_video_url == source_video_url)
        .order_by(desc(EditSession.id))
        .limit(1)
    )
    session_row = db.execute(stmt).scalar_one_or_none()
    if session_row is None:
        return None
    return _parse_cta(session_row.cta_provenance)


# ---------------------------------------------------------------------------
# Outcome shapes — these are dataclasses (not Pydantic) because the
# router wraps them in its own Pydantic response models. Keeps the
# rollup module free of FastAPI imports for cheap unit-testability.
# ---------------------------------------------------------------------------


@dataclass
class SnapshotPoint:
    window_key: str
    sampled_at: str
    views: Optional[int]
    likes: Optional[int]
    comments: Optional[int]
    shares: Optional[int]
    watch_time_seconds: Optional[float]
    avg_view_percentage: Optional[float]
    click_through_rate: Optional[float]


@dataclass
class PublishedOutcome:
    """Per (DistributionResult) outcome: the published post + its
    snapshot timeline + (optional) attribution to a recommendation.
    """

    distribution_job_id: int
    distribution_result_id: int
    platform: str
    posted_url: Optional[str]
    published_at: str
    title: str
    source_video_url: Optional[str]
    # Latest snapshot per window_key, keyed for cheap UI lookup.
    snapshots: dict[str, SnapshotPoint]
    # Convenience: the most recent snapshot regardless of window.
    latest: Optional[SnapshotPoint]
    # Recommendation attribution (empty dict if user opened Studio
    # directly without a deep-link CTA).
    cta_provenance: Optional[dict]


# ---------------------------------------------------------------------------
# Rollup queries
# ---------------------------------------------------------------------------


def list_user_outcomes(
    db: Session,
    *,
    user_id: int,
    limit: int = 50,
) -> list[PublishedOutcome]:
    """Return the user's recent published posts with their snapshots.

    Ordered by publication time, most-recent first. Each row carries
    a ``snapshots`` dict keyed by ``window_key`` so the UI can
    render "1h / 24h / 7d / 30d" columns without re-sorting.
    """
    # Pull successful results + parent jobs for the user.
    result_stmt = (
        select(DistributionResult, DistributionJob)
        .join(
            DistributionJob,
            DistributionResult.job_id == DistributionJob.id,
        )
        .where(DistributionJob.user_id == user_id)
        .where(DistributionResult.status == "success")
        .order_by(desc(DistributionResult.completed_at))
        .limit(limit)
    )
    rows = list(db.execute(result_stmt).all())
    if not rows:
        return []

    result_ids = [r.id for r, _ in rows]

    # Bulk-fetch all snapshots for the page of results so we avoid
    # an N+1. Postgres will pick the
    # ``idx_pms_result_window`` composite index for this lookup.
    snap_stmt = select(PublishedMetricSnapshot).where(
        PublishedMetricSnapshot.distribution_result_id.in_(result_ids)
    )
    snaps_by_result: dict[int, dict[str, PublishedMetricSnapshot]] = {}
    for snap in db.execute(snap_stmt).scalars().all():
        bucket = snaps_by_result.setdefault(
            snap.distribution_result_id, {}
        )
        # If two snapshots exist for the same window (race; see
        # ``record_metric_snapshot`` design note), prefer the
        # newest. We sort first so the assignment ends up with the
        # latest.
        existing = bucket.get(snap.window_key)
        if existing is None or snap.sampled_at >= existing.sampled_at:
            bucket[snap.window_key] = snap

    outcomes: list[PublishedOutcome] = []
    for result, job in rows:
        snaps = snaps_by_result.get(result.id, {})
        snap_points = {
            key: SnapshotPoint(
                window_key=s.window_key,
                sampled_at=s.sampled_at.isoformat() + "Z",
                views=s.views,
                likes=s.likes,
                comments=s.comments,
                shares=s.shares,
                watch_time_seconds=s.watch_time_seconds,
                avg_view_percentage=s.avg_view_percentage,
                click_through_rate=s.click_through_rate,
            )
            for key, s in snaps.items()
        }
        # "Latest" — prefer the longest-window snapshot we have, since
        # it carries the most information. Falls back to whatever the
        # most-recent sampled_at is when window order is ambiguous.
        latest = None
        for key in ("30d", "7d", "24h", "1h"):
            if key in snap_points:
                latest = snap_points[key]
                break
        if latest is None and snap_points:
            latest = max(
                snap_points.values(),
                key=lambda p: p.sampled_at,
            )

        published_at = (
            result.completed_at or result.created_at
        ).isoformat() + "Z"
        outcomes.append(
            PublishedOutcome(
                distribution_job_id=job.id,
                distribution_result_id=result.id,
                platform=result.platform,
                posted_url=result.posted_url,
                published_at=published_at,
                title=job.title,
                source_video_url=job.source_video_url,
                snapshots=snap_points,
                latest=latest,
                cta_provenance=_attribution_for_source(
                    db,
                    user_id=user_id,
                    source_video_url=job.source_video_url,
                ),
            )
        )
    return outcomes


# ---------------------------------------------------------------------------
# Recommendation-effectiveness rollup
# ---------------------------------------------------------------------------


@dataclass
class RecommendationGroup:
    """One bucket in the "did following the recommendation help?" view."""

    tool: str  # "hook_lab" | "script_writer" | ... | "baseline"
    label: str  # Human-readable group label for the UI.
    sample_count: int  # Number of published posts in the group.
    avg_views: Optional[float]
    avg_likes: Optional[float]
    avg_engagement_rate: Optional[float]  # (likes + comments) / views
    avg_retention: Optional[float]  # avg_view_percentage averaged


def _avg(values: list[float]) -> Optional[float]:
    """Mean of a list; ``None`` for empty input.

    The Outcomes UI distinguishes "we have no data" from "the answer
    is literally 0" — ``None`` flows through to ``"—"`` in the
    rendered cell rather than a misleading zero.
    """
    cleaned = [v for v in values if v is not None]
    return sum(cleaned) / len(cleaned) if cleaned else None


def _engagement_rate(snap: SnapshotPoint) -> Optional[float]:
    """(likes + comments) / views — the most platform-portable rate."""
    if not snap.views:
        return None
    likes = snap.likes or 0
    comments = snap.comments or 0
    if likes + comments == 0:
        return 0.0
    return (likes + comments) / snap.views


def rollup_recommendation_effectiveness(
    outcomes: list[PublishedOutcome],
) -> list[RecommendationGroup]:
    """Group published outcomes by originating recommendation tool.

    Renders the "Recommendation effectiveness" card. Each group
    summarizes the outcomes that came from a particular recommended
    tool ("hook_lab", "script_writer", etc.) plus a "baseline" group
    for posts that didn't come from a deep-link CTA. The dashboard
    compares each tool group against the baseline.

    We pick the longest-window snapshot per outcome for the rollup
    (30d > 7d > 24h > 1h) so a sample of mixed-age posts averages
    apples-to-apples. Posts with no snapshots yet contribute to the
    ``sample_count`` but not to the averages (NULL-respecting math).
    """
    by_tool: dict[str, list[PublishedOutcome]] = {}
    for outcome in outcomes:
        tool = (
            (outcome.cta_provenance or {}).get("tool") or "baseline"
        )
        by_tool.setdefault(tool, []).append(outcome)

    label_map = {
        "hook_lab": "Hook Lab",
        "script_writer": "Script Writer",
        "ab_tester": "A/B Tester",
        "title_generator": "Title Generator",
        "thumbnails": "Thumbnails",
        "loop_designer": "Loop Designer",
        "shorts": "Shorts",
        "distribution": "Distribution",
        "baseline": "No recommendation (baseline)",
    }

    groups: list[RecommendationGroup] = []
    for tool, items in by_tool.items():
        latests = [o.latest for o in items if o.latest is not None]
        views = [s.views for s in latests if s.views is not None]
        likes = [s.likes for s in latests if s.likes is not None]
        retentions = [
            s.avg_view_percentage
            for s in latests
            if s.avg_view_percentage is not None
        ]
        engagement = [_engagement_rate(s) for s in latests]
        groups.append(
            RecommendationGroup(
                tool=tool,
                label=label_map.get(tool, tool.replace("_", " ").title()),
                sample_count=len(items),
                avg_views=_avg([float(v) for v in views]),
                avg_likes=_avg([float(v) for v in likes]),
                avg_engagement_rate=_avg(
                    [v for v in engagement if v is not None]
                ),
                avg_retention=_avg(retentions),
            )
        )
    # Always render the baseline first (or last? — first feels more
    # honest because every comparison anchors to it). The rest are
    # ordered by sample size desc.
    baseline = [g for g in groups if g.tool == "baseline"]
    others = sorted(
        [g for g in groups if g.tool != "baseline"],
        key=lambda g: g.sample_count,
        reverse=True,
    )
    return baseline + others
