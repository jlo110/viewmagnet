"""
Best Time to Publish Analyzer

Analyzes video performance by publish time to recommend optimal posting times.
Uses category/niche-specific patterns and channel-specific history.
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from collections import defaultdict
import numpy as np
from sqlalchemy import func, extract
from sqlalchemy.orm import Session
import structlog

from src.database.models import Video, Channel

logger = structlog.get_logger()


@dataclass
class TimeSlotPerformance:
    """Performance metrics for a time slot."""
    day_of_week: int  # 0=Monday, 6=Sunday
    hour: int  # 0-23
    avg_views: float
    avg_engagement_rate: float
    video_count: int
    performance_index: float  # Normalized 0-1, higher = better


@dataclass
class PublishTimeRecommendation:
    """Recommended publish time with reasoning."""
    day_of_week: int
    day_name: str
    hour: int
    time_display: str  # e.g., "3:00 PM"
    performance_index: float
    confidence: str  # low, medium, high
    reasoning: str
    video_count_basis: int


@dataclass
class PublishTimeAnalysis:
    """Complete publish time analysis result."""
    # Top recommendations
    top_times: List[PublishTimeRecommendation]
    
    # Worst times to avoid
    worst_times: List[PublishTimeRecommendation]
    
    # Heatmap data (7 days x 24 hours)
    heatmap: Dict[int, Dict[int, float]]  # day -> hour -> performance
    
    # Summary stats
    best_day: str
    worst_day: str
    peak_hours: List[int]
    
    # Data quality
    total_videos_analyzed: int
    confidence_level: str


class PublishTimeAnalyzer:
    """
    Analyze optimal publish times based on historical data.
    
    Considers:
    - Category-level patterns
    - Niche-specific patterns (if available)
    - Channel-specific history (if provided)
    - Day of week and hour combinations
    """
    
    DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    def __init__(self, session: Session):
        self.session = session
    
    def analyze(
        self,
        category: str,
        niche_id: Optional[int] = None,
        channel_id: Optional[str] = None,
        min_videos: int = 10
    ) -> PublishTimeAnalysis:
        """
        Analyze best publish times for a category/niche/channel.
        
        Args:
            category: Video category (gaming, tech, etc.)
            niche_id: Optional niche for more specific analysis
            channel_id: Optional channel for personalized recommendations
            min_videos: Minimum videos needed per slot for confidence
            
        Returns:
            PublishTimeAnalysis with recommendations
        """
        # Get performance by time slot
        time_slots = self._get_time_slot_performance(category, niche_id, channel_id)
        
        if not time_slots:
            logger.warning(f"No data found for category={category}, niche={niche_id}")
            return self._empty_analysis()
        
        # Build heatmap
        heatmap = self._build_heatmap(time_slots)
        
        # Find top and worst times
        sorted_slots = sorted(time_slots, key=lambda x: x.performance_index, reverse=True)
        
        # Get top 5 recommendations
        top_times = []
        seen_combos = set()
        for slot in sorted_slots:
            combo = (slot.day_of_week, slot.hour)
            if combo not in seen_combos and slot.video_count >= min_videos:
                confidence = self._calculate_confidence(slot.video_count)
                top_times.append(PublishTimeRecommendation(
                    day_of_week=slot.day_of_week,
                    day_name=self.DAY_NAMES[slot.day_of_week],
                    hour=slot.hour,
                    time_display=self._format_hour(slot.hour),
                    performance_index=slot.performance_index,
                    confidence=confidence,
                    reasoning=self._generate_reasoning(slot, "top"),
                    video_count_basis=slot.video_count
                ))
                seen_combos.add(combo)
            if len(top_times) >= 5:
                break
        
        # Get worst 3 times
        worst_times = []
        seen_combos = set()
        for slot in reversed(sorted_slots):
            combo = (slot.day_of_week, slot.hour)
            if combo not in seen_combos and slot.video_count >= min_videos:
                confidence = self._calculate_confidence(slot.video_count)
                worst_times.append(PublishTimeRecommendation(
                    day_of_week=slot.day_of_week,
                    day_name=self.DAY_NAMES[slot.day_of_week],
                    hour=slot.hour,
                    time_display=self._format_hour(slot.hour),
                    performance_index=slot.performance_index,
                    confidence=confidence,
                    reasoning=self._generate_reasoning(slot, "worst"),
                    video_count_basis=slot.video_count
                ))
                seen_combos.add(combo)
            if len(worst_times) >= 3:
                break
        
        # Summary stats
        day_performance = defaultdict(list)
        hour_performance = defaultdict(list)
        
        for slot in time_slots:
            day_performance[slot.day_of_week].append(slot.performance_index)
            hour_performance[slot.hour].append(slot.performance_index)
        
        best_day_idx = max(day_performance.keys(), key=lambda d: np.mean(day_performance[d]))
        worst_day_idx = min(day_performance.keys(), key=lambda d: np.mean(day_performance[d]))
        
        # Peak hours (top 25% of hours)
        hour_avgs = {h: np.mean(hour_performance[h]) for h in hour_performance}
        threshold = np.percentile(list(hour_avgs.values()), 75)
        peak_hours = sorted([h for h, avg in hour_avgs.items() if avg >= threshold])
        
        total_videos = sum(s.video_count for s in time_slots)
        confidence = "high" if total_videos > 5000 else "medium" if total_videos > 1000 else "low"
        
        return PublishTimeAnalysis(
            top_times=top_times,
            worst_times=worst_times,
            heatmap=heatmap,
            best_day=self.DAY_NAMES[best_day_idx],
            worst_day=self.DAY_NAMES[worst_day_idx],
            peak_hours=peak_hours,
            total_videos_analyzed=total_videos,
            confidence_level=confidence
        )
    
    def _get_time_slot_performance(
        self,
        category: str,
        niche_id: Optional[int],
        channel_id: Optional[str]
    ) -> List[TimeSlotPerformance]:
        """Query database for performance by time slot."""
        
        # Build query
        query = self.session.query(
            extract('dow', Video.published_at).label('day_of_week'),  # 0=Sunday in PostgreSQL
            extract('hour', Video.published_at).label('hour'),
            func.avg(Video.view_count).label('avg_views'),
            func.avg(Video.engagement_rate).label('avg_engagement'),
            func.count(Video.id).label('video_count')
        ).join(
            Channel, Video.channel_id == Channel.channel_id
        ).filter(
            Channel.primary_category == category,
            Video.view_count > 0
        )
        
        if niche_id:
            query = query.filter(Channel.niche_id == niche_id)
        
        if channel_id:
            query = query.filter(Video.channel_id == channel_id)
        
        query = query.group_by('day_of_week', 'hour')
        
        results = query.all()
        
        if not results:
            return []
        
        # Convert to TimeSlotPerformance objects
        # Note: PostgreSQL DOW is 0=Sunday, so we adjust to 0=Monday
        slots = []
        all_views = [r.avg_views for r in results if r.avg_views]
        
        if not all_views:
            return []
        
        max_views = max(all_views)
        min_views = min(all_views)
        view_range = max_views - min_views if max_views != min_views else 1
        
        for r in results:
            # Adjust DOW: PostgreSQL 0=Sunday -> Python 0=Monday
            dow_adjusted = (int(r.day_of_week) - 1) % 7 if r.day_of_week is not None else 0
            
            # Normalize performance to 0-1
            perf_index = (r.avg_views - min_views) / view_range if r.avg_views else 0
            
            slots.append(TimeSlotPerformance(
                day_of_week=dow_adjusted,
                hour=int(r.hour) if r.hour is not None else 0,
                avg_views=float(r.avg_views or 0),
                avg_engagement_rate=float(r.avg_engagement or 0),
                video_count=int(r.video_count),
                performance_index=float(perf_index)
            ))
        
        return slots
    
    def _build_heatmap(self, time_slots: List[TimeSlotPerformance]) -> Dict[int, Dict[int, float]]:
        """Build a 7x24 heatmap of performance."""
        heatmap = {day: {hour: 0.0 for hour in range(24)} for day in range(7)}
        
        for slot in time_slots:
            heatmap[slot.day_of_week][slot.hour] = slot.performance_index
        
        return heatmap
    
    def _calculate_confidence(self, video_count: int) -> str:
        """Calculate confidence based on sample size."""
        if video_count >= 100:
            return "high"
        elif video_count >= 30:
            return "medium"
        return "low"
    
    def _format_hour(self, hour: int) -> str:
        """Format hour as readable time."""
        if hour == 0:
            return "12:00 AM"
        elif hour < 12:
            return f"{hour}:00 AM"
        elif hour == 12:
            return "12:00 PM"
        else:
            return f"{hour - 12}:00 PM"
    
    def _generate_reasoning(self, slot: TimeSlotPerformance, position: str) -> str:
        """Generate human-readable reasoning."""
        day_name = self.DAY_NAMES[slot.day_of_week]
        time_str = self._format_hour(slot.hour)
        
        if position == "top":
            perf_pct = int(slot.performance_index * 100)
            return f"{day_name} at {time_str} shows {perf_pct}% relative performance based on {slot.video_count} videos"
        else:
            perf_pct = int(slot.performance_index * 100)
            return f"Avoid {day_name} at {time_str} - only {perf_pct}% relative performance ({slot.video_count} videos)"
    
    def _empty_analysis(self) -> PublishTimeAnalysis:
        """Return empty analysis when no data available."""
        return PublishTimeAnalysis(
            top_times=[],
            worst_times=[],
            heatmap={day: {hour: 0.5 for hour in range(24)} for day in range(7)},
            best_day="Unknown",
            worst_day="Unknown",
            peak_hours=[],
            total_videos_analyzed=0,
            confidence_level="low"
        )
    
    def get_quick_recommendation(
        self,
        category: str,
        niche_id: Optional[int] = None
    ) -> Tuple[str, str, str]:
        """
        Get a quick recommendation without full analysis.
        
        Returns:
            (best_day, best_time, confidence)
        """
        analysis = self.analyze(category, niche_id)
        
        if not analysis.top_times:
            return ("Saturday", "3:00 PM", "low")  # Default fallback
        
        top = analysis.top_times[0]
        return (top.day_name, top.time_display, top.confidence)


def analyze_publish_times(
    session: Session,
    category: str,
    niche_id: Optional[int] = None
) -> PublishTimeAnalysis:
    """Convenience function for publish time analysis."""
    analyzer = PublishTimeAnalyzer(session)
    return analyzer.analyze(category, niche_id)

