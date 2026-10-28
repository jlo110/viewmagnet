"""Candidate ranker API (TODO #9 / plan 6.4 v1).

POST 2-4 packaging candidates (titles, optionally a thumbnail per title) for
the same video → ranked with reach scores (where thumbnails are given), the
MrBeast packaging rubric per title, and the winner. The "which of these should
I upload?" endpoint.
"""
from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User
from src.features.candidate_ranker import rank_candidates

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["candidate-ranker"])

_MAX_THUMB_BYTES = 8 * 1024 * 1024  # thumbnails, not videos
_ALLOWED = {".jpg", ".jpeg", ".png", ".webp"}


@router.post("/rank/candidates")
@limiter.limit(Tier.LLM_HEAVY)
async def rank_packaging_candidates(
    request: Request,  # noqa: ARG001 — slowapi
    titles: List[str] = Form(...),
    thumbnails: Optional[List[UploadFile]] = File(default=None),
    idea: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_user),
):
    """Rank 2-4 title(+thumbnail) candidates for one video.

    ``thumbnails``, when provided, must align with ``titles`` by position
    (use an empty filename to skip a slot). Reach scores require thumbnails;
    titles-only requests still get the full rubric ranking.
    """
    titles = [t for t in (titles or []) if (t or "").strip()]
    if not 2 <= len(titles) <= 4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide 2-4 non-empty titles.",
        )
    thumbs = thumbnails or []
    if thumbs and len(thumbs) > len(titles):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="More thumbnails than titles.",
        )

    candidates: List[dict] = []
    for i, title in enumerate(titles):
        image_bytes = None
        if i < len(thumbs) and thumbs[i] and thumbs[i].filename:
            import os

            suffix = os.path.splitext(thumbs[i].filename)[1].lower()
            if suffix not in _ALLOWED:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Thumbnail {i}: unsupported type '{suffix}'.",
                )
            data = await thumbs[i].read()
            if len(data) > _MAX_THUMB_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Thumbnail {i} too large (max 8MB).",
                )
            image_bytes = data
        candidates.append({"title": title, "image_bytes": image_bytes})

    plan = getattr(current_user, "plan", None) or "free"
    report = rank_candidates(candidates, idea=idea, user_id=current_user.id, plan=plan)
    return report
