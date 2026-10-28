"""Format Radar — emerging title/packaging formats mined from live breakouts.

The live counterpart to a static format archive: formats ranked by momentum and
openness so creators catch a pattern while it's still rising and uncrowded. See
``src/features/emerging_formats.py`` and ``docs/specs/emerging-formats.md``.
User-facing (auth'd); works on the tracked set, so it needs no user OAuth.
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
router = APIRouter(tags=["formats"])

# Free plan sees the top N formats (by the chosen sort), the rest is gated —
# the "free sees 5 of N" desire mechanic, but our list updates daily.
_FREE_LIMIT = 5


@router.get("/formats")
@limiter.limit(Tier.READ)
async def list_formats(
    request: Request,  # noqa: ARG001 — slowapi
    niche: Optional[str] = Query(default=None, description="category id filter, e.g. 20"),
    sort: str = Query(default="momentum", pattern="^(momentum|outlier|views|count)$"),
    openness: Optional[str] = Query(default=None, pattern="^(open|warming|crowded)$"),
    min_reliability: Optional[str] = Query(default=None, pattern="^(low|medium|high)$"),
    limit: int = Query(default=40, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    """Emerging formats, ranked. Free plan is capped to the top few + a locked count."""
    try:
        from src.features.emerging_formats import get_formats

        with get_session() as db:
            result = get_formats(
                db, niche=niche, sort=sort, openness=openness,
                min_reliability=min_reliability, limit=limit,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("formats.failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"format radar failed: {exc}",
        )

    # Paywall disabled while testing — return all formats to every plan.
    # (Re-enable by gating on `getattr(current_user, "plan", None)` later.)
    return result
