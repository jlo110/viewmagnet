"""Video collector - collects videos for channels."""
import json
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

from sqlalchemy.orm import Session
import structlog

from src.youtube.client import YouTubeClient
from src.database.models import Channel, Video

logger = structlog.get_logger()


@dataclass
class VideoCollectionResult:
    """Result of video collection for a channel."""
    channel_id: str
    videos_found: int
    videos_added: int
    videos_skipped: int
    errors: int


class VideoCollector:
    """
    Collects videos for channels in the database.
    
    Week 2-3: Video Metadata Collection
    - Last 30 videos per channel
    - Calculate performance metrics
    """
    
    VIDEOS_PER_CHANNEL = 30
    
    def __init__(
        self,
        session: Session,
        youtube_client: Optional[YouTubeClient] = None,
    ):
        """
        Initialize video collector.
        
        Args:
            session: SQLAlchemy session
            youtube_client: YouTube API client
        """
        self.session = session
        self.client = youtube_client or YouTubeClient()
    
    def collect_for_channel(
        self,
        channel: Channel,
        max_videos: int = 30,
    ) -> VideoCollectionResult:
        """
        Collect videos for a single channel.
        
        Args:
            channel: Channel model instance
            max_videos: Maximum videos to collect
            
        Returns:
            VideoCollectionResult with statistics
        """
        result = VideoCollectionResult(
            channel_id=channel.channel_id,
            videos_found=0,
            videos_added=0,
            videos_skipped=0,
            errors=0
        )
        
        # Get uploads playlist ID
        uploads_playlist_id = f"UU{channel.channel_id[2:]}"  # Convert UCxxx to UUxxx
        
        try:
            # Step 1: Get video IDs from uploads playlist
            playlist_response = self.client.get_channel_videos(
                uploads_playlist_id,
                max_results=max_videos
            )
            
            video_ids = []
            for item in playlist_response.get("items", []):
                video_id = item.get("contentDetails", {}).get("videoId")
                if video_id:
                    video_ids.append(video_id)
            
            if not video_ids:
                logger.debug("no_videos_found", channel_id=channel.channel_id)
                return result
            
            result.videos_found = len(video_ids)
            
            # Step 2: Get full video details in batches of 50
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i:i+50]
                
                try:
                    videos = self.client.get_video_details(batch)
                    
                    for video_info in videos:
                        try:
                            # Check if video already exists
                            existing = self.session.query(Video).filter(
                                Video.video_id == video_info.video_id
                            ).first()
                            
                            if existing:
                                result.videos_skipped += 1
                                continue
                            
                            # Calculate performance metrics
                            performance_ratio = self._calculate_performance_ratio(
                                video_info.view_count,
                                channel.avg_views_per_video
                            )
                            engagement_rate = self._calculate_engagement_rate(
                                video_info.view_count,
                                video_info.like_count,
                                video_info.comment_count
                            )
                            age_adjusted = self._calculate_age_adjusted_performance(
                                video_info.view_count,
                                video_info.published_at,
                                channel.avg_views_per_video
                            )
                            
                            # Create video record
                            video = Video(
                                video_id=video_info.video_id,
                                channel_id=video_info.channel_id,
                                title=video_info.title,
                                description=video_info.description,
                                thumbnail_url=video_info.thumbnail_url,
                                tags=json.dumps(video_info.tags) if video_info.tags else None,
                                duration_seconds=video_info.duration_seconds,
                                published_at=video_info.published_at,
                                youtube_category_id=video_info.youtube_category_id,
                                view_count=video_info.view_count,
                                like_count=video_info.like_count,
                                comment_count=video_info.comment_count,
                                performance_ratio=performance_ratio,
                                engagement_rate=engagement_rate,
                                age_adjusted_performance=age_adjusted,
                            )
                            
                            self.session.add(video)
                            result.videos_added += 1
                            
                        except Exception as e:
                            logger.error(
                                "video_save_error",
                                video_id=video_info.video_id,
                                error=str(e)
                            )
                            result.errors += 1
                            
                except Exception as e:
                    logger.error(
                        "video_batch_error",
                        channel_id=channel.channel_id,
                        error=str(e)
                    )
                    result.errors += len(batch)
            
            # Commit and mark channel as processed
            self.session.commit()
            
            channel.videos_collected = True
            self.session.commit()
            
            logger.info(
                "channel_videos_collected",
                channel_id=channel.channel_id,
                channel_name=channel.channel_name,
                found=result.videos_found,
                added=result.videos_added,
                skipped=result.videos_skipped
            )
            
        except Exception as e:
            logger.error(
                "channel_collection_error",
                channel_id=channel.channel_id,
                error=str(e)
            )
            result.errors += 1
            self.session.rollback()
        
        return result
    
    def collect_all(
        self,
        max_channels: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[VideoCollectionResult]:
        """
        Collect videos for all channels that haven't been processed.
        
        Args:
            max_channels: Maximum channels to process (None for all)
            category: Only process channels in this category
            
        Returns:
            List of VideoCollectionResult
        """
        # Query channels that need video collection
        query = self.session.query(Channel).filter(
            Channel.videos_collected == False,
            Channel.is_active == True
        )
        
        if category:
            query = query.filter(Channel.primary_category == category)
        
        if max_channels:
            query = query.limit(max_channels)
        
        channels = query.all()
        
        logger.info(
            "starting_video_collection",
            channels_to_process=len(channels),
            category=category
        )
        
        results = []
        total_videos = 0
        
        for i, channel in enumerate(channels):
            # Check quota before processing
            quota = self.client.get_quota_status()
            if quota["total_remaining"] < 10:
                logger.warning("low_quota_stopping", remaining=quota["total_remaining"])
                break
            
            result = self.collect_for_channel(channel)
            results.append(result)
            total_videos += result.videos_added
            
            # Log progress every 10 channels
            if (i + 1) % 10 == 0:
                logger.info(
                    "collection_progress",
                    processed=i + 1,
                    total=len(channels),
                    videos_collected=total_videos
                )
        
        logger.info(
            "video_collection_complete",
            channels_processed=len(results),
            total_videos=total_videos
        )
        
        return results
    
    def _calculate_performance_ratio(
        self,
        view_count: int,
        channel_avg: Optional[float]
    ) -> Optional[float]:
        """Calculate views / channel average."""
        if not channel_avg or channel_avg == 0:
            return None
        return view_count / channel_avg
    
    def _calculate_engagement_rate(
        self,
        view_count: int,
        like_count: int,
        comment_count: int
    ) -> Optional[float]:
        """Calculate (likes + comments) / views."""
        if view_count == 0:
            return None
        return (like_count + comment_count) / view_count
    
    def _calculate_age_adjusted_performance(
        self,
        view_count: int,
        published_at: datetime,
        channel_avg: Optional[float]
    ) -> Optional[float]:
        """
        Calculate age-adjusted performance.
        
        Newer videos get more credit for their views.
        Formula: (views / age_days) / (channel_avg / 30)
        
        This normalizes for how many views per day vs expected.
        """
        if not channel_avg or channel_avg == 0:
            return None
        
        age_days = max(1, (datetime.utcnow() - published_at).days)
        views_per_day = view_count / age_days
        expected_per_day = channel_avg / 30  # Assume 30-day average
        
        if expected_per_day == 0:
            return None
        
        return views_per_day / expected_per_day
    
    def get_collection_stats(self) -> dict:
        """Get current video collection statistics."""
        from sqlalchemy import func
        
        total_channels = self.session.query(func.count(Channel.id)).scalar()
        processed_channels = self.session.query(func.count(Channel.id)).filter(
            Channel.videos_collected == True
        ).scalar()
        total_videos = self.session.query(func.count(Video.id)).scalar()
        
        return {
            "total_channels": total_channels,
            "processed_channels": processed_channels,
            "pending_channels": total_channels - processed_channels,
            "total_videos": total_videos,
            "progress_pct": round((processed_channels / total_channels * 100), 1) if total_channels else 0
        }

