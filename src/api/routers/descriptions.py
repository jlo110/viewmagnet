"""YouTube Description Generator: POST /descriptions/generate."""
from __future__ import annotations

from typing import Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["descriptions"])


class DescriptionGenerateRequest(BaseModel):
    """Request to generate a YouTube description."""
    title: str
    transcript: Optional[str] = None
    transcript_segments: Optional[List[Dict]] = None
    language: str = "en"
    video_duration: Optional[float] = None
    include_chapters: bool = True
    include_hashtags: bool = True


class DescriptionResponse(BaseModel):
    """Response with a generated description."""
    description: str
    chapters: List[Dict]
    hashtags: List[str]
    summary: str
    language: str


@router.post("/descriptions/generate", response_model=DescriptionResponse)
@limiter.limit(Tier.LLM_HEAVY)
async def generate_youtube_description_endpoint(
    request: Request,
    body: DescriptionGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate a YouTube description with chapters and hashtags."""
    try:
        from src.features.description_generator import DescriptionGenerator

        generator = DescriptionGenerator()
        # Attribute the LLM call to the right user (and rate-limit at
        # LLM_HEAVY tier — was previously unbounded).
        generator.set_budget_context(current_user.id, current_user.plan or "free")
        result = generator.generate(
            title=body.title,
            transcript=body.transcript,
            transcript_segments=body.transcript_segments,
            language=body.language,
            video_duration=body.video_duration,
            include_chapters=body.include_chapters,
            include_hashtags=body.include_hashtags,
        )

        return DescriptionResponse(
            description=result.description,
            chapters=[
                {
                    "timestamp": c.timestamp,
                    "title": c.title,
                    "start_seconds": c.start_seconds,
                }
                for c in result.chapters
            ],
            hashtags=result.hashtags,
            summary=result.summary,
            language=result.language,
        )
    except Exception as e:
        logger.error(f"Description generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
