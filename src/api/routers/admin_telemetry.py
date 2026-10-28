"""Admin telemetry dashboard endpoints (Week 8 P3 polish).

Surfaces the rolled-up render-pipeline telemetry from
:func:`src.queue.telemetry_summary.summarize_renders` so an operator
can answer the four questions that matter most without grepping logs:

  1. Is the render funnel converting? (success / failure / cancel rates)
  2. How busy are we right now? (queue depth + surge level)
  3. What's failing, and is it the same thing every time?
     (top error types)
  4. Are we keeping up over time? (daily queued/completed/failed series)

Endpoints (all gated by :func:`src.auth.admin.require_admin`):

  * ``GET /admin/telemetry/renders`` — the funnel summary, scoped to
    a rolling lookback window (default 24h, max 30d).
  * ``GET /admin/telemetry/queue`` — current worker queue depth plus
    the classified surge level. Cheap; safe to poll from the UI on
    a short interval (~5s).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.admin import require_admin
from src.database.connection import get_session
from src.queue import get_queue_depth
from src.queue.surge import classify_depth
from src.queue.telemetry_summary import summarize_renders

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class WindowInfo(BaseModel):
    since: str
    until: str
    lookback_seconds: int


class CountsBlock(BaseModel):
    queued: int = 0
    started: int = 0
    completed: int = 0
    failed: int = 0
    dlq: int = 0
    cancelled: int = 0
    budget_blocked: int = 0
    retried: int = 0


class RatesBlock(BaseModel):
    success_rate: float
    failure_rate: float
    cancel_rate: float


class DurationBlock(BaseModel):
    p50: Optional[float] = None
    p95: Optional[float] = None
    samples: int = 0


class TopError(BaseModel):
    error_type: str
    count: int


class DayBucket(BaseModel):
    date: str
    queued: int = 0
    completed: int = 0
    failed: int = 0


class RenderTelemetryResponse(BaseModel):
    window: WindowInfo
    counts: CountsBlock
    rates: RatesBlock
    wait_seconds: DurationBlock
    render_seconds: DurationBlock
    top_errors: List[TopError] = Field(default_factory=list)
    by_day: List[DayBucket] = Field(default_factory=list)


class QueueSnapshotResponse(BaseModel):
    """Live queue depth + classified surge level for the admin UI."""

    available: bool
    level: str  # "normal" | "busy" | "slammed"
    queue_depth: int
    started: int
    deferred: int = 0
    scheduled: int = 0
    estimated_wait_seconds: int


class QuotaKeyBlock(BaseModel):
    key_index: int
    used: int
    remaining: int
    exhausted: bool


class QuotaDayBucket(BaseModel):
    date: str
    used: int
    remaining: int
    pct_remaining: float


class QuotaResponse(BaseModel):
    """Today's YouTube quota consumption + recent history for the admin UI."""

    date: str
    capacity: int
    num_keys: int
    total_used: int
    total_remaining: int
    pct_remaining: float
    keys_exhausted: int
    by_operation: dict = Field(default_factory=dict)
    by_key: List[QuotaKeyBlock] = Field(default_factory=list)
    history: List[QuotaDayBucket] = Field(default_factory=list)
    alert: Optional[dict] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


# Cap the lookback at 30 days — the audit table grows fast and a
# 90-day scan is expensive even with the index. The dashboard only
# needs 24h-7d in practice; the longer windows are for ad-hoc
# investigation.
_MAX_LOOKBACK_HOURS = 24 * 30


