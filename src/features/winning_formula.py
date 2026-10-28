"""Your Winning Formula -- per-channel pattern discovery.

This module analyses a single creator's channel to surface *correlational*
patterns in their history — things their past hits share vs their flops. These
are HYPOTHESES TO TEST, not proven causes. Honesty caveat (memory:
content-classifier-title-no-signal): packaging (title/thumbnail) does NOT
reliably separate a channel's hits from its flops on rigorous evaluation, so the
title/thumbnail patterns here are weak/correlational and must be framed as such.
Posting-time and topic/content patterns are sturdier but still observational.

1. What their past hits share vs their flops (correlational)
2. Title structures that *co-occur* with their hits (weak — test it)
3. Thumbnail patterns that *co-occur* with their hits (weak — test it)
4. Posting times associated with higher early velocity
5. Content/topic patterns in their top performers

Relationship to :mod:`src.features.niche_patterns`
--------------------------------------------------

``niche_patterns`` discovers patterns across an entire niche/category
(``"tech"``, ``"gaming"``, ...) by aggregating thousands of videos.
``winning_formula`` zooms in on a *single channel* and surfaces what's
working for them specifically.

The two modules share concept classes (``TitlePattern``, ``ThumbnailPattern``)
because the discovery primitives are the same. Future cleanup: hoist the
shared primitives into ``src/features/_pattern_types.py`` so both modules
import from a single source instead of redeclaring the dataclasses.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from collections import Counter
import re
import numpy as np

from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures, VideoContentAnalysis


@dataclass
class TitlePattern:
    """A pattern found in successful titles."""
    pattern: str
    description: str
    frequency: float  # How often it appears in top videos
    avg_performance: float  # Avg performance ratio when used
    examples: List[str]


@dataclass
class ThumbnailPattern:
    """A pattern found in successful thumbnails."""
    pattern: str
    description: str
    frequency: float
    avg_performance: float


@dataclass 
class ContentPattern:
    """A pattern found in successful video content."""
    pattern: str
    description: str
    avg_value: float
    top_performer_avg: float
    recommendation: str


@dataclass
class EngagementComparison:
    """Compare video engagement to channel baseline."""
    like_ratio: float  # likes / views
    comment_ratio: float  # comments / views
    baseline_like_ratio: float  # channel average
    baseline_comment_ratio: float  # channel average
    like_ratio_vs_baseline: float  # ratio (1.0 = same as baseline)
    comment_ratio_vs_baseline: float  # ratio
    like_percentile: float  # 0-100, where this video ranks
    comment_percentile: float  # 0-100
    assessment: str  # "above_average", "average", "below_average"


@dataclass
class WinningFormula:
    """Complete analysis of a creator's winning formula."""
    channel_name: str
    channel_id: str
    total_videos_analyzed: int
    avg_views: float
    hit_rate: float  # % of videos that outperform
    
    # What makes their hits
    title_patterns: List[TitlePattern]
    thumbnail_patterns: List[ThumbnailPattern]
    content_patterns: List[ContentPattern]
    
    # Optimal settings
    optimal_title_length: Tuple[int, int]  # min, max
    optimal_video_length: Tuple[int, int]  # min, max in seconds
    best_posting_times: List[str]
    
    # Top performers for reference
    top_videos: List[Dict]
    
    # Key insights
    key_insights: List[str]
    
    # Engagement baseline (NEW)
    baseline_like_ratio: float = 0.0
    baseline_comment_ratio: float = 0.0
    

