"""
Creator context features - channel momentum, consistency, and historical performance.

Provides context about the creator's recent trajectory for better predictions.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
import numpy as np
from sqlalchemy import desc
from sqlalchemy.orm import Session
import structlog

from src.database.models import Channel, Video, ChannelSnapshot

logger = structlog.get_logger()


@dataclass
class CreatorContext:
    """Comprehensive creator context for predictions."""
    # Channel basics
    channel_id: str
    channel_name: str
    subscriber_count: int
    size_tier: str
    category: str
    
    # Historical baseline
    avg_views_per_video: float  # All-time average
    median_views_per_video: float
    avg_engagement_rate: float
    total_videos: int
    
    # Recent performance (last 10 videos)
    recent_avg_views: float
    recent_median_views: float
    recent_engagement_rate: float
    
    # Momentum metrics
    momentum_score: float  # -1 to 1: declining to growing
    views_trend_slope: float  # Positive = views increasing
    engagement_trend_slope: float
    
    # Consistency metrics
    upload_consistency_score: float  # 0-1: how regular are uploads
    avg_days_between_uploads: float
    upload_variance: float  # Higher = less consistent
    
    # Growth trajectory
    subscriber_growth_30d: Optional[float]  # % change in last 30 days
    views_growth_30d: Optional[float]
    
    # Performance variability
    views_coefficient_of_variation: float  # Higher = more variable performance
    hit_rate: float  # % of videos that exceed 2x average
    
    # Engagement rate trends (NEW)
    engagement_trend_direction: str  # "rising", "falling", "stable"
    engagement_trend_7d: float  # % change in last 7 days vs prior 7
    engagement_trend_30d: float  # % change in last 30 days vs prior 30
    engagement_recent_vs_baseline: float  # ratio of recent to all-time
    like_ratio_trend: str  # "rising", "falling", "stable"
    comment_ratio_trend: str  # "rising", "falling", "stable"


class CreatorContextCalculator:
    """Calculate creator context features from database."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_context(self, channel_id: str) -> Optional[CreatorContext]:
        """
        Get comprehensive creator context for a channel.
        
        Args:
            channel_id: YouTube channel ID
            
        Returns:
            CreatorContext or None if channel not found
        """
        # Get channel
        channel = self.session.query(Channel).filter_by(channel_id=channel_id).first()
        if not channel:
            logger.warning(f"Channel not found: {channel_id}")
            return None
        
        # Get all videos
        videos = (
            self.session.query(Video)
            .filter_by(channel_id=channel_id)
            .order_by(desc(Video.published_at))
            .all()
        )
        
        if not videos:
            logger.warning(f"No videos found for channel: {channel_id}")
            return None
        
        # Calculate baseline metrics
        all_views = [v.view_count for v in videos if v.view_count]
        all_engagements = [
            (v.like_count + v.comment_count) / max(v.view_count, 1)
            for v in videos if v.view_count
        ]
        
        avg_views = np.mean(all_views) if all_views else 0
        median_views = np.median(all_views) if all_views else 0
        avg_engagement = np.mean(all_engagements) if all_engagements else 0
        
        # Recent 10 videos
        recent_videos = videos[:10]
        recent_views = [v.view_count for v in recent_videos if v.view_count]
        recent_engagements = [
            (v.like_count + v.comment_count) / max(v.view_count, 1)
            for v in recent_videos if v.view_count
        ]
        
        recent_avg_views = np.mean(recent_views) if recent_views else 0
        recent_median_views = np.median(recent_views) if recent_views else 0
        recent_engagement = np.mean(recent_engagements) if recent_engagements else 0
        
        # Momentum calculation
        momentum_score, views_slope, engagement_slope = self._calculate_momentum(videos[:20])
        
        # Upload consistency
        consistency_score, avg_days, variance = self._calculate_consistency(videos)
        
        # Growth trajectory (from snapshots if available)
        sub_growth, views_growth = self._calculate_growth(channel_id)
        
        # Performance variability
        cv = np.std(all_views) / avg_views if avg_views > 0 else 0
        hit_rate = sum(1 for v in all_views if v > 2 * avg_views) / len(all_views) if all_views else 0
        
        return CreatorContext(
            channel_id=channel_id,
            channel_name=channel.channel_name,
            subscriber_count=channel.subscriber_count,
            size_tier=channel.size_tier,
            category=channel.primary_category,
            avg_views_per_video=float(avg_views),
            median_views_per_video=float(median_views),
            avg_engagement_rate=float(avg_engagement),
            total_videos=len(videos),
            recent_avg_views=float(recent_avg_views),
            recent_median_views=float(recent_median_views),
            recent_engagement_rate=float(recent_engagement),
            momentum_score=momentum_score,
            views_trend_slope=views_slope,
            engagement_trend_slope=engagement_slope,
            upload_consistency_score=consistency_score,
            avg_days_between_uploads=avg_days,
            upload_variance=variance,
            subscriber_growth_30d=sub_growth,
            views_growth_30d=views_growth,
            views_coefficient_of_variation=float(cv),
            hit_rate=float(hit_rate),
            **self._calculate_engagement_trends(videos)
        )
    
    def _calculate_momentum(self, videos: List[Video], window: int = 10) -> Tuple[float, float, float]:
        """
        Calculate momentum score based on recent vs older performance.
        
        Returns:
            (momentum_score, views_slope, engagement_slope)
        """
        if len(videos) < 4:
            return 0.0, 0.0, 0.0
        
        # Split into recent half and older half
        mid = len(videos) // 2
        recent = videos[:mid]
        older = videos[mid:]
        
        # Compare views
        recent_views = np.mean([v.view_count for v in recent if v.view_count])
        older_views = np.mean([v.view_count for v in older if v.view_count])
        
        if older_views > 0:
            views_change = (recent_views - older_views) / older_views
        else:
            views_change = 0
        
        # Compare engagement
        recent_engagement = np.mean([
            (v.like_count + v.comment_count) / max(v.view_count, 1)
            for v in recent if v.view_count
        ])
        older_engagement = np.mean([
            (v.like_count + v.comment_count) / max(v.view_count, 1)
            for v in older if v.view_count
        ])
        
        if older_engagement > 0:
            engagement_change = (recent_engagement - older_engagement) / older_engagement
        else:
            engagement_change = 0
        
        # Calculate linear trend (slope)
        x = np.arange(len(videos))
        views = np.array([v.view_count for v in reversed(videos)])  # Oldest first
        
        if len(views) > 2:
            views_slope = np.polyfit(x, views, 1)[0]
            # Normalize slope relative to mean
            views_slope_normalized = views_slope / max(np.mean(views), 1)
        else:
            views_slope_normalized = 0
        
        # Overall momentum score: combine views change and engagement change
        # Clip to -1 to 1 range
        momentum = np.clip((views_change * 0.7 + engagement_change * 0.3), -1, 1)
        
        return float(momentum), float(views_slope_normalized), float(engagement_change)
    
    def _calculate_consistency(self, videos: List[Video]) -> Tuple[float, float, float]:
        """
        Calculate upload consistency metrics.
        
        Returns:
            (consistency_score, avg_days_between, variance)
        """
        if len(videos) < 2:
            return 0.5, 0.0, 0.0
        
        # Calculate days between uploads
        intervals = []
        sorted_videos = sorted(videos, key=lambda v: v.published_at, reverse=True)
        
        for i in range(len(sorted_videos) - 1):
            diff = (sorted_videos[i].published_at - sorted_videos[i+1].published_at).days
            if diff > 0:  # Ignore same-day uploads
                intervals.append(diff)
        
        if not intervals:
            return 0.5, 0.0, 0.0
        
        avg_days = np.mean(intervals)
        variance = np.std(intervals)
        
        # Consistency score: lower variance = higher consistency
        # Also penalize very long gaps
        cv = variance / max(avg_days, 1)  # Coefficient of variation
        
        # Score: 1.0 = perfectly consistent, 0.0 = very inconsistent
        consistency = max(0, 1 - (cv / 2))  # CV of 2+ = score of 0
        
        # Penalize very infrequent uploaders (>30 days average)
        if avg_days > 30:
            consistency *= (30 / avg_days)
        
        return float(np.clip(consistency, 0, 1)), float(avg_days), float(variance)
    
    def _calculate_growth(self, channel_id: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate 30-day growth from snapshots.
        
        Returns:
            (subscriber_growth_pct, views_growth_pct) or (None, None)
        """
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        # Get oldest and newest snapshots in last 30 days
        snapshots = (
            self.session.query(ChannelSnapshot)
            .filter(
                ChannelSnapshot.channel_id == channel_id,
                ChannelSnapshot.snapshot_at >= thirty_days_ago
            )
            .order_by(ChannelSnapshot.snapshot_at)
            .all()
        )
        
        if len(snapshots) < 2:
            return None, None
        
        oldest = snapshots[0]
        newest = snapshots[-1]
        
        # Calculate growth
        sub_growth = None
        if oldest.subscriber_count > 0:
            sub_growth = (newest.subscriber_count - oldest.subscriber_count) / oldest.subscriber_count
        
        views_growth = None
        if oldest.total_views > 0:
            views_growth = (newest.total_views - oldest.total_views) / oldest.total_views
        
        return sub_growth, views_growth
    
    def _calculate_engagement_trends(self, videos: List[Video]) -> dict:
        """
        Calculate engagement rate trends over time.
        
        Returns dict with trend metrics for CreatorContext.
        """
        now = datetime.utcnow()
        
        # Default values
        defaults = {
            "engagement_trend_direction": "stable",
            "engagement_trend_7d": 0.0,
            "engagement_trend_30d": 0.0,
            "engagement_recent_vs_baseline": 1.0,
            "like_ratio_trend": "stable",
            "comment_ratio_trend": "stable",
        }
        
        if len(videos) < 5:
            return defaults
        
        def calc_engagement(v):
            if not v.view_count or v.view_count == 0:
                return 0
            return (v.like_count or 0 + v.comment_count or 0) / v.view_count
        
        def calc_like_ratio(v):
            if not v.view_count or v.view_count == 0:
                return 0
            return (v.like_count or 0) / v.view_count
        
        def calc_comment_ratio(v):
            if not v.view_count or v.view_count == 0:
                return 0
            return (v.comment_count or 0) / v.view_count
        
        # Filter videos by time periods
        videos_7d = [v for v in videos if v.published_at and (now - v.published_at).days <= 7]
        videos_prior_7d = [v for v in videos if v.published_at and 7 < (now - v.published_at).days <= 14]
        videos_30d = [v for v in videos if v.published_at and (now - v.published_at).days <= 30]
        videos_prior_30d = [v for v in videos if v.published_at and 30 < (now - v.published_at).days <= 60]
        
        # All-time baseline
        all_engagement = [calc_engagement(v) for v in videos if calc_engagement(v) > 0]
        baseline_engagement = np.mean(all_engagement) if all_engagement else 0
        
        # Recent engagement (last 10 videos)
        recent_engagement = [calc_engagement(v) for v in videos[:10] if calc_engagement(v) > 0]
        recent_avg = np.mean(recent_engagement) if recent_engagement else 0
        
        # 7-day trend
        eng_7d = np.mean([calc_engagement(v) for v in videos_7d]) if videos_7d else 0
        eng_prior_7d = np.mean([calc_engagement(v) for v in videos_prior_7d]) if videos_prior_7d else 0
        
        if eng_prior_7d > 0:
            trend_7d = (eng_7d - eng_prior_7d) / eng_prior_7d
        else:
            trend_7d = 0
        
        # 30-day trend
        eng_30d = np.mean([calc_engagement(v) for v in videos_30d]) if videos_30d else 0
        eng_prior_30d = np.mean([calc_engagement(v) for v in videos_prior_30d]) if videos_prior_30d else 0
        
        if eng_prior_30d > 0:
            trend_30d = (eng_30d - eng_prior_30d) / eng_prior_30d
        else:
            trend_30d = 0
        
        # Recent vs baseline ratio
        recent_vs_baseline = recent_avg / baseline_engagement if baseline_engagement > 0 else 1.0
        
        # Determine overall trend direction
        if trend_30d > 0.1:
            direction = "rising"
        elif trend_30d < -0.1:
            direction = "falling"
        else:
            direction = "stable"
        
        # Like ratio trend
        like_ratios = [(v, calc_like_ratio(v)) for v in videos[:20] if calc_like_ratio(v) > 0]
        if len(like_ratios) >= 10:
            recent_likes = np.mean([lr[1] for lr in like_ratios[:5]])
            older_likes = np.mean([lr[1] for lr in like_ratios[10:15]])
            if older_likes > 0:
                like_change = (recent_likes - older_likes) / older_likes
                like_ratio_trend = "rising" if like_change > 0.1 else ("falling" if like_change < -0.1 else "stable")
            else:
                like_ratio_trend = "stable"
        else:
            like_ratio_trend = "stable"
        
        # Comment ratio trend
        comment_ratios = [(v, calc_comment_ratio(v)) for v in videos[:20] if calc_comment_ratio(v) > 0]
        if len(comment_ratios) >= 10:
            recent_comments = np.mean([cr[1] for cr in comment_ratios[:5]])
            older_comments = np.mean([cr[1] for cr in comment_ratios[10:15]])
            if older_comments > 0:
                comment_change = (recent_comments - older_comments) / older_comments
                comment_ratio_trend = "rising" if comment_change > 0.1 else ("falling" if comment_change < -0.1 else "stable")
            else:
                comment_ratio_trend = "stable"
        else:
            comment_ratio_trend = "stable"
        
        return {
            "engagement_trend_direction": direction,
            "engagement_trend_7d": float(trend_7d),
            "engagement_trend_30d": float(trend_30d),
            "engagement_recent_vs_baseline": float(recent_vs_baseline),
            "like_ratio_trend": like_ratio_trend,
            "comment_ratio_trend": comment_ratio_trend,
        }
    
    def get_performance_percentile(self, channel_id: str, view_count: int) -> float:
        """
        Get what percentile a view count would be for this channel.
        
        Args:
            channel_id: Channel ID
            view_count: View count to evaluate
            
        Returns:
            Percentile (0-100)
        """
        videos = self.session.query(Video.view_count).filter_by(channel_id=channel_id).all()
        
        if not videos:
            return 50.0
        
        views = [v[0] for v in videos if v[0]]
        percentile = sum(1 for v in views if v < view_count) / len(views) * 100
        
        return float(percentile)
    
    def is_channel_hot(self, channel_id: str, threshold: float = 0.3) -> bool:
        """
        Check if a channel is currently "hot" (growing rapidly).
        
        Args:
            channel_id: Channel ID
            threshold: Momentum threshold for "hot" status
            
        Returns:
            True if channel momentum exceeds threshold
        """
        context = self.get_context(channel_id)
        if not context:
            return False
        
        return context.momentum_score > threshold


def get_creator_context(session: Session, channel_id: str) -> Optional[CreatorContext]:
    """Convenience function to get creator context."""
    calculator = CreatorContextCalculator(session)
    return calculator.get_context(channel_id)

