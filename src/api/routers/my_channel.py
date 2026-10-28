"""Connect Your Own Channel (3.1) — point the validated detector at the user's
*own* uploads and act on it.

Studio shows you your numbers; it doesn't tell you "this one is breaking out and
it's the durable kind — make a sequel now." This does: on connect we enroll the
user's channel into collection (same path as the watchlist), then run the same
detector + durability grader on their uploads and attach a durability-driven
recommendation. Honest: we detect + coach, we never predict that a sequel will
also break out.
"""
from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_session
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["my-channel"])


def _connected_channels(db, user_id: int) -> dict:
    """{channel_id: channel_name} for the user's active YouTube connections."""
    from src.database.models import YouTubeConnection

    rows = db.query(YouTubeConnection.channel_id, YouTubeConnection.channel_name).filter(
        YouTubeConnection.user_id == user_id, YouTubeConnection.is_active.is_(True)).all()
    return {cid: name for cid, name in rows}


@router.post("/my-channel/enroll")
@limiter.limit(Tier.WRITE)
async def enroll_my_channels(
    request: Request,  # noqa: ARG001
    current_user: User = Depends(get_current_user),
):
    """Enroll all of the user's connected channels into collection (idempotent).

    Connecting after this feature shipped auto-enrolls in the OAuth callback;
    this back-fills channels connected earlier. Breakouts only show up on their
    *future* uploads once collected."""
    from src.api.routers.watchlist import _enroll_for_collection

    with get_session() as db:
        channels = _connected_channels(db, current_user.id)
        if not channels:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="No connected YouTube channel. Connect one first.")
        for cid in channels:
            _enroll_for_collection(db, cid)
    return {"enrolled": list(channels), "count": len(channels)}


@router.get("/my-channel/breakouts")
@limiter.limit(Tier.READ)
async def my_channel_breakouts(
    request: Request,  # noqa: ARG001
    checkpoint: str = Query(default="6h", pattern="^(1h|6h|24h)$"),
    max_age_hours: float = Query(default=168.0, ge=1.0, le=336.0),
    current_user: User = Depends(get_current_user),
):
    """Breakouts on the user's OWN uploads, each with a durability badge and a
    durability-driven "make a sequel / capture the spike" recommendation."""
    from src.features.breakout_detector import detect_live_breakouts
    from src.features.durability_grader import grade
    from src.features.sequel_recommender import sequel_recommendation
    from src.features.topic_saturation import annotate_with_topics

    with get_session() as db:
        mine = _connected_channels(db, current_user.id)
        if not mine:
            return {"connected": False, "checkpoint": checkpoint, "count": 0, "breakouts": [],
                    "updated_at": datetime.utcnow().isoformat() + "Z"}
        try:
            items = detect_live_breakouts(
                db, checkpoint=checkpoint, min_probability=0.6,
                max_age_hours=max_age_hours, min_views=100.0, limit=2000,
            )
            items = [it for it in items if it.get("channel_id") in mine]
            items = annotate_with_topics(db, items)
            from src.api.routers.breakouts import _annotate_niche
            items = _annotate_niche(db, items)
            grades = grade(db, [it["video_id"] for it in items], checkpoint=checkpoint)
            for it in items:
                d = grades.get(it["video_id"], {"label": "too_early", "probability": None})
                it["durability"] = d
                it["recommendation"] = sequel_recommendation(d.get("label"))
                it["channel_name"] = mine.get(it["channel_id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("my_channel.breakouts_failed", error=str(exc))
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail=f"my-channel breakouts failed: {exc}")
    return {"connected": True, "checkpoint": checkpoint, "count": len(items),
            "breakouts": items, "updated_at": datetime.utcnow().isoformat() + "Z"}


@router.get("/my-channel/analytics")
@limiter.limit(Tier.READ)
async def my_channel_analytics(
    request: Request,  # noqa: ARG001
    current_user: User = Depends(get_current_user),
):
    """Real owner-side analytics (CTR, impressions, avg view %, retention curve)
    for the user's connected channels — the honest, validated half of 3.2. Pure
    display: this is the *real* click data, not the dead packaging proxy, and we
    do NOT predict off it until the gated channel-grouped re-validation passes.
    """
    from src.features.owner_analytics import get_stored_analytics

    with get_session() as db:
        connected = bool(_connected_channels(db, current_user.id))
        data = get_stored_analytics(db, current_user.id)
    return {"connected": connected, **data}


@router.post("/my-channel/analytics/refresh")
@limiter.limit(Tier.MEDIA_HEAVY)
async def refresh_my_channel_analytics(
    request: Request,  # noqa: ARG001
    current_user: User = Depends(get_current_user),
):
    """Pull fresh analytics for the current user's channels on demand (rather than
    waiting for the daily job). Uses the user's own OAuth/analytics quota."""
    from src.features.owner_analytics import pull_owner_analytics

    with get_session() as db:
        if not _connected_channels(db, current_user.id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="No connected YouTube channel.")
        try:
            result = pull_owner_analytics(db, user_id=current_user.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("my_channel.analytics_refresh_failed", error=str(exc))
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail=f"analytics refresh failed: {exc}")
    return result
