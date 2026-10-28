"""Rebuild a cross-sectional training set from channels' upload history.

The historical scrape/time-series was lost (memory/ml-data-disconnected.md), so
the served content classifier (74.6%) has no live dataset behind it. This walks
active English channels, pulls each one's recent uploads + final stats via the
API, and writes ``BackfillVideo`` rows labelled with the video's *outlier* —
final views vs the channel's own median (log space), the same channel-relative
target the live breakout detector uses.

Cheap: ~2 quota units/channel (1 ``playlistItems.list`` + 1 ``videos.list``).
Idempotent + bounded: a channel with existing rows is skipped, and only
``max_channels`` are processed per run, so it drains over days without touching
live collection. Runs on spare quota (we use ~4% of the daily budget).
"""
from __future__ import annotations

import json
import math
from statistics import median
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

VIDEOS_PER_CHANNEL = 50      # one playlist page; the channel's most recent uploads
MIN_VIDEOS_FOR_LABEL = 5     # need enough uploads to form a stable channel median


def _uploads_playlist_id(channel_id: str) -> Optional[str]:
    """A channel's uploads playlist id is its id with the ``UC`` prefix swapped
    to ``UU`` — derivable without an API call."""
    if channel_id and channel_id.startswith("UC") and len(channel_id) > 2:
        return "UU" + channel_id[2:]
    return None


def _channels_to_backfill(session, max_channels: int) -> list[str]:
    """Active channels with no backfill rows yet (idempotent drain)."""
    from sqlalchemy import select

    from src.database.models import BackfillVideo, TrackedChannel

    done = set(session.execute(select(BackfillVideo.channel_id).distinct()).scalars().all())
    active = session.execute(
        select(TrackedChannel.channel_id).where(TrackedChannel.is_active.is_(True))
    ).scalars().all()
    return [c for c in active if c not in done][:max_channels]


def backfill_channel_history(
    session,
    client,
    max_channels: int = 400,
    videos_per_channel: int = VIDEOS_PER_CHANNEL,
) -> dict:
    """Pull recent uploads for un-backfilled channels and write labelled rows."""
    from src.database.models import BackfillVideo

    targets = _channels_to_backfill(session, max_channels)
    if not targets:
        logger.info("backfill.nothing_due")
        return {"channels": 0, "videos": 0}

    channels_done = 0
    videos_written = 0
    for channel_id in targets:
        playlist = _uploads_playlist_id(channel_id)
        if not playlist:
            continue
        try:
            resp = client.get_channel_videos(playlist, max_results=videos_per_channel)
            vids = [
                (it.get("contentDetails") or {}).get("videoId")
                for it in resp.get("items", [])
            ]
            vids = [v for v in vids if v]
            if len(vids) < MIN_VIDEOS_FOR_LABEL:
                continue
            details = client.get_video_details(vids)
        except Exception as e:
            logger.warning("backfill.channel_failed", channel=channel_id, error=str(e)[:80])
            continue

        # Channel baseline = median of long-form views (Shorts skew low/separate).
        longform = [v for v in details if (v.duration_seconds or 0) >= 60]
        pool = longform if len(longform) >= MIN_VIDEOS_FOR_LABEL else details
        views = [max(0, v.view_count) for v in pool]
        if len(views) < MIN_VIDEOS_FOR_LABEL:
            continue
        med = float(median(views)) or 1.0

        for v in details:
            outlier = (v.view_count or 0) / med if med else None
            session.add(BackfillVideo(
                video_id=v.video_id,
                channel_id=channel_id,
                title=v.title or "",
                thumbnail_url=v.thumbnail_url,
                tags=json.dumps(v.tags) if v.tags else None,
                published_at=v.published_at,
                duration_seconds=v.duration_seconds,
                is_short=(v.duration_seconds or 0) < 60,
                youtube_category_id=v.youtube_category_id,
                default_audio_language=v.default_audio_language,
                view_count=v.view_count or 0,
                like_count=v.like_count,
                comment_count=v.comment_count,
                channel_median_views=med,
                outlier=round(outlier, 4) if outlier is not None else None,
                log_outlier=round(math.log(outlier), 4) if outlier and outlier > 0 else None,
            ))
            videos_written += 1
        session.commit()
        channels_done += 1

    logger.info("backfill.complete", channels=channels_done, videos=videos_written)
    return {"channels": channels_done, "videos": videos_written}