@router.get(
    "/admin/telemetry/renders", response_model=RenderTelemetryResponse
)
@limiter.limit(Tier.READ)
async def render_telemetry(
    request: Request,  # noqa: ARG001 — required by slowapi limiter
    lookback_hours: int = Query(default=24, ge=1, le=_MAX_LOOKBACK_HOURS),
    top_errors: int = Query(default=5, ge=1, le=25),
    current_user=Depends(require_admin),  # noqa: ARG001
):
    """Return the rolled-up render funnel for the lookback window.

    The window is right-anchored on "now" (UTC). Callers that want a
    sliding bar chart should call this on a debounce when the window
    selector changes — the query is index-backed and typically
    <50ms even for 30 days of history.
    """
    until = datetime.utcnow()
    since = until - timedelta(hours=lookback_hours)
    try:
        with get_session() as db:
            data = summarize_renders(
                db, since=since, until=until, top_errors=top_errors
            )
    except Exception as exc:  # noqa: BLE001
        # Telemetry must never bring down the admin page — surface a
        # 503 with a hint instead of a 500 so the operator knows to
        # check the DB, not their browser.
        logger.warning(
            "admin.telemetry.summary_failed",
            error=str(exc),
            lookback_hours=lookback_hours,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"telemetry rollup failed: {exc}",
        )
    return RenderTelemetryResponse(**data)


@router.get("/admin/telemetry/queue", response_model=QueueSnapshotResponse)
@limiter.limit(Tier.READ)
async def queue_telemetry(
    request: Request,  # noqa: ARG001
    current_user=Depends(require_admin),  # noqa: ARG001
):
    """Return the live worker queue depth + surge classification.

    Cheap enough to poll on a 5–10s interval from the dashboard
    without straining Redis (it's four ``LLEN`` calls). When Redis
    isn't configured, ``available`` is False and the rest of the
    fields are zeros — the UI then hides the queue card."""
    raw = get_queue_depth()
    surge = classify_depth(raw)
    snapshot_dict = raw or {}
    return QueueSnapshotResponse(
        available=surge.available,
        level=surge.level,
        queue_depth=surge.queue_depth,
        started=surge.started,
        deferred=int(snapshot_dict.get("deferred") or 0),
        scheduled=int(snapshot_dict.get("scheduled") or 0),
        estimated_wait_seconds=surge.estimated_wait_seconds,
    )


@router.get("/admin/quota", response_model=QuotaResponse)
@limiter.limit(Tier.READ)
async def quota_usage(
    request: Request,  # noqa: ARG001
    history_days: int = Query(default=7, ge=1, le=30),
    current_user=Depends(require_admin),  # noqa: ARG001
):
    """Return today's YouTube API quota consumption + recent daily history.

    Answers "are our jobs running out of quota?" — total used/remaining across
    all keys, the per-operation breakdown (discovery's ``playlistItems.list`` is
    usually the sink), per-key exhaustion, and an ``alert`` block when remaining
    quota is below the configured threshold. Backed by ``youtube_quota_usage``,
    which the scheduler flushes every 5 min, so it survives restarts.
    """
    from src.config import get_settings
    from src.youtube.quota_store import (
        evaluate_quota_alert,
        get_today_usage,
        get_usage_history,
    )

    try:
        with get_session() as db:
            quota_status = get_today_usage(db)
            history = get_usage_history(db, days=history_days)
    except Exception as exc:  # noqa: BLE001
        logger.warning("admin.quota.read_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"quota read failed: {exc}",
        )
    quota_status["alert"] = evaluate_quota_alert(
        quota_status, get_settings().youtube_quota_alert_pct
    )
    quota_status["history"] = history
    return QuotaResponse(**quota_status)


