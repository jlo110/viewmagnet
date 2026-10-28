"""GET /trends/analyze: topic trend score + recommendation."""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["trends"])


def _to_jsonable(value: Any) -> Any:
    """Recursively coerce numpy / pandas scalars to native Python types.

    ``TrendAnalyzer`` runs on pandas / numpy data and leaks ``numpy.bool_``
    / ``numpy.int64`` / etc. into its dataclass fields (especially through
    ``pytrends`` related-queries DataFrames). FastAPI's ``jsonable_encoder``
    treats those as unknown objects and crashes with::

        TypeError: 'numpy.bool' object is not iterable

    Doing the coercion at the boundary is safer than peppering ``int()`` /
    ``bool()`` casts through every code path that produces these values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except (TypeError, ValueError):
            pass
    return str(value)


@router.get("/trends/analyze")
@limiter.limit(Tier.READ)
async def analyze_trends(
    request: Request,
    topic: str = Query(..., max_length=300),
    category: str = Query(default="general", max_length=50),
    current_user: User = Depends(get_current_user),
):
    """Analyze trends for a topic using ``TrendAnalyzer``."""
    try:
        from src.features.trend_analyzer import TrendAnalyzer

        analyzer = TrendAnalyzer()
        result = analyzer.analyze_topic(topic=topic)

        return _to_jsonable({
            "topic": topic,
            "trend_score": result.current_interest,
            "trend_direction": result.trend_direction,
            "peak_interest": result.peak_interest,
            "current_interest": result.current_interest,
            "change_7d": result.change_7d,
            "change_30d": result.change_30d,
            "is_seasonal": result.is_seasonal,
            "best_months": result.best_months,
            "related_rising": result.related_rising,
            "recommendation": result.recommendation,
            "timing": {
                "best_time_to_post": "Based on your niche's peak engagement times",
                "urgency": (
                    "high" if result.trend_direction == "breakout"
                    else "medium" if result.trend_direction == "rising"
                    else "low"
                ),
            },
        })
    except Exception as e:
        logger.error(f"Trend analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trends/momentum")
@limiter.limit(Tier.READ)
async def topic_momentum(
    request: Request,  # noqa: ARG001
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """Which topics are heating up across YouTube right now, from our own breakout
    feed — each topic's breakout density (share of its videos breaking out) and
    whether that's rising/peaking/fading. Market timing, NOT a packaging predictor;
    descriptive read on where audiences are rewarding content. None until computed.
    """
    from src.database.connection import get_session
    from src.features.topic_saturation import get_topic_momentum

    from src.features.timing_insights import wave_stats

    with get_session() as db:
        data = get_topic_momentum(db, limit=limit)
        waves = wave_stats(db)
    if data is None:
        return {"computed_at": None, "topics": [], "wave_duration": waves}
    # How long these waves typically last -- turns a snapshot into timing.
    return {**data, "wave_duration": waves}
