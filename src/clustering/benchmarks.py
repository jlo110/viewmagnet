"""
Niche Benchmarks - Calculate performance benchmarks per niche.

For each micro-niche, calculates:
- Average thumbnail characteristics
- Average title patterns
- Average video duration
- Performance benchmarks by creator size tier
"""
from typing import Dict, List, Optional
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session
import structlog

from src.database.models import Channel, Video, VideoFeatures, Niche

logger = structlog.get_logger()


@dataclass
class NicheBenchmark:
    """Benchmark metrics for a niche."""
    niche_id: int
    niche_name: str
    channel_count: int
    
    # Video metrics
    avg_views: float
    median_views: float
    avg_duration_seconds: float
    avg_engagement_rate: float
    
    # Thumbnail metrics
    face_rate: float  # % of thumbnails with faces
    avg_face_count: float
    avg_brightness: float
    avg_saturation: float
    avg_composition_score: float
    
    # Title metrics  
    avg_title_length: float
    avg_word_count: float
    top_hook_types: List[str]
    
    # By size tier
    benchmarks_by_size: Dict[str, Dict]


class NicheBenchmarks:
    """Calculate and store benchmarks for each niche."""
    
    def __init__(self, session: Session):
        """Initialize benchmarks calculator."""
        self.session = session
    
    def calculate_for_niche(self, niche_id: int) -> Optional[NicheBenchmark]:
        """
        Calculate all benchmarks for a single niche.
        
        Args:
            niche_id: Database ID of the niche
            
        Returns:
            NicheBenchmark with all calculated metrics
        """
        niche = self.session.query(Niche).filter(Niche.id == niche_id).first()
        if not niche:
            return None
        
        # Get all channels in this niche
        channels = self.session.query(Channel).filter(
            Channel.niche_id == niche_id,
            Channel.is_active == True
        ).all()
        
        if not channels:
            return None
        
        channel_ids = [c.channel_id for c in channels]
        
        # Get all videos for these channels
        videos = self.session.query(Video).filter(
            Video.channel_id.in_(channel_ids)
        ).all()
        
        if not videos:
            return None
        
        video_ids = [v.video_id for v in videos]
        
        # Get features for these videos
        features = self.session.query(VideoFeatures).filter(
            VideoFeatures.video_id.in_(video_ids)
        ).all()
        
        # Calculate video metrics - convert numpy to native Python types
        view_counts = [v.view_count or 0 for v in videos]
        avg_views = float(np.mean(view_counts)) if view_counts else 0.0
        median_views = float(np.median(view_counts)) if view_counts else 0.0
        
        durations = [v.duration_seconds or 0 for v in videos if v.duration_seconds]
        avg_duration = float(np.mean(durations)) if durations else 0.0
        
        # Calculate engagement rates
        engagement_rates = []
        for v in videos:
            if v.view_count and v.view_count > 0:
                likes = v.like_count or 0
                comments = v.comment_count or 0
                rate = (likes + comments) / v.view_count
                engagement_rates.append(rate)
        avg_engagement = float(np.mean(engagement_rates)) if engagement_rates else 0.0
        
        # Calculate thumbnail metrics
        face_count = sum(1 for f in features if f.has_face)
        face_rate = face_count / len(features) if features else 0
        
        avg_face_count = float(np.mean([f.face_count or 0 for f in features])) if features else 0.0
        avg_brightness = float(np.mean([f.brightness or 0 for f in features if f.brightness])) if features else 0.0
        avg_saturation = float(np.mean([f.saturation or 0 for f in features if f.saturation])) if features else 0.0
        avg_composition = float(np.mean([f.composition_score or 0 for f in features if f.composition_score])) if features else 0.0
        
        # Calculate title metrics
        avg_title_length = float(np.mean([f.title_char_length or 0 for f in features if f.title_char_length])) if features else 0.0
        avg_word_count = float(np.mean([f.title_word_count or 0 for f in features if f.title_word_count])) if features else 0.0
        
        # Get top hook types
        hook_types = [f.title_hook_type for f in features if f.title_hook_type]
        hook_counter = Counter(hook_types)
        top_hooks = [h for h, _ in hook_counter.most_common(5)]
        
        # Calculate benchmarks by size tier
        benchmarks_by_size = {}
        for size_tier in ["nano", "micro", "small", "medium", "large", "mega"]:
            tier_channels = [c for c in channels if c.size_tier == size_tier]
            if not tier_channels:
                continue
            
            tier_channel_ids = [c.channel_id for c in tier_channels]
            tier_videos = [v for v in videos if v.channel_id in tier_channel_ids]
            
            if tier_videos:
                tier_views = [v.view_count or 0 for v in tier_videos]
                benchmarks_by_size[size_tier] = {
                    "channel_count": len(tier_channels),
                    "video_count": len(tier_videos),
                    "avg_views": float(np.mean(tier_views)),
                    "median_views": float(np.median(tier_views)),
                    "p25_views": float(np.percentile(tier_views, 25)),
                    "p75_views": float(np.percentile(tier_views, 75)),
                }
        
        return NicheBenchmark(
            niche_id=niche_id,
            niche_name=niche.name,
            channel_count=len(channels),
            avg_views=avg_views,
            median_views=median_views,
            avg_duration_seconds=avg_duration,
            avg_engagement_rate=avg_engagement,
            face_rate=face_rate,
            avg_face_count=avg_face_count,
            avg_brightness=avg_brightness,
            avg_saturation=avg_saturation,
            avg_composition_score=avg_composition,
            avg_title_length=avg_title_length,
            avg_word_count=avg_word_count,
            top_hook_types=top_hooks,
            benchmarks_by_size=benchmarks_by_size,
        )
    
    def calculate_all_benchmarks(self) -> List[NicheBenchmark]:
        """Calculate benchmarks for all niches and save to database."""
        niches = self.session.query(Niche).all()
        
        benchmarks = []
        
        for niche in niches:
            logger.info(f"Calculating benchmarks for: {niche.name}")
            
            benchmark = self.calculate_for_niche(niche.id)
            
            if benchmark:
                # Update niche record with benchmarks
                niche.avg_views_per_video = benchmark.avg_views
                niche.avg_engagement_rate = benchmark.avg_engagement_rate
                niche.avg_video_duration = benchmark.avg_duration_seconds
                niche.avg_face_rate = benchmark.face_rate
                niche.avg_title_length = benchmark.avg_title_length
                niche.common_hook_types = ",".join(benchmark.top_hook_types)
                
                benchmarks.append(benchmark)
        
        self.session.commit()
        logger.info(f"Calculated benchmarks for {len(benchmarks)} niches")
        
        return benchmarks
    
    def get_benchmark_summary(self) -> List[Dict]:
        """Get summary of all niche benchmarks."""
        niches = self.session.query(Niche).order_by(
            Niche.category, Niche.channel_count.desc()
        ).all()
        
        return [
            {
                "id": n.id,
                "name": n.name,
                "category": n.category,
                "channels": n.channel_count,
                "avg_views": n.avg_views_per_video,
                "avg_engagement": n.avg_engagement_rate,
                "face_rate": n.avg_face_rate,
                "avg_title_length": n.avg_title_length,
                "hook_types": n.common_hook_types.split(",") if n.common_hook_types else [],
            }
            for n in niches
        ]

