"""YouTube Analytics for connected channels + per-niche insights."""
from __future__ import annotations

import json
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_session
from src.database.models import User, YouTubeConnection

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["analytics"])


@router.get("/analytics/channel")
@limiter.limit(Tier.READ)
async def get_channel_analytics(
    request: Request,
    channel_id: str = Query(...),
    days: int = Query(default=28, ge=7, le=90),
    current_user: User = Depends(get_current_user),
):
    """Get YouTube Analytics for a connected channel.

    Requires authentication and a YouTube account connection.
    """
    with get_session() as session:
        connection = session.query(YouTubeConnection).filter(
            YouTubeConnection.user_id == current_user.id,
            YouTubeConnection.channel_id == channel_id,
            YouTubeConnection.is_active == True,  # noqa: E712
        ).first()

        if not connection:
            raise HTTPException(
                status_code=404,
                detail="YouTube channel not connected. Connect via /auth/youtube",
            )

        try:
            from src.integrations.youtube_analytics import YouTubeAnalyticsClient
        except ImportError:
            raise HTTPException(status_code=500, detail="Google auth libraries not installed")

        creds_dict = {
            "token": connection.access_token,
            "refresh_token": connection.refresh_token,
            "token_uri": connection.token_uri,
            "client_id": connection.client_id,
            "client_secret": connection.client_secret,
            "scopes": json.loads(connection.scopes),
        }

        client = YouTubeAnalyticsClient()
        client.credentials_from_dict(creds_dict)

        try:
            analytics = client.get_channel_analytics(days=days)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch analytics: {str(e)}")

        connection.last_synced = datetime.utcnow()
        session.commit()

    return {
        "channel_name": analytics.channel_name,
        "total_views": analytics.total_views,
        "watch_time_hours": analytics.total_watch_time_hours,
        "subscribers_gained": analytics.subscribers_gained,
        "avg_ctr": analytics.avg_ctr,
        "avg_view_duration": analytics.avg_view_duration_seconds,
        "top_videos": [
            {
                "video_id": v.video_id,
                "title": v.title,
                "views": v.views,
                "ctr": v.ctr,
                "avg_duration": v.avg_view_duration_seconds,
            }
            for v in analytics.top_videos[:5]
        ],
    }


@router.get("/analytics/video/{video_id}")
@limiter.limit(Tier.READ)
async def get_video_analytics(
    request: Request,
    video_id: str,
    channel_id: str = Query(...),
    current_user: User = Depends(get_current_user),
):
    """Get detailed analytics for a specific video.

    Requires authentication and a YouTube account connection.
    """
    with get_session() as session:
        connection = session.query(YouTubeConnection).filter(
            YouTubeConnection.user_id == current_user.id,
            YouTubeConnection.channel_id == channel_id,
            YouTubeConnection.is_active == True,  # noqa: E712
        ).first()

        if not connection:
            raise HTTPException(status_code=404, detail="YouTube channel not connected")

        try:
            from src.integrations.youtube_analytics import YouTubeAnalyticsClient
        except ImportError:
            raise HTTPException(status_code=500, detail="Google auth libraries not installed")

        creds_dict = {
            "token": connection.access_token,
            "refresh_token": connection.refresh_token,
            "token_uri": connection.token_uri,
            "client_id": connection.client_id,
            "client_secret": connection.client_secret,
            "scopes": json.loads(connection.scopes),
        }

        client = YouTubeAnalyticsClient()
        client.credentials_from_dict(creds_dict)

        try:
            analytics = client.get_video_analytics(video_id)
            comparison = client.get_ctr_comparison(video_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch analytics: {str(e)}")

    return {
        "video_id": analytics.video_id,
        "title": analytics.title,
        "views": analytics.views,
        "watch_time_minutes": analytics.watch_time_minutes,
        "avg_view_duration": analytics.avg_view_duration_seconds,
        "avg_view_percentage": analytics.avg_view_percentage,
        "impressions": analytics.impressions,
        "ctr": analytics.ctr,
        "ctr_comparison": comparison,
        "traffic_sources": analytics.traffic_sources,
        "engagement": {
            "likes": analytics.likes,
            "comments": analytics.comments,
            "shares": analytics.shares,
        },
    }


@router.get("/niche/{category}/insights")
@limiter.limit(Tier.READ)
async def get_niche_insights(request: Request, category: str):
    """Get niche-specific insights and patterns.

    Returns validated phrases, avoid patterns, and benchmarks.
    """
    try:
        from src.features.niche_patterns import NichePatternDiscovery

        with get_session() as session:
            discovery = NichePatternDiscovery(session)
            patterns = discovery.discover_patterns(category, min_videos=100)

            if patterns.video_count == 0:
                raise HTTPException(status_code=404, detail=f"No data for category: {category}")

            return {
                "category": category,
                "video_count": patterns.video_count,
                "validated_phrases": [
                    {
                        "pattern": p.phrase,
                        "impact": p.impact_str,
                        "sample_size": p.count,
                        "confidence": p.reliability,
                    }
                    for p in (patterns.validated_phrases or [])[:5]
                ],
                "avoid_patterns": [
                    {
                        "pattern": a.pattern,
                        "impact": a.impact_str,
                        "sample_size": 0,
                        "confidence": a.confidence,
                    }
                    for a in (patterns.avoid_details or [])[:5]
                ],
                "power_words": patterns.power_words[:10] if patterns.power_words else [],
                "avg_title_length": patterns.avg_title_length,
                "avg_description_length": patterns.avg_description_length,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get niche insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/niche/categories")
async def list_niche_categories():
    """List all available niche categories."""
    return {
        "categories": [
            {"id": "gaming", "name": "Gaming", "icon": "🎮"},
            {"id": "tech_reviews", "name": "Tech & Reviews", "icon": "💻"},
            {"id": "entertainment_vlogs", "name": "Entertainment & Vlogs", "icon": "🎬"},
            {"id": "education_howto", "name": "Education & How-To", "icon": "📚"},
            {"id": "lifestyle", "name": "Lifestyle", "icon": "✨"},
            {"id": "music_creative", "name": "Music & Creative", "icon": "🎵"},
            {"id": "news_politics", "name": "News & Politics", "icon": "📰"},
            {"id": "commentary_essay", "name": "Commentary & Essay", "icon": "💭"},
        ]
    }
