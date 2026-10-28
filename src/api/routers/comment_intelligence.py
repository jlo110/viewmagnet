"""Comment Intelligence API (Phase 7.4).

Surfaces LLM-extracted signal from the comments the tracker captured for a
video: sentiment, top viewer questions, next-video ideas, an FAQ → pinned-
comment suggestion, and praise/criticism themes.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_async_session
from src.database.models import User, VideoComment
from src.features.comment_intelligence import analyze_comments

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["comment-intelligence"])


@router.get("/comment-intelligence/{video_id}")
@limiter.limit(Tier.LLM_HEAVY)
async def comment_intelligence(
    request: Request,
    video_id: str,
    current_user: User = Depends(get_current_user),
):
    """Return actionable intelligence from a tracked video's captured comments."""
    async with get_async_session() as db:
        rows = (await db.execute(
            select(VideoComment.text, VideoComment.like_count)
            .where(VideoComment.video_id == video_id)
            .order_by(VideoComment.like_count.desc())
            .limit(100)
        )).all()

    if rows:
        comments = [{"text": r[0], "like_count": r[1]} for r in rows]
    else:
        # Not in the tracked-set capture (true for ~any user's own video) — fetch
        # on-demand from the API so this works for any video, not just the ~1%
        # we've captured.
        try:
            from src.features.comment_analyzer import CommentFetcher
            fetched = CommentFetcher().fetch_comments(video_id, max_results=100, order="relevance")
            comments = [{"text": c.text, "like_count": getattr(c, "like_count", 0)} for c in fetched]
        except Exception as e:
            logger.warning("comment_intelligence.fetch_failed", video_id=video_id, error=str(e)[:80])
            comments = []
        if not comments:
            raise HTTPException(
                status_code=404,
                detail="No comments available for this video (it may be new, have comments "
                       "disabled, or be unavailable).",
            )
    insights = analyze_comments(
        comments, user_id=current_user.id, plan=getattr(current_user, "plan", "free")
    )
    return {"video_id": video_id, **insights}
