"""Storage pipeline for saving discovered channels."""
from datetime import datetime
from typing import List, Optional
import structlog

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from src.database.models import Channel, ChannelSnapshot
from src.youtube.client import ChannelInfo
from src.discovery.tracker import DistributionTracker

logger = structlog.get_logger()


class ChannelStorage:
    """
    Handles persisting discovered channels to the database.
    
    Features:
    - Upsert logic (update if exists, insert if new)
    - Automatic size tier classification
    - Snapshot creation for tracking
    - Batch operations for efficiency
    """
    
    def __init__(self, session: Session, tracker: Optional[DistributionTracker] = None):
        """
        Initialize storage.
        
        Args:
            session: SQLAlchemy session
            tracker: Distribution tracker for size classification
        """
        self.session = session
        self.tracker = tracker or DistributionTracker()
    
    def save_channel(
        self,
        channel: ChannelInfo,
        category: str,
        discovery_source: str = "search",
        discovery_query: Optional[str] = None,
    ) -> Channel:
        """
        Save a single channel to the database.
        
        Args:
            channel: Channel info from YouTube API
            category: Assigned category
            discovery_source: How the channel was discovered
            discovery_query: The query used to find it
            
        Returns:
            The saved Channel model
        """
        size_tier = self.tracker.get_size_tier(channel.subscriber_count)
        
        # Calculate derived metrics
        avg_views = 0.0
        if channel.video_count > 0:
            avg_views = channel.total_views / channel.video_count
        
        db_channel = Channel(
            channel_id=channel.channel_id,
            channel_name=channel.channel_name,
            custom_url=channel.custom_url,
            subscriber_count=channel.subscriber_count,
            total_views=channel.total_views,
            video_count=channel.video_count,
            primary_category=category,
            size_tier=size_tier,
            avg_views_per_video=avg_views,
            description=channel.description[:2000] if channel.description else None,
            country=channel.country,
            default_language=channel.default_language,
            created_at_yt=channel.created_at,
            thumbnail_url=channel.thumbnail_url,
            discovery_source=discovery_source,
            discovery_query=discovery_query,
        )
        
        self.session.add(db_channel)
        self.session.flush()  # Flush to get any constraint errors early
        
        logger.debug(
            "channel_saved",
            channel_id=channel.channel_id,
            name=channel.channel_name,
            category=category,
            size_tier=size_tier,
        )
        
        return db_channel
    
    def commit(self) -> None:
        """Commit pending changes to database."""
        self.session.commit()
    
    def save_channels_batch(
        self,
        channels: List[tuple[ChannelInfo, str]],
        discovery_source: str = "search",
        discovery_query: Optional[str] = None,
    ) -> int:
        """
        Save multiple channels in a batch.
        
        Args:
            channels: List of (ChannelInfo, category) tuples
            discovery_source: How channels were discovered
            discovery_query: The query used
            
        Returns:
            Number of channels saved
        """
        saved = 0
        
        for channel_info, category in channels:
            try:
                self.save_channel(
                    channel_info,
                    category,
                    discovery_source,
                    discovery_query
                )
                saved += 1
            except Exception as e:
                logger.error(
                    "channel_save_error",
                    channel_id=channel_info.channel_id,
                    error=str(e)
                )
        
        try:
            self.session.commit()
            logger.info("batch_save_complete", count=saved)
        except Exception as e:
            self.session.rollback()
            logger.error("batch_commit_error", error=str(e))
            raise
        
        return saved
    
    def upsert_channel(
        self,
        channel: ChannelInfo,
        category: str,
        discovery_source: str = "search",
    ) -> None:
        """
        Insert or update a channel (PostgreSQL upsert).
        
        Args:
            channel: Channel info from YouTube API
            category: Assigned category
            discovery_source: How the channel was discovered
        """
        size_tier = self.tracker.get_size_tier(channel.subscriber_count)
        
        avg_views = 0.0
        if channel.video_count > 0:
            avg_views = channel.total_views / channel.video_count
        
        values = {
            "channel_id": channel.channel_id,
            "channel_name": channel.channel_name,
            "custom_url": channel.custom_url,
            "subscriber_count": channel.subscriber_count,
            "total_views": channel.total_views,
            "video_count": channel.video_count,
            "primary_category": category,
            "size_tier": size_tier,
            "avg_views_per_video": avg_views,
            "description": channel.description[:2000] if channel.description else None,
            "country": channel.country,
            "default_language": channel.default_language,
            "created_at_yt": channel.created_at,
            "thumbnail_url": channel.thumbnail_url,
            "discovery_source": discovery_source,
            "last_updated": datetime.utcnow(),
        }
        
        stmt = insert(Channel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["channel_id"],
            set_={
                "channel_name": stmt.excluded.channel_name,
                "subscriber_count": stmt.excluded.subscriber_count,
                "total_views": stmt.excluded.total_views,
                "video_count": stmt.excluded.video_count,
                "avg_views_per_video": stmt.excluded.avg_views_per_video,
                "size_tier": stmt.excluded.size_tier,
                "last_updated": stmt.excluded.last_updated,
            }
        )
        
        self.session.execute(stmt)
    
    def create_snapshot(self, channel: Channel) -> ChannelSnapshot:
        """
        Create a snapshot of channel statistics.
        
        Used for tracking channel growth over time.
        
        Args:
            channel: Channel model
            
        Returns:
            The created snapshot
        """
        snapshot = ChannelSnapshot(
            channel_id=channel.channel_id,
            subscriber_count=channel.subscriber_count,
            total_views=channel.total_views,
            video_count=channel.video_count,
        )
        
        self.session.add(snapshot)
        return snapshot
    
    def get_channel_by_id(self, channel_id: str) -> Optional[Channel]:
        """Get a channel by its YouTube ID."""
        return self.session.query(Channel).filter(
            Channel.channel_id == channel_id
        ).first()
    
    def get_channels_by_category(
        self,
        category: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Channel]:
        """Get channels in a category."""
        return self.session.query(Channel).filter(
            Channel.primary_category == category,
            Channel.is_active == True,
        ).order_by(
            Channel.subscriber_count.desc()
        ).offset(offset).limit(limit).all()
    
    def get_channels_needing_videos(self, limit: int = 100) -> List[Channel]:
        """Get channels that haven't had their videos collected yet."""
        return self.session.query(Channel).filter(
            Channel.videos_collected == False,
            Channel.is_active == True,
        ).limit(limit).all()
    
    def mark_videos_collected(self, channel_id: str) -> None:
        """Mark a channel as having its videos collected."""
        self.session.query(Channel).filter(
            Channel.channel_id == channel_id
        ).update({"videos_collected": True})
    
    def get_statistics(self) -> dict:
        """Get collection statistics."""
        from sqlalchemy import func
        
        total = self.session.query(func.count(Channel.id)).scalar()
        
        by_category = dict(
            self.session.query(
                Channel.primary_category,
                func.count(Channel.id)
            ).group_by(Channel.primary_category).all()
        )
        
        by_size = dict(
            self.session.query(
                Channel.size_tier,
                func.count(Channel.id)
            ).group_by(Channel.size_tier).all()
        )
        
        return {
            "total_channels": total,
            "by_category": by_category,
            "by_size": by_size,
        }