class WinningFormulaAnalyzer:
    """Discovers a creator's unique winning formula."""
    
    def analyze(self, channel_id: str) -> Optional[WinningFormula]:
        """
        Analyze a channel to discover their winning formula.
        
        Args:
            channel_id: YouTube channel ID
            
        Returns:
            WinningFormula or None if not enough data
        """
        with get_session() as session:
            # Get channel
            channel = session.query(Channel).filter_by(channel_id=channel_id).first()
            if not channel:
                return None
            
            # Get all videos with features
            videos = session.query(Video).filter_by(
                channel_id=channel_id
            ).order_by(Video.view_count.desc()).all()
            
            if len(videos) < 10:
                return None  # Need at least 10 videos
            
            # Calculate channel average
            avg_views = channel.avg_views_per_video or np.mean([v.view_count for v in videos])
            
            # Classify hits vs flops
            hits = [v for v in videos if v.view_count > avg_views * 1.5]
            flops = [v for v in videos if v.view_count < avg_views * 0.5]
            
            hit_rate = len(hits) / len(videos) if videos else 0
            
            # Get features for analysis
            video_ids = [v.video_id for v in videos]
            features = {f.video_id: f for f in session.query(VideoFeatures).filter(
                VideoFeatures.video_id.in_(video_ids)
            ).all()}
            
            # Get content analysis
            content = {c.video_id: c for c in session.query(VideoContentAnalysis).filter(
                VideoContentAnalysis.video_id.in_(video_ids)
            ).all()}
            
            # Analyze title patterns
            title_patterns = self._analyze_title_patterns(hits, flops, avg_views)
            
            # Analyze thumbnail patterns  
            thumbnail_patterns = self._analyze_thumbnail_patterns(hits, flops, features)
            
            # Analyze content patterns
            content_patterns = self._analyze_content_patterns(hits, flops, content)
            
            # Find optimal settings
            optimal_title_length = self._find_optimal_title_length(hits)
            optimal_video_length = self._find_optimal_video_length(hits)
            best_posting_times = self._find_best_posting_times(hits)
            
            # Generate key insights
            key_insights = self._generate_insights(
                hits, flops, title_patterns, thumbnail_patterns, content_patterns
            )
            
            # Top videos
            top_videos = [
                {
                    "title": v.title,
                    "views": v.view_count,
                    "ratio": v.view_count / avg_views if avg_views else 0,
                    "published": str(v.published_at) if v.published_at else None
                }
                for v in videos[:5]
            ]
            
            return WinningFormula(
                channel_name=channel.channel_name,
                channel_id=channel_id,
                total_videos_analyzed=len(videos),
                avg_views=avg_views,
                hit_rate=hit_rate,
                title_patterns=title_patterns,
                thumbnail_patterns=thumbnail_patterns,
                content_patterns=content_patterns,
                optimal_title_length=optimal_title_length,
                optimal_video_length=optimal_video_length,
                best_posting_times=best_posting_times,
                top_videos=top_videos,
                key_insights=key_insights,
            )
    
    def _analyze_title_patterns(
        self, 
        hits: List[Video], 
        flops: List[Video],
        avg_views: float
    ) -> List[TitlePattern]:
        """Find title patterns that differentiate hits from flops."""
        patterns = []
        
        hit_titles = [v.title for v in hits]
        flop_titles = [v.title for v in flops]
        
        # Pattern: Contains number
        hit_has_number = sum(1 for t in hit_titles if re.search(r'\d', t)) / max(len(hit_titles), 1)
        flop_has_number = sum(1 for t in flop_titles if re.search(r'\d', t)) / max(len(flop_titles), 1)
        
        if hit_has_number > flop_has_number + 0.1:
            patterns.append(TitlePattern(
                pattern="contains_number",
                description="Titles with numbers perform better for you",
                frequency=hit_has_number,
                avg_performance=1.5 * (hit_has_number - flop_has_number + 1),
                examples=[t for t in hit_titles if re.search(r'\d', t)][:3]
            ))
        
        # Pattern: Question mark
        hit_has_question = sum(1 for t in hit_titles if '?' in t) / max(len(hit_titles), 1)
        flop_has_question = sum(1 for t in flop_titles if '?' in t) / max(len(flop_titles), 1)
        
        if hit_has_question > flop_has_question + 0.1:
            patterns.append(TitlePattern(
                pattern="question_format",
                description="Question titles drive more clicks for your audience",
                frequency=hit_has_question,
                avg_performance=1.5 * (hit_has_question - flop_has_question + 1),
                examples=[t for t in hit_titles if '?' in t][:3]
            ))
        
        # Pattern: Short vs Long titles
        hit_avg_length = np.mean([len(t) for t in hit_titles]) if hit_titles else 50
        flop_avg_length = np.mean([len(t) for t in flop_titles]) if flop_titles else 50
        
        if hit_avg_length < flop_avg_length - 5:
            patterns.append(TitlePattern(
                pattern="shorter_titles",
                description=f"Your hits average {hit_avg_length:.0f} chars vs {flop_avg_length:.0f} for flops",
                frequency=1.0,
                avg_performance=1.3,
                examples=sorted(hit_titles, key=len)[:3]
            ))
        elif hit_avg_length > flop_avg_length + 5:
            patterns.append(TitlePattern(
                pattern="longer_titles",
                description=f"Your hits are more descriptive ({hit_avg_length:.0f} chars)",
                frequency=1.0,
                avg_performance=1.3,
                examples=sorted(hit_titles, key=len, reverse=True)[:3]
            ))
        
        # Pattern: Power words
        power_words = ["insane", "epic", "amazing", "incredible", "shocking", "secret"]
        hit_power = sum(1 for t in hit_titles if any(w in t.lower() for w in power_words)) / max(len(hit_titles), 1)
        flop_power = sum(1 for t in flop_titles if any(w in t.lower() for w in power_words)) / max(len(flop_titles), 1)
        
        if hit_power > flop_power + 0.1:
            patterns.append(TitlePattern(
                pattern="emotional_words",
                description="Emotional language resonates with your audience",
                frequency=hit_power,
                avg_performance=1.4,
                examples=[t for t in hit_titles if any(w in t.lower() for w in power_words)][:3]
            ))
        
        # Pattern: Capitalization
        hit_caps = sum(1 for t in hit_titles if t.isupper() or any(w.isupper() for w in t.split() if len(w) > 2)) / max(len(hit_titles), 1)
        flop_caps = sum(1 for t in flop_titles if t.isupper() or any(w.isupper() for w in t.split() if len(w) > 2)) / max(len(flop_titles), 1)
        
        if hit_caps > flop_caps + 0.15:
            patterns.append(TitlePattern(
                pattern="strategic_caps",
                description="Strategic capitalization grabs attention for you",
                frequency=hit_caps,
                avg_performance=1.25,
                examples=[t for t in hit_titles if any(w.isupper() for w in t.split() if len(w) > 2)][:3]
            ))
        
        return patterns
    
    def _analyze_thumbnail_patterns(
        self,
        hits: List[Video],
        flops: List[Video],
        features: Dict[str, VideoFeatures]
    ) -> List[ThumbnailPattern]:
        """Find thumbnail patterns that work."""
        patterns = []
        
        hit_features = [features.get(v.video_id) for v in hits if v.video_id in features]
        flop_features = [features.get(v.video_id) for v in flops if v.video_id in features]
        
        hit_features = [f for f in hit_features if f]
        flop_features = [f for f in flop_features if f]
        
        if not hit_features or not flop_features:
            return patterns
        
        # Pattern: Face in thumbnail
        hit_face = sum(1 for f in hit_features if f.face_count and f.face_count > 0) / len(hit_features)
        flop_face = sum(1 for f in flop_features if f.face_count and f.face_count > 0) / len(flop_features)
        
        if hit_face > flop_face + 0.15:
            patterns.append(ThumbnailPattern(
                pattern="face_present",
                description="Thumbnails with faces perform better for you",
                frequency=hit_face,
                avg_performance=1.0 + (hit_face - flop_face)
            ))
        elif flop_face > hit_face + 0.15:
            patterns.append(ThumbnailPattern(
                pattern="no_face",
                description="Your audience prefers thumbnails without faces",
                frequency=1 - hit_face,
                avg_performance=1.0 + (flop_face - hit_face)
            ))
        
        # Pattern: Text in thumbnail
        hit_text = sum(1 for f in hit_features if f.text_count and f.text_count > 0) / len(hit_features)
        flop_text = sum(1 for f in flop_features if f.text_count and f.text_count > 0) / len(flop_features)
        
        if hit_text > flop_text + 0.15:
            patterns.append(ThumbnailPattern(
                pattern="text_overlay",
                description="Text overlays boost your thumbnails",
                frequency=hit_text,
                avg_performance=1.0 + (hit_text - flop_text)
            ))
        
        # Pattern: Brightness
        hit_brightness = [f.brightness for f in hit_features if f.brightness]
        flop_brightness = [f.brightness for f in flop_features if f.brightness]
        
        if hit_brightness and flop_brightness:
            avg_hit_bright = np.mean(hit_brightness)
            avg_flop_bright = np.mean(flop_brightness)
            
            if avg_hit_bright > avg_flop_bright + 15:
                patterns.append(ThumbnailPattern(
                    pattern="brighter_thumbnails",
                    description="Brighter thumbnails work better for your channel",
                    frequency=1.0,
                    avg_performance=1.2
                ))
            elif avg_hit_bright < avg_flop_bright - 15:
                patterns.append(ThumbnailPattern(
                    pattern="darker_thumbnails", 
                    description="Your audience responds to darker, moodier thumbnails",
                    frequency=1.0,
                    avg_performance=1.2
                ))
        
        # Pattern: Dominant colors
        hit_colors = Counter([f.dominant_color for f in hit_features if f.dominant_color])
        flop_colors = Counter([f.dominant_color for f in flop_features if f.dominant_color])
        
        if hit_colors:
            top_hit_color = hit_colors.most_common(1)[0][0]
            hit_rate = hit_colors[top_hit_color] / len(hit_features)
            flop_rate = flop_colors.get(top_hit_color, 0) / max(len(flop_features), 1)
            
            if hit_rate > flop_rate + 0.1:
                patterns.append(ThumbnailPattern(
                    pattern=f"color_{top_hit_color}",
                    description=f"Your hits often feature {top_hit_color} prominently",
                    frequency=hit_rate,
                    avg_performance=1.15
                ))
        
        return patterns
    
    def _analyze_content_patterns(
        self,
        hits: List[Video],
        flops: List[Video],
        content: Dict[str, VideoContentAnalysis]
    ) -> List[ContentPattern]:
        """Find content patterns in successful videos."""
        patterns = []
        
        hit_content = [content.get(v.video_id) for v in hits if v.video_id in content]
        flop_content = [content.get(v.video_id) for v in flops if v.video_id in content]
        
        hit_content = [c for c in hit_content if c and c.extraction_success]
        flop_content = [c for c in flop_content if c and c.extraction_success]
        
        if not hit_content or not flop_content:
            return patterns
        
        # Hook timing
        hit_hooks = [c.face_appears_seconds for c in hit_content if c.face_appears_seconds]
        flop_hooks = [c.face_appears_seconds for c in flop_content if c.face_appears_seconds]
        
        if hit_hooks and flop_hooks:
            avg_hit = np.mean(hit_hooks)
            avg_flop = np.mean(flop_hooks)
            
            if avg_hit < avg_flop - 2:
                patterns.append(ContentPattern(
                    pattern="fast_hook",
                    description="Your hits have faster hooks",
                    avg_value=avg_flop,
                    top_performer_avg=avg_hit,
                    recommendation=f"Show face within {avg_hit:.0f} seconds"
                ))
        
        # Scene changes/pacing
        hit_scenes = [c.total_scene_changes for c in hit_content if c.total_scene_changes]
        flop_scenes = [c.total_scene_changes for c in flop_content if c.total_scene_changes]
        
        if hit_scenes and flop_scenes:
            avg_hit = np.mean(hit_scenes)
            avg_flop = np.mean(flop_scenes)
            
            if avg_hit > avg_flop * 1.3:
                patterns.append(ContentPattern(
                    pattern="high_pacing",
                    description="Your audience likes faster-paced content",
                    avg_value=avg_flop,
                    top_performer_avg=avg_hit,
                    recommendation=f"Target {avg_hit:.0f} scene changes per video"
                ))
            elif avg_hit < avg_flop * 0.7:
                patterns.append(ContentPattern(
                    pattern="slower_pacing",
                    description="Your audience prefers a calmer pace",
                    avg_value=avg_flop,
                    top_performer_avg=avg_hit,
                    recommendation="Don't over-edit - let moments breathe"
                ))
        
        # Music intro
        hit_music = sum(1 for c in hit_content if c.has_music_intro) / len(hit_content)
        flop_music = sum(1 for c in flop_content if c.has_music_intro) / len(flop_content)
        
        if hit_music > flop_music + 0.2:
            patterns.append(ContentPattern(
                pattern="music_intro",
                description="Music intros work for your channel",
                avg_value=flop_music,
                top_performer_avg=hit_music,
                recommendation="Start with an engaging music intro"
            ))
        elif flop_music > hit_music + 0.2:
            patterns.append(ContentPattern(
                pattern="no_music_intro",
                description="Skip the music intro - get straight to content",
                avg_value=flop_music,
                top_performer_avg=hit_music,
                recommendation="Jump right into the content"
            ))
        
        return patterns
    
    def _find_optimal_title_length(self, hits: List[Video]) -> Tuple[int, int]:
        """Find optimal title length range."""
        if not hits:
            return (40, 60)
        
        lengths = [len(v.title) for v in hits]
        return (int(np.percentile(lengths, 25)), int(np.percentile(lengths, 75)))
    
    def _find_optimal_video_length(self, hits: List[Video]) -> Tuple[int, int]:
        """Find optimal video length range."""
        if not hits:
            return (480, 900)  # 8-15 min default
        
        durations = [v.duration_seconds for v in hits if v.duration_seconds]
        if not durations:
            return (480, 900)
        
        return (int(np.percentile(durations, 25)), int(np.percentile(durations, 75)))
    
    def _find_best_posting_times(self, hits: List[Video]) -> List[str]:
        """Find best posting times."""
        if not hits:
            return ["Weekdays 2-4 PM"]
        
        times = []
        for v in hits:
            if v.published_at:
                hour = v.published_at.hour
                day = v.published_at.strftime("%A")
                times.append((day, hour))
        
        if not times:
            return ["Weekdays 2-4 PM"]
        
        # Count by day and hour
        day_counts = Counter([t[0] for t in times])
        hour_counts = Counter([t[1] for t in times])
        
        best_days = [d for d, _ in day_counts.most_common(2)]
        best_hours = [h for h, _ in hour_counts.most_common(2)]
        
        results = []
        for day in best_days:
            for hour in best_hours:
                time_str = f"{hour}:00" if hour >= 12 else f"{hour}:00 AM"
                if hour >= 12:
                    time_str = f"{hour-12 if hour > 12 else 12}:00 PM"
                results.append(f"{day}s at {time_str}")
        
        return results[:3] if results else ["Weekdays 2-4 PM"]
    
    def _generate_insights(
        self,
        hits: List[Video],
        flops: List[Video],
        title_patterns: List[TitlePattern],
        thumbnail_patterns: List[ThumbnailPattern],
        content_patterns: List[ContentPattern]
    ) -> List[str]:
        """Generate key insights from the analysis."""
        insights = []
        
        # Hit rate insight
        total = len(hits) + len(flops)
        if total > 0:
            hit_rate = len(hits) / total
            if hit_rate > 0.3:
                insights.append(f"🔥 Strong consistency: {hit_rate*100:.0f}% of your videos outperform")
            elif hit_rate < 0.15:
                insights.append(f"📈 Room to grow: Only {hit_rate*100:.0f}% outperform - focus on patterns below")
        
        # Top title pattern
        if title_patterns:
            top_title = title_patterns[0]
            insights.append(f"📝 Title secret: {top_title.description}")
        
        # Top thumbnail pattern
        if thumbnail_patterns:
            top_thumb = thumbnail_patterns[0]
            insights.append(f"🖼️ Thumbnail secret: {top_thumb.description}")
        
        # Top content pattern
        if content_patterns:
            top_content = content_patterns[0]
            insights.append(f"🎬 Content secret: {top_content.recommendation}")
        
        # Length insight
        if hits:
            avg_hit_length = np.mean([v.duration_seconds for v in hits if v.duration_seconds])
            avg_flop_length = np.mean([v.duration_seconds for v in flops if v.duration_seconds] or [avg_hit_length])
            
            if avg_hit_length < avg_flop_length * 0.8:
                insights.append(f"⏱️ Your hits are shorter ({avg_hit_length/60:.0f} min avg)")
            elif avg_hit_length > avg_flop_length * 1.2:
                insights.append(f"⏱️ Your audience prefers longer content ({avg_hit_length/60:.0f} min avg)")
        
        return insights[:5]


