"""Social Publishing: /social/accounts, /social/publish, /social/publish-clip.

DEPRECATED — use /distribution/* for all user-facing publish workflows.

These routes were the original direct-file-path publishing primitives.
The /distribution/* router supersedes them with DB-tracked jobs, outcomes
polling, and the Distribution Hub UI. These endpoints are kept for
internal use by the shorts-clip workflow but should not be called by
new frontend code.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["social"])


class SocialPublishRequest(BaseModel):
    """Request to publish video to social platforms."""
    video_path: str
    title: str
    description: str = ""
    platforms: List[str] = ["tiktok", "youtube"]
    hashtags: List[str] = []
    scheduled_time: Optional[str] = None  # ISO format datetime


class SocialPublishResponse(BaseModel):
    """Response from social publishing."""
    video_path: str
    title: str
    platforms_requested: List[str]
    results: List[Dict]
    all_successful: bool
    any_successful: bool


class SocialAccountStatus(BaseModel):
    """One row in the connected-accounts response. Some platforms
    expose multiple linked accounts (e.g. multiple TikTok handles),
    so the response wraps each platform's value in a list."""

    connected: bool = Field(..., description="True if the platform has at least one valid token")
    handle: Optional[str] = Field(default=None, description="Display handle when known")
    expires_at: Optional[str] = Field(
        default=None, description="ISO-8601 token expiry when known"
    )

    model_config = {"extra": "allow"}


class SocialAccountsResponse(BaseModel):
    accounts: Dict[str, List[SocialAccountStatus]] = Field(
        ..., description="Per-platform connection rows (tiktok / instagram / youtube)"
    )
    message: str = Field(..., description="Human-readable status / next-step")


class SocialClipPublishResponse(SocialPublishResponse):
    """Same shape as /social/publish plus the clip's source path/index
    so the caller can correlate the publish with the underlying
    extracted clip."""

    clip_index: int = Field(..., ge=0)
    clip_path: str = Field(..., description="Absolute path to the clip that was published")


@router.get("/social/accounts", response_model=SocialAccountsResponse)
async def get_social_accounts(
    current_user: User = Depends(get_current_user),
) -> SocialAccountsResponse:
    """Get connected social media accounts.

    Returns the connection status for TikTok, Instagram, and YouTube.
    """
    try:
        from src.features.social_publisher import SocialPublisher

        publisher = SocialPublisher(use_upload_post=True)
        try:
            accounts = await publisher.get_connected_accounts()
            return SocialAccountsResponse(
                accounts=accounts,
                message="Configure API keys in environment to enable publishing",
            )
        finally:
            await publisher.close()

    except Exception as e:
        logger.error(f"Failed to get social accounts: {e}")
        return SocialAccountsResponse(
            accounts={
                "tiktok": [SocialAccountStatus(connected=False)],
                "instagram": [SocialAccountStatus(connected=False)],
                "youtube": [SocialAccountStatus(connected=False)],
            },
            message=str(e),
        )


@router.post("/social/publish", response_model=SocialPublishResponse)
async def publish_to_social(
    request: SocialPublishRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Publish a video to social media platforms (TikTok / Instagram / YouTube).

    Supports immediate or scheduled posting via Upload-Post (preferred) or
    direct platform tokens (``TIKTOK_ACCESS_TOKEN`` etc.).
    """
    try:
        from src.features.social_publisher import publish_shorts

        if not os.path.exists(request.video_path):
            raise HTTPException(
                status_code=400, detail=f"Video file not found: {request.video_path}"
            )

        scheduled_time = None
        if request.scheduled_time:
            try:
                scheduled_time = datetime.fromisoformat(request.scheduled_time)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Invalid scheduled_time format. Use ISO format "
                        "(YYYY-MM-DDTHH:MM:SS)"
                    ),
                )

        result = await publish_shorts(
            video_path=request.video_path,
            title=request.title,
            description=request.description,
            platforms=request.platforms,
            hashtags=request.hashtags,
            scheduled_time=scheduled_time,
            use_upload_post=True,
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return SocialPublishResponse(
            video_path=result["video_path"],
            title=result["title"],
            platforms_requested=result["platforms_requested"],
            results=result["results"],
            all_successful=result["all_successful"],
            any_successful=result["any_successful"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Social publishing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/social/publish-clip/{clip_index}", response_model=SocialClipPublishResponse
)
@limiter.limit(Tier.MEDIA_HEAVY)
async def publish_clip_to_social(
    request: Request,
    clip_index: int,
    analysis_dir: str = Query(..., description="Directory containing extracted clips", max_length=500),
    title: str = Query(..., description="Video title", max_length=300),
    description: str = Query(default="", description="Video description", max_length=5000),
    platforms: str = Query(default="tiktok,youtube", description="Comma-separated platforms"),
    hashtags: str = Query(default="", description="Comma-separated hashtags", max_length=500),
    current_user: User = Depends(get_current_user),
) -> SocialClipPublishResponse:
    """Publish a specific clip from shorts analysis to social platforms."""
    try:
        from src.features.social_publisher import publish_shorts

        vertical_clip_path = os.path.join(analysis_dir, f"clip_{clip_index}_vertical.mp4")
        if not os.path.exists(vertical_clip_path):
            vertical_clip_path = os.path.join(analysis_dir, f"clip_{clip_index}.mp4")

        if not os.path.exists(vertical_clip_path):
            raise HTTPException(
                status_code=404,
                detail=f"Clip {clip_index} not found in {analysis_dir}",
            )

        platform_list = [p.strip() for p in platforms.split(",") if p.strip()]
        hashtag_list = [h.strip() for h in hashtags.split(",") if h.strip()]

        result = await publish_shorts(
            video_path=vertical_clip_path,
            title=title,
            description=description,
            platforms=platform_list,
            hashtags=hashtag_list,
            use_upload_post=True,
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return SocialClipPublishResponse(
            clip_index=clip_index,
            clip_path=vertical_clip_path,
            video_path=result["video_path"],
            title=result["title"],
            platforms_requested=result["platforms_requested"],
            results=result["results"],
            all_successful=result["all_successful"],
            any_successful=result["any_successful"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Clip publishing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
