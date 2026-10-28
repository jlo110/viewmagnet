"""Velocity Monitoring: /velocity/monitor, /velocity/channels, /velocity/videos, ..."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from src.api._common import resolve_channel_handle
from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_session
from src.database.models import (
    Channel,
    TrackedChannel,
    TrackedVideo,
    User,
    UserVideoAnalysis,
    VideoSnapshot,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["velocity"])


class VelocityMonitorRequest(BaseModel):
    """Request to add a channel or video to monitoring."""
    url: str  # Can be video URL, channel URL, or channel ID


def _checkpoint_for_age(age_hours: float) -> str:
    if age_hours >= 720:
        return "30d"
    if age_hours >= 336:
        return "14d"
    if age_hours >= 168:
        return "7d"
    if age_hours >= 72:
        return "3d"
    if age_hours >= 24:
        return "24h"
    if age_hours >= 6:
        return "6h"
    return "1h"


@router.post("/velocity/monitor")
@limiter.limit(Tier.WRITE)
async def add_to_velocity_monitor(
    request: Request,
    body: VelocityMonitorRequest,
    current_user: User = Depends(get_current_user),
):
    """Add a channel or video to velocity monitoring (auth required).

    Accepts video URLs (extracts channel automatically), channel URLs, or
    raw channel IDs (``UC...``).
    """
    from src.tracking.velocity_monitor import VelocityMonitor
    from src.youtube.client import YouTubeClient

    url = body.url.strip()
    channel_id = None
    video_id = None

    video_patterns = [
        r"youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in video_patterns:
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            break

    if not video_id and re.match(r"^[a-zA-Z0-9_-]{11}$", url):
        video_id = url

    if video_id:
        try:
            client = YouTubeClient()
            video_details = client.get_video_details([video_id])
            if video_details:
                channel_id = video_details[0].channel_id
        except Exception as e:
            logger.error(f"Failed to get video details: {e}")
            raise HTTPException(status_code=400, detail=f"Could not fetch video: {e}")

    if not channel_id:
        channel_patterns = [
            r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})",
            r"youtube\.com/@([a-zA-Z0-9_-]+)",
        ]
        for pattern in channel_patterns:
            match = re.search(pattern, url)
            if match:
                channel_id = match.group(1)
                break

        if not channel_id and re.match(r"^UC[a-zA-Z0-9_-]{22}$", url):
            channel_id = url

        if not channel_id and url.startswith("@"):
            try:
                client = YouTubeClient()
                channel_id = resolve_channel_handle(client, url)
            except Exception as e:
                logger.warning(f"Could not resolve handle {url}: {e}")

    if not channel_id:
        raise HTTPException(
            status_code=400, detail="Could not extract channel from URL"
        )

    try:
        with get_session() as session:
            monitor = VelocityMonitor(session)
            result = monitor.add_channel(channel_id)

            if video_id:
                existing = session.query(TrackedVideo).filter(
                    TrackedVideo.video_id == video_id
                ).first()

                if not existing:
                    client = YouTubeClient()
                    video_details = client.get_video_details([video_id])

                    if video_details:
                        vd = video_details[0]
                        published_at = vd.published_at or datetime.utcnow()
                        tracked = TrackedVideo(
                            video_id=video_id,
                            channel_id=channel_id,
                            title=vd.title,
                            published_at=published_at,
                            tracking_complete=False,
                        )
                        session.add(tracked)

                        hours_since = (datetime.utcnow() - published_at).total_seconds() / 3600
                        snapshot = VideoSnapshot(
                            video_id=video_id,
                            checkpoint=_checkpoint_for_age(hours_since),
                            hours_since_publish=hours_since,
                            view_count=vd.view_count,
                            like_count=vd.like_count,
                            comment_count=vd.comment_count,
                        )
                        session.add(snapshot)
                        session.commit()

                        result["video_added"] = {
                            "video_id": video_id,
                            "title": vd.title,
                            "current_views": vd.view_count,
                        }

            return result
    except Exception as e:
        logger.error(f"Failed to add to monitoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/velocity/channels")
@limiter.limit(Tier.READ)
async def get_tracked_channels(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Get all tracked channels with their stats (auth required).

    Single aggregate query (no N+1).
    """
    request.state.current_user = current_user
    try:
        with get_session() as session:
            stmt = (
                select(
                    TrackedChannel.channel_id,
                    TrackedChannel.added_at,
                    Channel.channel_name,
                    Channel.subscriber_count,
                    func.count(TrackedVideo.id).label("videos_tracked"),
                )
                .outerjoin(Channel, Channel.channel_id == TrackedChannel.channel_id)
                .outerjoin(
                    TrackedVideo,
                    TrackedVideo.channel_id == TrackedChannel.channel_id,
                )
                .where(
                    TrackedChannel.is_active.is_(True),
                    TrackedChannel.source == "user",
                )
                .group_by(
                    TrackedChannel.channel_id,
                    TrackedChannel.added_at,
                    Channel.channel_name,
                    Channel.subscriber_count,
                )
                .order_by(TrackedChannel.added_at.desc())
            )
            rows = session.execute(stmt).all()
            return {
                "channels": [
                    {
                        "channel_id": row.channel_id,
                        "channel_name": row.channel_name or "Unknown",
                        "subscriber_count": row.subscriber_count or 0,
                        "videos_tracked": int(row.videos_tracked or 0),
                        "added_at": row.added_at.isoformat() if row.added_at else None,
                        "avg_accuracy": None,
                        "growth_pattern": None,
                    }
                    for row in rows
                ]
            }
    except Exception as e:
        logger.error("velocity.channels_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/velocity/videos")