def compare_engagement_to_baseline(
    video_views: int,
    video_likes: int, 
    video_comments: int,
    channel_id: str
) -> EngagementComparison:
    """
    Compare a video's engagement metrics to channel baseline.
    
    Args:
        video_views: Video view count
        video_likes: Video like count
        video_comments: Video comment count
        channel_id: Channel ID for baseline
        
    Returns:
        EngagementComparison with ratios and percentiles
    """
    with get_session() as session:
        # Get all videos for baseline
        videos = session.query(
            Video.view_count, Video.like_count, Video.comment_count
        ).filter(
            Video.channel_id == channel_id,
            Video.view_count > 0
        ).all()
        
        if not videos:
            # No baseline available
            like_ratio = video_likes / video_views if video_views > 0 else 0
            comment_ratio = video_comments / video_views if video_views > 0 else 0
            return EngagementComparison(
                like_ratio=like_ratio,
                comment_ratio=comment_ratio,
                baseline_like_ratio=0.03,  # Default ~3%
                baseline_comment_ratio=0.001,  # Default ~0.1%
                like_ratio_vs_baseline=like_ratio / 0.03 if like_ratio > 0 else 0,
                comment_ratio_vs_baseline=comment_ratio / 0.001 if comment_ratio > 0 else 0,
                like_percentile=50.0,
                comment_percentile=50.0,
                assessment="unknown"
            )
        
        # Calculate baseline ratios
        like_ratios = [(v.like_count or 0) / v.view_count for v in videos if v.view_count > 0]
        comment_ratios = [(v.comment_count or 0) / v.view_count for v in videos if v.view_count > 0]
        
        baseline_like = np.mean(like_ratios) if like_ratios else 0.03
        baseline_comment = np.mean(comment_ratios) if comment_ratios else 0.001
        
        # This video's ratios
        video_like_ratio = video_likes / video_views if video_views > 0 else 0
        video_comment_ratio = video_comments / video_views if video_views > 0 else 0
        
        # Ratios vs baseline
        like_vs_baseline = video_like_ratio / baseline_like if baseline_like > 0 else 1.0
        comment_vs_baseline = video_comment_ratio / baseline_comment if baseline_comment > 0 else 1.0
        
        # Calculate percentiles
        like_percentile = sum(1 for r in like_ratios if r < video_like_ratio) / len(like_ratios) * 100 if like_ratios else 50
        comment_percentile = sum(1 for r in comment_ratios if r < video_comment_ratio) / len(comment_ratios) * 100 if comment_ratios else 50
        
        # Overall assessment
        avg_vs_baseline = (like_vs_baseline + comment_vs_baseline) / 2
        if avg_vs_baseline > 1.2:
            assessment = "above_average"
        elif avg_vs_baseline < 0.8:
            assessment = "below_average"
        else:
            assessment = "average"
        
        return EngagementComparison(
            like_ratio=video_like_ratio,
            comment_ratio=video_comment_ratio,
            baseline_like_ratio=baseline_like,
            baseline_comment_ratio=baseline_comment,
            like_ratio_vs_baseline=like_vs_baseline,
            comment_ratio_vs_baseline=comment_vs_baseline,
            like_percentile=like_percentile,
            comment_percentile=comment_percentile,
            assessment=assessment
        )


def analyze_channel(channel_id: str) -> Optional[WinningFormula]:
    """
    Convenience function to analyze a channel's winning formula.
    
    Args:
        channel_id: YouTube channel ID
        
    Returns:
        WinningFormula or None
    """
    analyzer = WinningFormulaAnalyzer()
    return analyzer.analyze(channel_id)

