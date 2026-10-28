"""Per-niche coverage — the "are we tracking enough?" admin view.

Surfaces ``NicheCoverage`` (spec: docs/specs/stratified-expansion.md): which
niches are densely enough tracked to surface live signal, and which are starved
and should drive the next stratified-expansion sweep. Admin-gated.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.api.limiter import Tier, limiter
from src.auth.admin import require_admin
from src.database.connection import get_session

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])


@router.get("/admin/coverage")
@limiter.limit(Tier.READ)
async def niche_coverage(
    request: Request,  # noqa: ARG001 — slowapi
    current_user=Depends(require_admin),  # noqa: ARG001
):
    """Per-niche tracking coverage + the starved-niche list (expansion targets)."""
    try:
        from src.features.niche_coverage import get_coverage

        with get_session() as db:
            return get_coverage(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("coverage.read_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"coverage read failed: {exc}",
        )