@router.get("/admin/collection-health")
@limiter.limit(Tier.READ)
async def collection_health(
    request: Request,  # noqa: ARG001
    lookback_days: int = Query(default=40, ge=1, le=120),
    current_user=Depends(require_admin),  # noqa: ARG001
):
    """Per-checkpoint velocity-collection hit-rate (windows captured / eligible).

    Surfaces silent dataset erosion: a checkpoint whose ``recent_hit_rate`` is
    dropping means we're sampling late or not at all (quota exhaustion / stalled
    scheduler) even though the collection jobs still log success. ``alerts``
    lists checkpoints below ``collection_hit_rate_alert``.
    """
    from src.config import get_settings
    from src.tracking.collection_health import (
        evaluate_health_alert,
        get_collection_health,
        get_stream_anomalies,
    )

    try:
        with get_session() as db:
            summary = get_collection_health(db, lookback_days=lookback_days)
            summary["stream_anomalies"] = get_stream_anomalies(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("admin.collection_health.read_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"collection-health read failed: {exc}",
        )
    summary["alerts"] = evaluate_health_alert(
        summary, get_settings().collection_hit_rate_alert
    )
    return summary


@router.get("/admin/breakouts")
@limiter.limit(Tier.READ)
async def live_breakouts(
    request: Request,  # noqa: ARG001
    checkpoint: str = Query(default="6h", pattern="^(1h|6h|24h)$"),
    min_probability: float = Query(default=0.7, ge=0.0, le=1.0),
    max_age_hours: float = Query(default=48.0, ge=1.0, le=336.0),
    min_views: float = Query(default=1000.0, ge=0.0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user=Depends(require_admin),  # noqa: ARG001
):
    """Tracked videos breaking out right now (trend/competitor feed).

    Scores recent tracked uploads at ``checkpoint`` against their channel's own
    leave-one-out baseline and returns those above ``min_probability`` (calibrated
    P(breakout)), ranked. Works on the collection alone — no user accounts needed.
    Sanity-gated by ``min_views`` and a channel-baseline floor so a relative spike
    on a near-zero video doesn't register.
    """
    from src.features.breakout_detector import detect_live_breakouts
    from src.features.topic_saturation import annotate_with_topics

    try:
        with get_session() as db:
            items = detect_live_breakouts(
                db,
                checkpoint=checkpoint,
                min_probability=min_probability,
                max_age_hours=max_age_hours,
                min_views=min_views,
                limit=limit,
            )
            # 8.2: attach each breakout's topic saturation — "breaking out AND
            # the topic is crowded" vs "breaking out on open ground" are
            # different calls to action.
            items = annotate_with_topics(db, items)
    except Exception as exc:  # noqa: BLE001
        logger.warning("admin.breakouts.failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"breakout detection failed: {exc}",
        )
    return {"checkpoint": checkpoint, "count": len(items), "breakouts": items}


@router.get("/admin/topics")
@limiter.limit(Tier.READ)
async def topic_saturation(
    request: Request,  # noqa: ARG001
    limit: int = Query(default=50, ge=1, le=200),
    min_channels: int = Query(default=2, ge=1),
    current_user=Depends(require_admin),  # noqa: ARG001
):
    """Current topic clusters across the tracked set (saturation index, 8.2).

    What the ~4.8k tracked channels are publishing right now, clustered by
    title similarity. ``size``/``channel_count`` = how saturated a topic is;
    compare batches over time for topic velocity. Computed by the 6-hourly
    ``topic_clusters`` scheduler job; this reads the latest batch.
    """
    from src.features.topic_saturation import get_latest_topics

    try:
        with get_session() as db:
            data = get_latest_topics(db, limit=limit, min_channels=min_channels)
    except Exception as exc:  # noqa: BLE001
        logger.warning("admin.topics.read_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"topics read failed: {exc}",
        )
    if data is None:
        return {"computed_at": None, "topics": [], "note": "no batch computed yet"}
    return data


@router.get("/admin/topics/velocity")
@limiter.limit(Tier.READ)
async def topic_velocity(
    request: Request,  # noqa: ARG001
    limit: int = Query(default=30, ge=1, le=100),
    current_user=Depends(require_admin),  # noqa: ARG001
):
    """Rising / new / falling topics across the two latest batches (8.2).

    The timing-advisor view: ``trend=new|rising`` with low ``channel_count`` =
    open ground (post now); large+``falling`` = the wave already crested.
    """
    from src.features.topic_saturation import get_topic_velocity

    try:
        with get_session() as db:
            data = get_topic_velocity(db, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("admin.topic_velocity.read_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"topic velocity read failed: {exc}",
        )
    if data is None:
        return {"topics": [], "note": "need two batches; the job runs every 6h"}
    return data
