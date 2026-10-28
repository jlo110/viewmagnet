"""Metadata feature extraction."""
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict
import structlog

logger = structlog.get_logger()


@dataclass
class MetadataFeatures:
    """Extracted features from video metadata."""
    duration_seconds: int
    duration_category_ratio: float  # Relative to category average
    posting_day_of_week: int  # 0=Monday, 6=Sunday
    posting_hour: int  # 0-23
    tags_count: int


# Average video durations by category (in seconds)
# Based on typical YouTube content
CATEGORY_AVG_DURATIONS = {
    "gaming": 1200,  # 20 minutes
    "commentary_essay": 900,  # 15 minutes
    "entertainment_vlogs": 720,  # 12 minutes
    "education_howto": 600,  # 10 minutes
    "tech_reviews": 780,  # 13 minutes
    "music_creative": 240,  # 4 minutes
    "lifestyle": 600,  # 10 minutes
    "news_politics": 480,  # 8 minutes
    "other": 600,  # 10 minutes default
}


class MetadataAnalyzer:
    """Extracts features from video metadata."""
    
    def __init__(self, category_averages: Optional[Dict[str, float]] = None):
        """
        Initialize analyzer.
        
        Args:
            category_averages: Optional custom category duration averages
        """
        self.category_averages = category_averages or CATEGORY_AVG_DURATIONS
    
    def analyze(
        self,
        duration_seconds: int,
        published_at: datetime,
        tags: Optional[str],  # JSON string or None
        category: str = "other",
    ) -> MetadataFeatures:
        """
        Extract features from video metadata.
        
        Args:
            duration_seconds: Video duration in seconds
            published_at: When the video was published
            tags: JSON string of tags list
            category: Video category for duration comparison
            
        Returns:
            MetadataFeatures with extracted features
        """
        # Duration relative to category average
        avg_duration = self.category_averages.get(category, 600)
        duration_ratio = duration_seconds / avg_duration if avg_duration > 0 else 1.0
        
        # Posting time features
        day_of_week = published_at.weekday()  # 0=Monday, 6=Sunday
        hour = published_at.hour
        
        # Tags count
        tags_count = 0
        if tags:
            try:
                tags_list = json.loads(tags)
                tags_count = len(tags_list) if isinstance(tags_list, list) else 0
            except (json.JSONDecodeError, TypeError):
                tags_count = 0
        
        return MetadataFeatures(
            duration_seconds=duration_seconds,
            duration_category_ratio=duration_ratio,
            posting_day_of_week=day_of_week,
            posting_hour=hour,
            tags_count=tags_count,
        )
    
    def update_category_average(self, category: str, average: float) -> None:
        """
        Update the average duration for a category.
        
        Can be used to dynamically calculate from collected data.
        """
        self.category_averages[category] = average
    
    @staticmethod
    def calculate_category_averages_from_db(session) -> Dict[str, float]:
        """
        Calculate average durations from collected videos.
        
        Args:
            session: SQLAlchemy session
            
        Returns:
            Dict mapping category to average duration
        """
        from sqlalchemy import func
        from src.database.models import Video, Channel
        
        results = session.query(
            Channel.primary_category,
            func.avg(Video.duration_seconds)
        ).join(
            Channel, Video.channel_id == Channel.channel_id
        ).group_by(
            Channel.primary_category
        ).all()
        
        averages = {}
        for category, avg in results:
            if avg:
                averages[category] = float(avg)
        
        return averages

