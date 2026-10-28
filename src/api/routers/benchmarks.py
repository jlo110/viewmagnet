"""GET /benchmarks/*: measured view-trajectory percentiles per niche and format.

These are descriptions of collected snapshots — at each checkpoint, what view
counts the 10th..99th percentile video in a niche actually reached. No model,
no forecast.

History worth keeping: this router used to return invented constants
(``pct_with_face: 78``, ``optimal_upload_hour: 14``) from an except-block
fallback whenever its lookup failed, so the numbers users saw were fabricated.
Nothing here falls back to made-up values: when a niche lacks a large enough
sample it falls back to the pooled all-niches cell (flagged with ``pooled``),
and when nothing has been computed yet it returns 404.
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_session
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["benchmarks"])


@router.get("/benchmarks/trajectory")
@limiter.limit(Tier.READ)
async def trajectory_benchmarks(
    request: Request,  # noqa: ARG001
    niche: Optional[str] = Query(default=None, description="YouTube category id, e.g. 20"),
    is_short: bool = Query(default=False),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """The full measured curve for a niche/format: percentiles at every checkpoint."""
    from src.features.niche_benchmarks import CHECKPOINTS, get_benchmark

    with get_session() as db:
        curve = []
        for cp in CHECKPOINTS:
            b = get_benchmark(db, niche, is_short, cp)
            if b is not None:
                curve.append(b)
    if not curve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Benchmarks haven't been computed yet.")
    return {"niche": niche, "is_short": is_short, "checkpoints": curve}


@router.get("/benchmarks/rank")
@limiter.limit(Tier.READ)
async def rank_against_niche(
    request: Request,  # noqa: ARG001
    views: float = Query(..., ge=0),
    checkpoint: str = Query(default="24h", pattern="^(1h|6h|24h|3d|7d|14d|30d)$"),
    niche: Optional[str] = Query(default=None),
    is_short: bool = Query(default=False),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """Where a view count sits against its niche at a checkpoint.

    e.g. 24h views of 40,000 in Gaming long-form -> "72nd percentile, 1.8x median".
    """
    from src.features.niche_benchmarks import rank_video

    with get_session() as db:
        result = rank_video(db, views, niche, is_short, checkpoint)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No benchmark for that niche/checkpoint yet.")
    return result


@router.get("/benchmarks/timing")
@limiter.limit(Tier.READ)
async def timing_benchmarks(
    request: Request,  # noqa: ARG001
    dimension: str = Query(default="hour", pattern="^(hour|dow)$"),
    niche: Optional[str] = Query(default=None),
    is_short: bool = Query(default=False),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """Measured publish-timing effect: hit rate by publish hour (UTC) or weekday.

    "Hit" = landing in the top 20% of that channel's OWN videos by 24h views, so
    channel size cannot confound it. The real spread is ~5 points against a 20%
    baseline -- genuine at this sample size, but far smaller than typical "best
    time to post" advice, and correlational (channels don't randomise when they
    publish). The response carries that caveat explicitly.
    """
    from src.features.timing_insights import get_timing

    with get_session() as db:
        data = get_timing(db, dimension, niche, is_short)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Timing benchmarks haven't been computed yet.")
    return data