@limiter.limit(Tier.READ)
async def get_tracked_videos(
    request: Request,
    channel_id: Optional[str] = Query(None, description="Filter by channel", max_length=24),
    active_only: bool = Query(True, description="Only show active (incomplete) videos"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
):
    """Get all tracked videos with their predictions."""
    from src.tracking.velocity_monitor import VelocityMonitor
    from src.youtube.client import YouTubeClient

    try:
        with get_session() as session:
            user_channel_ids = [
                c[0]
                for c in session.query(TrackedChannel.channel_id)
                .filter(TrackedChannel.source == "user")
                .all()
            ]

            query = session.query(TrackedVideo)
            if user_channel_ids:
                query = query.filter(TrackedVideo.channel_id.in_(user_channel_ids))
            else:
                return {"videos": []}

            if channel_id:
                query = query.filter(TrackedVideo.channel_id == channel_id)
            if active_only:
                query = query.filter(TrackedVideo.tracking_complete == False)  # noqa: E712

            videos = (
                query.order_by(TrackedVideo.published_at.desc()).limit(limit).all()
            )

            # Backfill missing snapshots in batch.
            videos_needing_snapshot = []
            for video in videos:
                has_snapshot = session.query(VideoSnapshot).filter(
                    VideoSnapshot.video_id == video.video_id
                ).first()
                if not has_snapshot:
                    videos_needing_snapshot.append(video)

            if videos_needing_snapshot:
                try:
                    client = YouTubeClient()
                    details = client.get_video_details(
                        [v.video_id for v in videos_needing_snapshot]
                    )
                    details_map = {d.video_id: d for d in details}

                    for video in videos_needing_snapshot:
                        if video.video_id in details_map:
                            vd = details_map[video.video_id]
                            hours_since = (
                                datetime.utcnow() - video.published_at
                            ).total_seconds() / 3600

                            snapshot = VideoSnapshot(
                                video_id=video.video_id,
                                checkpoint=_checkpoint_for_age(hours_since),
                                hours_since_publish=hours_since,
                                view_count=vd.view_count,
                                like_count=vd.like_count,
                                comment_count=vd.comment_count,
                            )
                            session.add(snapshot)
                    session.commit()
                except Exception as e:
                    logger.warning(f"Failed to fetch snapshots for videos: {e}")

            monitor = VelocityMonitor(session)
            results: list[dict] = []

            video_ids = [v.video_id for v in videos]
            analysis_scores: dict[str, Optional[int]] = {}
            if video_ids:
                analyses = session.query(
                    UserVideoAnalysis.video_id, UserVideoAnalysis.prediction_score
                ).filter(
                    UserVideoAnalysis.video_id.in_(video_ids)
                ).all()
                for a in analyses:
                    analysis_scores[a.video_id] = (
                        int(a.prediction_score) if a.prediction_score else None
                    )

            for video in videos:
                channel = session.query(Channel).filter(
                    Channel.channel_id == video.channel_id
                ).first()

                snapshots = session.query(VideoSnapshot).filter(
                    VideoSnapshot.video_id == video.video_id
                ).order_by(VideoSnapshot.checkpoint).all()

                snapshot_list = [
                    {"checkpoint": s.checkpoint, "views": s.view_count}
                    for s in snapshots
                ]

                age_hours = (
                    datetime.utcnow() - video.published_at
                ).total_seconds() / 3600
                current_views = snapshots[-1].view_count if snapshots else 0

                prediction = monitor.get_video_prediction(video.video_id)
                predicted_30d = prediction.predicted_30d if prediction else None
                actual_30d = prediction.actual_30d if prediction else None
                accuracy = prediction.accuracy_30d if prediction else None

                predictions_dict: dict = {}
                actuals_dict: dict = {}
                if prediction:
                    for tf in ("3d", "7d", "14d", "30d"):
                        pval = getattr(prediction, f"predicted_{tf}", None)
                        aval = getattr(prediction, f"actual_{tf}", None)
                        if pval is not None:
                            predictions_dict[tf] = pval
                        if aval is not None:
                            actuals_dict[tf] = aval

                if predicted_30d and current_views > 0:
                    expected_now = (
                        predicted_30d * (age_hours / 720)
                        if age_hours < 720 else predicted_30d
                    )
                    if current_views > expected_now * 1.2:
                        trajectory = "above"
                    elif current_views < expected_now * 0.8:
                        trajectory = "below"
                    else:
                        trajectory = "on_track"
                else:
                    trajectory = "on_track"

                results.append({
                    "video_id": video.video_id,
                    "title": video.title,
                    "channel_id": video.channel_id,
                    "channel_name": channel.channel_name if channel else "Unknown",
                    "published_at": video.published_at.isoformat(),
                    "age_hours": round(age_hours, 1),
                    "current_checkpoint": _checkpoint_for_age(age_hours),
                    "current_views": current_views,
                    "magnet_score": analysis_scores.get(video.video_id),
                    "predictions": predictions_dict,
                    "actuals": actuals_dict,
                    "predicted_30d": predicted_30d,
                    "actual_30d": actual_30d,
                    "accuracy": accuracy,
                    "trajectory": trajectory,
                    "snapshots": snapshot_list,
                })

            return {"videos": results}
    except Exception as e:
        logger.error(f"Failed to get tracked videos: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/velocity/video/{video_id}")
@limiter.limit(Tier.READ)
async def get_video_velocity(
    request: Request,
    video_id: str,
    current_user: User = Depends(get_current_user),
):
    """Get detailed velocity prediction for a specific video (auth required)."""
    from src.tracking.velocity_monitor import VelocityMonitor

    try:
        with get_session() as session:
            video = session.query(TrackedVideo).filter(
                TrackedVideo.video_id == video_id
            ).first()
            if not video:
                raise HTTPException(status_code=404, detail="Video not found in tracking")

            monitor = VelocityMonitor(session)
            prediction = monitor.get_video_prediction(video_id)
            if not prediction:
                raise HTTPException(status_code=404, detail="Could not generate prediction")

            channel = session.query(Channel).filter(
                Channel.channel_id == video.channel_id
            ).first()
            snapshots = session.query(VideoSnapshot).filter(
                VideoSnapshot.video_id == video_id
            ).order_by(VideoSnapshot.checkpoint).all()

            return {
                "video_id": prediction.video_id,
                "title": prediction.title,
                "channel_id": prediction.channel_id,
                "channel_name": channel.channel_name if channel else "Unknown",
                "published_at": prediction.published_at.isoformat(),
                "hours_since_publish": round(prediction.hours_since_publish, 1),
                "current_checkpoint": prediction.current_checkpoint,
                "current_views": prediction.current_views,
                "predictions": {
                    "3d": prediction.predicted_3d,
                    "7d": prediction.predicted_7d,
                    "14d": prediction.predicted_14d,
                    "30d": prediction.predicted_30d,
                },
                "actuals": {
                    "3d": prediction.actual_3d,
                    "7d": prediction.actual_7d,
                    "14d": prediction.actual_14d,
                    "30d": prediction.actual_30d,
                },
                "accuracy": {
                    "3d": prediction.accuracy_3d,
                    "7d": prediction.accuracy_7d,
                    "14d": prediction.accuracy_14d,
                    "30d": prediction.accuracy_30d,
                },
                "channel_growth_pattern": prediction.channel_growth_pattern,
                "snapshots": [
                    {"checkpoint": s.checkpoint, "views": s.view_count}
                    for s in snapshots
                ],
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get video velocity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/velocity/accuracy")
@limiter.limit(Tier.READ)
async def get_velocity_accuracy(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Overall velocity prediction accuracy report (auth required)."""
    from src.tracking.velocity_monitor import VelocityMonitor

    try:
        with get_session() as session:
            monitor = VelocityMonitor(session)
            return monitor.get_accuracy_report()
    except Exception as e:
        logger.error(f"Failed to get accuracy report: {e}")
        raise HTTPException(status_code=500, detail=str(e))
