"""GET /channel/overview: snapshot of channel metadata + recent videos."""
from __future__ import annotations

import re

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api._common import resolve_channel_handle
from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["channel"])


@router.get("/channel/overview")
@limiter.limit(Tier.READ)
async def get_channel_overview(
    request: Request,
    channel_url: str = Query(..., max_length=500),
    current_user: User = Depends(get_current_user),
):
    """Get overview stats for a YouTube channel (auth required)."""
    request.state.current_user = current_user
    from src.youtube.client import YouTubeClient

    try:
        client = YouTubeClient()
        channel_id = None
        url = channel_url.strip()

        if url.startswith("@"):
            channel_id = resolve_channel_handle(client, url)
        elif url.startswith("UC") and len(url) == 24:
            channel_id = url
        elif "youtube.com" in url or "youtu.be" in url:
            match = re.search(r"/channel/(UC[a-zA-Z0-9_-]{22})", url)
            if match:
                channel_id = match.group(1)
            else:
                handle_match = (
                    re.search(r"/@([a-zA-Z0-9_-]+)", url)
                    or re.search(r"/c/([a-zA-Z0-9_-]+)", url)
                    or re.search(r"/user/([a-zA-Z0-9_-]+)", url)
                )
                if handle_match:
                    handle = handle_match.group(1)
                    channel_id = resolve_channel_handle(client, handle)
        else:
            channel_id = resolve_channel_handle(client, url)

        if not channel_id:
            raise HTTPException(status_code=404, detail="Channel not found")

        channels = client.get_channel_details([channel_id])
        if not channels:
            raise HTTPException(status_code=404, detail="Channel not found")

        ch = channels[0]

        uploads_playlist = f"UU{channel_id[2:]}"  # UC... -> UU...
        recent_videos = []
        total_recent_views = 0
        try:
            playlist_response = client.get_channel_videos(
                uploads_playlist_id=uploads_playlist,
                max_results=10,
            )
            if playlist_response and "items" in playlist_response:
                video_ids = [
                    item["snippet"]["resourceId"]["videoId"]
                    for item in playlist_response["items"]
                ]
                if video_ids:
                    video_details = client.get_video_details(video_ids)
                    for vd in video_details:
                        total_recent_views += vd.view_count
                        recent_videos.append({
                            "video_id": vd.video_id,
                            "title": vd.title,
                            "view_count": vd.view_count,
                            "published_at": vd.published_at.isoformat() if vd.published_at else None,
                            "thumbnail_url": vd.thumbnail_url,
                        })
        except Exception as e:
            logger.warning(f"Failed to get recent videos: {e}")

        return {
            "channel_id": channel_id,
            "channel_name": ch.channel_name,
            "subscriber_count": ch.subscriber_count,
            "total_views": ch.total_views,
            "video_count": ch.video_count,
            "thumbnail_url": ch.thumbnail_url,
            "recent_views": total_recent_views,
            "recent_videos": recent_videos,
            "avg_views_per_video": (
                total_recent_views // len(recent_videos) if recent_videos else 0
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get channel overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))
