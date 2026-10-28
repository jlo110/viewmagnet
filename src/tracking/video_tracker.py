"""Video tracker for temporal performance monitoring."""
import json
from datetime import datetime, timedelta
from typing import List, Optional
from dataclasses import dataclass

from sqlalchemy import and_, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import structlog

from src.database.models import TrackedChannel, TrackedVideo, VideoSnapshot
from src.youtube.client import YouTubeClient

logger = structlog.get_logger()


# Checkpoint key -> the TrackedVideo boolean column that records it as resolved.
# Lets the "due for a snapshot" filter run in SQL instead of loading every
# incomplete video and testing windows in Python.
_CHECKPOINT_COL = {
    "1h": TrackedVideo.checkpoint_1h,
    "6h": TrackedVideo.checkpoint_6h,
    "24h": TrackedVideo.checkpoint_24h,
    "3d": TrackedVideo.checkpoint_3d,
    "7d": TrackedVideo.checkpoint_7d,
    "14d": TrackedVideo.checkpoint_14d,
    "30d": TrackedVideo.checkpoint_30d,
}


# Checkpoint windows: (key, target_hours, grace_hours).
#
# A checkpoint is collectable ONLY within [target, target + grace] hours after
# publish. This is the crux of velocity-data integrity: if we sample late, the
# view count must be labelled with the checkpoint whose window we are actually
# in — never an earlier one. Sampling a 7-day-old video and storing its count
# as the "1h" value (the old behaviour) silently corrupts the training set.
# Once a window's grace expires uncollected, that checkpoint is permanently
# "missed" (no snapshot row → an honest gap in the trajectory) rather than
# backfilled with stale data. Mirrors the proven pattern in
# ``src/features/publish_metrics.py`` (MetricWindow / due_windows).
CHECKPOINT_WINDOWS: list[tuple[str, float, float]] = [
    ("1h", 1, 2),       # collect between 1h and 3h
    ("6h", 6, 6),       # 6h – 12h
    ("24h", 24, 12),    # 24h – 36h
    ("3d", 72, 24),     # 3d – 4d
    ("7d", 168, 48),    # 7d – 9d
    ("14d", 336, 72),   # 14d – 17d
    ("30d", 720, 120),  # 30d – 35d
]

# Order + lookups derived from the windows (single source of truth).
CHECKPOINTS = {key: target for key, target, _grace in CHECKPOINT_WINDOWS}
_GRACE = {key: grace for key, _target, grace in CHECKPOINT_WINDOWS}

# After this age a video is considered fully resolved and tracking stops, even
# if some checkpoints were missed (prevents the active set growing unbounded).
_MAX_TRACK_HOURS = 720 + 120  # last window's target + grace


@dataclass
class NewVideoInfo:
    """Info about a newly discovered video."""
    video_id: str
    channel_id: str
    title: str
    published_at: datetime
    thumbnail_url: Optional[str]


@dataclass
class TrackingResult:
    """Result of a tracking operation."""
    channels_checked: int
    new_videos_found: int
    snapshots_collected: int
    errors: int


