"""Channel selector for temporal tracking."""
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session
import structlog

from src.database.models import Channel, Video, TrackedChannel
from src.config import CATEGORY_DISTRIBUTION, SIZE_DISTRIBUTION

logger = structlog.get_logger()


@dataclass
class ChannelActivity:
    """Activity metrics for a channel."""
    channel_id: str
    channel_name: str
    recent_video_count: int
    avg_days_between_uploads: Optional[float]
    last_upload: Optional[datetime]


class ChannelSelector:
    """
    Selects active channels for temporal tracking.
    
    Active = 2+ videos in last 30 days
    Target: 8,000-10,000 channels across categories
    """
    
    MIN_RECENT_VIDEOS = 2
    LOOKBACK_DAYS = 30
    
    def __init__(self, session: Session):
        """Initialize selector."""
        self.session = session
    
    def find_active_channels(
        self,
        min_videos: int = 2,
        lookback_days: int = 30,
        limit: Optional[int] = None,
    ) -> List[ChannelActivity]:
        """
        Find channels with recent activity.
        
        Args:
            min_videos: Minimum videos in lookback period
            lookback_days: Days to look back for activity
            limit: Maximum channels to return
            
        Returns:
            List of ChannelActivity with metrics
        """
        cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
        
        # Query channels with recent video counts
        query = self.session.query(
            Channel.channel_id,
            Channel.channel_name,
            func.count(Video.id).label('recent_count'),
            func.max(Video.published_at).label('last_upload')
        ).join(
            Video, Channel.channel_id == Video.channel_id
        ).filter(
            Video.published_at >= cutoff_date,
            Channel.is_active == True
        ).group_by(
            Channel.channel_id,
            Channel.channel_name
        ).having(
            func.count(Video.id) >= min_videos
        ).order_by(
            func.count(Video.id).desc()
        )
        
        if limit:
            query = query.limit(limit)
        
        results = query.all()
        
        activities = []
        for channel_id, channel_name, count, last_upload in results:
            # Calculate average days between uploads
            avg_days = None
            if count > 1:
                avg_days = lookback_days / count
            
            activities.append(ChannelActivity(
                channel_id=channel_id,
                channel_name=channel_name,
                recent_video_count=count,
                avg_days_between_uploads=avg_days,
                last_upload=last_upload,
            ))
        
        logger.info(
            "found_active_channels",
            count=len(activities),
            min_videos=min_videos,
            lookback_days=lookback_days
        )
        
        return activities
    
    def add_channels_to_tracking(
        self,
        activities: List[ChannelActivity],
    ) -> int:
        """
        Add active channels to tracking.
        
        Args:
            activities: List of ChannelActivity to add
            
        Returns:
            Number of channels added
        """
        added = 0
        
        for activity in activities:
            # Check if already tracked
            existing = self.session.query(TrackedChannel).filter(
                TrackedChannel.channel_id == activity.channel_id
            ).first()
            
            if existing:
                # Update existing record
                existing.recent_video_count = activity.recent_video_count
                existing.avg_upload_frequency_days = activity.avg_days_between_uploads
                existing.is_active = True
            else:
                # Create new tracking record
                tracked = TrackedChannel(
                    channel_id=activity.channel_id,
                    recent_video_count=activity.recent_video_count,
                    avg_upload_frequency_days=activity.avg_days_between_uploads,
                    is_active=True,
                )
                self.session.add(tracked)
                added += 1
        
        self.session.commit()
        
        logger.info("channels_added_to_tracking", added=added)
        return added
    
    def get_tracking_stats(self) -> dict:
        """Get current tracking statistics."""
        total_tracked = self.session.query(func.count(TrackedChannel.id)).scalar()
        active_tracked = self.session.query(func.count(TrackedChannel.id)).filter(
            TrackedChannel.is_active == True
        ).scalar()
        
        return {
            "total_tracked_channels": total_tracked,
            "active_tracked_channels": active_tracked,
        }
    
    def track_all_channels(self) -> int:
        """
        Add ALL channels to tracking, regardless of activity.
        
        This ensures we catch videos from any channel that starts uploading.
        
        Returns:
            Number of new channels added to tracking
        """
        # Get already tracked channel IDs
        tracked_ids = set(
            row[0] for row in 
            self.session.query(TrackedChannel.channel_id).all()
        )
        
        # Get all channels not yet tracked
        all_channels = self.session.query(
            Channel.channel_id,
            Channel.channel_name
        ).filter(
            Channel.is_active == True,
            ~Channel.channel_id.in_(tracked_ids) if tracked_ids else True
        ).all()
        
        added = 0
        for channel_id, channel_name in all_channels:
            if channel_id in tracked_ids:
                continue
            
            tracked = TrackedChannel(
                channel_id=channel_id,
                recent_video_count=0,  # Will be updated when videos found
                avg_upload_frequency_days=None,
                is_active=True,
            )
            self.session.add(tracked)
            tracked_ids.add(channel_id)
            added += 1
        
        self.session.commit()
        
        logger.info(
            "added_all_channels_to_tracking",
            added=added,
            total_tracked=len(tracked_ids)
        )
        
        return added
    
    def select_for_tracking(
        self,
        target_count: int = 10000,
        min_videos: int = 2,
        ensure_distribution: bool = True,
    ) -> int:
        """
        Select and add channels for tracking up to target count.
        
        Args:
            target_count: Target number of tracked channels
            min_videos: Minimum recent videos required
            ensure_distribution: Ensure proportional category/size distribution
            
        Returns:
            Number of new channels added
        """
        if ensure_distribution:
            return self._select_with_distribution(target_count, min_videos)
        
        stats = self.get_tracking_stats()
        current = stats["active_tracked_channels"]
        
        if current >= target_count:
            logger.info("target_already_met", current=current, target=target_count)
            return 0
        
        needed = target_count - current
        
        # Find active channels not yet tracked
        activities = self.find_active_channels(
            min_videos=min_videos,
            limit=needed * 2
        )
        
        # Filter out already tracked
        tracked_ids = set(
            row[0] for row in 
            self.session.query(TrackedChannel.channel_id).all()
        )
        
        new_activities = [
            a for a in activities 
            if a.channel_id not in tracked_ids
        ][:needed]
        
        added = self.add_channels_to_tracking(new_activities)
        
        return added
    
    def _select_with_distribution(
        self,
        target_count: int,
        min_videos: int,
    ) -> int:
        """Select channels ensuring proportional distribution across categories/sizes."""
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        
        # Get already tracked channel IDs
        tracked_ids = set(
            row[0] for row in 
            self.session.query(TrackedChannel.channel_id).all()
        )
        
        # Calculate current distribution
        current_dist = self._get_current_distribution()
        
        # Calculate targets per category (proportional to CATEGORY_DISTRIBUTION)
        total_target = sum(CATEGORY_DISTRIBUTION.values())
        category_targets = {}
        for cat, count in CATEGORY_DISTRIBUTION.items():
            category_targets[cat] = int(target_count * count / total_target)
        
        added_total = 0
        
        # For each category
        for category, cat_target in category_targets.items():
            current_cat = sum(current_dist.get(category, {}).values())
            needed_cat = cat_target - current_cat
            
            if needed_cat <= 0:
                continue
            
            # For each size tier within category
            for size_tier, size_info in SIZE_DISTRIBUTION.items():
                size_pct = size_info["percentage"]
                size_target = int(cat_target * size_pct)
                current_size = current_dist.get(category, {}).get(size_tier, 0)
                needed_size = size_target - current_size
                
                if needed_size <= 0:
                    continue
                
                # Find active channels for this category/size
                channels = self._find_active_for_slot(
                    category=category,
                    size_tier=size_tier,
                    min_videos=min_videos,
                    cutoff_date=cutoff_date,
                    exclude_ids=tracked_ids,
                    limit=needed_size
                )
                
                for channel_id, channel_name, count, last_upload in channels:
                    if channel_id in tracked_ids:
                        continue
                    
                    tracked = TrackedChannel(
                        channel_id=channel_id,
                        recent_video_count=count,
                        avg_upload_frequency_days=30 / count if count > 0 else None,
                        is_active=True,
                    )
                    self.session.add(tracked)
                    tracked_ids.add(channel_id)
                    added_total += 1
        
        self.session.commit()
        
        logger.info(
            "distributed_selection_complete",
            added=added_total,
            target=target_count
        )
        
        return added_total
    
    def _get_current_distribution(self) -> Dict[str, Dict[str, int]]:
        """Get current tracked channel distribution by category and size."""
        results = self.session.query(
            Channel.primary_category,
            Channel.size_tier,
            func.count(TrackedChannel.id)
        ).join(
            Channel, TrackedChannel.channel_id == Channel.channel_id
        ).filter(
            TrackedChannel.is_active == True
        ).group_by(
            Channel.primary_category,
            Channel.size_tier
        ).all()
        
        dist = {}
        for cat, size, count in results:
            if cat not in dist:
                dist[cat] = {}
            dist[cat][size] = count
        
        return dist
    
    def _find_active_for_slot(
        self,
        category: str,
        size_tier: str,
        min_videos: int,
        cutoff_date: datetime,
        exclude_ids: set,
        limit: int,
    ) -> List:
        """Find active channels for a specific category/size slot."""
        query = self.session.query(
            Channel.channel_id,
            Channel.channel_name,
            func.count(Video.id).label('recent_count'),
            func.max(Video.published_at).label('last_upload')
        ).join(
            Video, Channel.channel_id == Video.channel_id
        ).filter(
            Video.published_at >= cutoff_date,
            Channel.is_active == True,
            Channel.primary_category == category,
            Channel.size_tier == size_tier,
            ~Channel.channel_id.in_(exclude_ids) if exclude_ids else True
        ).group_by(
            Channel.channel_id,
            Channel.channel_name
        ).having(
            func.count(Video.id) >= min_videos
        ).order_by(
            func.count(Video.id).desc()
        ).limit(limit)
        
        return query.all()