class VideoTracker:
    """
    Tracks video performance over time.
    
    Part 4: Temporal Training Set Collection
    - Monitors tracked channels for new uploads
    - Collects performance snapshots at checkpoints
    - Builds training data for prediction models
    """
    
    def __init__(
        self,
        session: Session,
        youtube_client: Optional[YouTubeClient] = None,
    ):
        """Initialize tracker."""
        self.session = session
        self.client = youtube_client or YouTubeClient()
    
    def check_for_new_videos(
        self,
        max_channels: Optional[int] = None,
    ) -> TrackingResult:
        """
        Check tracked channels for new uploads.
        
        Args:
            max_channels: Maximum channels to check
            
        Returns:
            TrackingResult with statistics
        """
        result = TrackingResult(
            channels_checked=0,
            new_videos_found=0,
            snapshots_collected=0,
            errors=0
        )
        
        # Get channels to check (prioritize those not checked recently)
        query = self.session.query(TrackedChannel).filter(
            TrackedChannel.is_active == True
        ).order_by(
            TrackedChannel.last_checked.asc().nullsfirst()
        )
        
        if max_channels:
            query = query.limit(max_channels)
        
        channels = query.all()
        
        for channel in channels:
            try:
                new_videos = self._check_channel(channel)
                result.channels_checked += 1
                result.new_videos_found += len(new_videos)
                
                # Update last checked
                channel.last_checked = datetime.utcnow()
                if new_videos:
                    channel.last_video_found = datetime.utcnow()
                
            except Exception as e:
                logger.error(
                    "channel_check_error",
                    channel_id=channel.channel_id,
                    error=str(e)
                )
                result.errors += 1
            
            # Check quota
            quota = self.client.get_quota_status()
            if quota["total_remaining"] < 10:
                logger.warning("low_quota_stopping")
                break
        
        self.session.commit()
        
        logger.info(
            "new_video_check_complete",
            channels=result.channels_checked,
            new_videos=result.new_videos_found
        )
        
        return result
    
    def _check_channel(self, channel: TrackedChannel) -> List[NewVideoInfo]:
        """Check a single channel for new videos."""
        # Get uploads playlist ID
        uploads_playlist_id = f"UU{channel.channel_id[2:]}"
        
        # Get recent videos
        response = self.client.get_channel_videos(
            uploads_playlist_id,
            max_results=10  # Only check recent uploads
        )
        
        new_videos = []
        now = datetime.utcnow()
        cutoff = now - timedelta(days=2)  # Only consider videos from last 2 days
        
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})
            
            video_id = content.get("videoId")
            if not video_id:
                continue
            
            # Parse publish date
            published_str = snippet.get("publishedAt", "")
            try:
                published_at = datetime.fromisoformat(
                    published_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except (ValueError, AttributeError):
                continue
            
            # Skip old videos
            if published_at < cutoff:
                continue
            
            # Check if already tracked
            existing = self.session.query(TrackedVideo).filter(
                TrackedVideo.video_id == video_id
            ).first()
            
            if existing:
                continue
            
            # Add to tracking
            tracked = TrackedVideo(
                video_id=video_id,
                channel_id=channel.channel_id,
                title=snippet.get("title", ""),
                published_at=published_at,
                thumbnail_url=snippet.get("thumbnails", {}).get("high", {}).get("url"),
            )
            self.session.add(tracked)
            
            new_videos.append(NewVideoInfo(
                video_id=video_id,
                channel_id=channel.channel_id,
                title=snippet.get("title", ""),
                published_at=published_at,
                thumbnail_url=tracked.thumbnail_url,
            ))
        
        return new_videos
    
    def collect_snapshots(
        self,
        max_videos: Optional[int] = None,
    ) -> TrackingResult:
        """
        Collect performance snapshots for videos due for checkpoints.
        
        Args:
            max_videos: Maximum videos to process
            
        Returns:
            TrackingResult with statistics
        """
        result = TrackingResult(
            channels_checked=0,
            new_videos_found=0,
            snapshots_collected=0,
            errors=0
        )
        
        now = datetime.utcnow()

        # Resolve, once, the exact checkpoint each due video should be sampled
        # for *right now* (within-window only). This is the single source of
        # truth — collection below never re-derives it independently.
        due = self._get_videos_due_for_snapshot(now, max_videos)  # list[(video, checkpoint)]

        # First, retire any checkpoints whose window has fully expired (mark
        # them resolved without a snapshot) and complete aged-out videos. This
        # keeps the active set bounded and the trajectory's gaps honest.
        self._retire_expired(now)

        if not due:
            self.session.commit()
            return result

        due_by_id = {v.video_id: (v, cp) for v, cp in due}
        video_ids = list(due_by_id.keys())

        unfetchable = 0
        for i in range(0, len(video_ids), 50):
            batch_ids = video_ids[i:i + 50]
            try:
                video_stats = self.client.get_video_details(batch_ids)

                # Videos the API didn't return are deleted/private. Resolve
                # their due checkpoint as missed (no snapshot — the honest gap),
                # otherwise they stay "due" for the whole window and, being the
                # oldest, permanently clog the front of the oldest-first queue:
                # observed post-migration as every cycle re-fetching the same
                # 6,000 dead ids and never reaching live videos behind them.
                # A transient miss costs one checkpoint, not the video.
                returned_ids = {info.video_id for info in video_stats}
                for vid in batch_ids:
                    if vid not in returned_ids:
                        gone_video, gone_cp = due_by_id[vid]
                        self._mark_checkpoint(gone_video, gone_cp)
                        unfetchable += 1

                for info in video_stats:
                    entry = due_by_id.get(info.video_id)
                    if not entry:
                        continue
                    tracked, checkpoint = entry

                    hours_since_publish = (now - tracked.published_at).total_seconds() / 3600
                    views = info.view_count or 0
                    # A YouTube Short is <= 60s (vertical detection isn't exposed
                    # by the Data API, so duration is the reliable proxy). Shorts
                    # and long-form have different view curves — tag so models
                    # never mix them.
                    is_short = (
                        info.duration_seconds <= 60
                        if info.duration_seconds is not None
                        else None
                    )
                    snapshot = VideoSnapshot(
                        video_id=info.video_id,
                        checkpoint=checkpoint,
                        hours_since_publish=hours_since_publish,
                        view_count=views,
                        like_count=info.like_count,
                        comment_count=info.comment_count,
                        views_per_hour=views / hours_since_publish if hours_since_publish > 0 else 0,
                        engagement_rate=(info.like_count + info.comment_count) / views if views > 0 else 0,
                        # Normalized early-engagement signals.
                        like_view_ratio=info.like_count / views if views > 0 else 0,
                        comment_view_ratio=info.comment_count / views if views > 0 else 0,
                        # Metadata snapshot (Phase 7.1) — already in `info`, free.
                        title=info.title,
                        thumbnail_url=info.thumbnail_url,
                        duration_seconds=info.duration_seconds,
                        youtube_category_id=info.youtube_category_id,
                        tag_count=len(info.tags) if info.tags is not None else None,
                        is_short=is_short,
                        # Phase 8.5 capture-now — also already in `info`, free.
                        description=info.description,
                        tags=json.dumps(info.tags) if info.tags else None,
                        live_broadcast_content=getattr(info, "live_broadcast_content", None),
                        default_audio_language=getattr(info, "default_audio_language", None),
                    )
                    self.session.add(snapshot)

                    # Persist this row immediately so a unique-constraint clash
                    # on (video_id, checkpoint) — possible if the boolean flags
                    # ever desync from the table — doesn't roll back the whole
                    # batch (the bug behind the UniqueViolation in snapshots.log).
                    try:
                        self.session.flush()
                    except IntegrityError:
                        self.session.rollback()
                        self._mark_checkpoint(tracked, checkpoint)  # already exists; resolve it
                        continue

                    self._mark_checkpoint(tracked, checkpoint)

                    if checkpoint == "30d":
                        tracked.tracking_complete = True
                        tracked.final_views = info.view_count
                        tracked.final_likes = info.like_count
                        tracked.final_comments = info.comment_count

                    result.snapshots_collected += 1

            except IntegrityError:
                self.session.rollback()
                result.errors += 1
            except Exception as e:
                logger.error("snapshot_batch_error", error=str(e))
                result.errors += 1

            quota = self.client.get_quota_status()
            if quota["total_remaining"] < 10:
                logger.warning("low_quota_stopping")
                break

        self.session.commit()
        
        logger.info(
            "snapshot_collection_complete",
            snapshots=result.snapshots_collected,
            errors=result.errors,
            unfetchable=unfetchable,
        )
        
        return result
    
    def _get_videos_due_for_snapshot(
        self,
        now: datetime,
        limit: Optional[int] = None,
    ) -> List[tuple]:
        """Videos with a checkpoint currently *inside its window*.

        Returns ``[(video, checkpoint_key), ...]`` — at most one checkpoint per
        video (the latest window currently active). Videos whose only pending
        checkpoints are out-of-window are excluded here and retired separately.
        """
        # Push the window test into SQL: a video is due only if SOME unresolved
        # checkpoint's window currently contains its age. For window [target,
        # target+grace) that means published_at in (now-(target+grace), now-target].
        # This loads only the few videos actually in-window right now instead of
        # every incomplete video (~400k) — the difference between a multi-MB,
        # timeout-prone scan and a tiny, fast query.
        window_clauses = []
        for key, target, grace in CHECKPOINT_WINDOWS:
            col = _CHECKPOINT_COL[key]
            lo = now - timedelta(hours=target + grace)  # published_at > lo
            hi = now - timedelta(hours=target)          # published_at <= hi
            window_clauses.append(and_(
                col == False,  # noqa: E712 — unresolved checkpoint
                TrackedVideo.published_at > lo,
                TrackedVideo.published_at <= hi,
            ))

        query = self.session.query(TrackedVideo).filter(
            TrackedVideo.tracking_complete == False,  # noqa: E712
            or_(*window_clauses),
        ).order_by(TrackedVideo.published_at)
        if limit:
            query = query.limit(limit)

        due: List[tuple] = []
        for video in query.all():
            # _due_checkpoint remains the source of truth for WHICH checkpoint
            # (it applies the "prefer the latest in-window target" tie-break).
            cp = self._due_checkpoint(video, now)
            if cp is not None:
                due.append((video, cp))
        return due

    def _due_checkpoint(self, video: TrackedVideo, now: datetime) -> Optional[str]:
        """The checkpoint to sample for ``video`` right now, or None.

        A checkpoint is due iff ``target <= hours_since_publish < target + grace``
        and it hasn't been resolved yet. If several are simultaneously in-window
        (after a long gap), prefer the *latest* target so we capture the most
        informative late point rather than a stale early one.
        """
        hours = (now - video.published_at).total_seconds() / 3600
        candidate: Optional[str] = None
        candidate_target = -1.0
        for key, target, grace in CHECKPOINT_WINDOWS:
            if self._has_checkpoint(video, key):
                continue
            if target <= hours < target + grace and target > candidate_target:
                candidate, candidate_target = key, target
        return candidate

    def _retire_expired(self, now: datetime) -> int:
        """Finish tracking videos past the last checkpoint window, in one bulk
        UPDATE instead of loading every incomplete video.

        Missed checkpoints no longer need eager boolean-marking: the SQL window
        filter in ``_get_videos_due_for_snapshot`` already excludes any checkpoint
        whose window has passed (a video only reappears while it's in-window and
        unresolved), and the honest record of a miss is the absence of a snapshot
        row — never backfilled with stale data. So retirement is purely an age-out.
        Returns the number of videos retired."""
        cutoff = now - timedelta(hours=_MAX_TRACK_HOURS)
        result = self.session.execute(
            update(TrackedVideo)
            .where(
                TrackedVideo.tracking_complete == False,  # noqa: E712
                TrackedVideo.published_at < cutoff,
            )
            .values(tracking_complete=True)
        )
        return result.rowcount or 0
    
    def _has_checkpoint(self, video: TrackedVideo, checkpoint: str) -> bool:
        """Check if a video has a specific checkpoint."""
        checkpoint_map = {
            "1h": video.checkpoint_1h,
            "6h": video.checkpoint_6h,
            "24h": video.checkpoint_24h,
            "3d": video.checkpoint_3d,
            "7d": video.checkpoint_7d,
            "14d": video.checkpoint_14d,
            "30d": video.checkpoint_30d,
        }
        return checkpoint_map.get(checkpoint, False)
    
    def _mark_checkpoint(self, video: TrackedVideo, checkpoint: str) -> None:
        """Mark a checkpoint as complete."""
        if checkpoint == "1h":
            video.checkpoint_1h = True
        elif checkpoint == "6h":
            video.checkpoint_6h = True
        elif checkpoint == "24h":
            video.checkpoint_24h = True
        elif checkpoint == "3d":
            video.checkpoint_3d = True
        elif checkpoint == "7d":
            video.checkpoint_7d = True
        elif checkpoint == "14d":
            video.checkpoint_14d = True
        elif checkpoint == "30d":
            video.checkpoint_30d = True
    
    def get_tracking_stats(self) -> dict:
        """Get current tracking statistics."""
        total_tracked = self.session.query(func.count(TrackedVideo.id)).scalar()
        complete = self.session.query(func.count(TrackedVideo.id)).filter(
            TrackedVideo.tracking_complete == True
        ).scalar()
        active = total_tracked - complete
        
        total_snapshots = self.session.query(func.count(VideoSnapshot.id)).scalar()
        
        # Snapshots by checkpoint
        by_checkpoint = dict(
            self.session.query(
                VideoSnapshot.checkpoint,
                func.count(VideoSnapshot.id)
            ).group_by(VideoSnapshot.checkpoint).all()
        )
        
        return {
            "total_tracked_videos": total_tracked,
            "active_tracking": active,
            "complete": complete,
            "total_snapshots": total_snapshots,
            "by_checkpoint": by_checkpoint,
        }

