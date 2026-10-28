"""
Competitor Analysis

Compares your channel against competitors to find:
1. What they're doing that you're not
2. Where you're winning
3. Gaps and opportunities
4. Their successful patterns you could adopt
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from collections import Counter
import re
import numpy as np
from datetime import datetime, timedelta

from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures


@dataclass
class MetricComparison:
    """Comparison of a single metric."""
    metric_name: str
    your_value: float
    competitor_value: float
    difference_percent: float
    winner: str  # "you", "competitor", "tie"
    insight: str


@dataclass
class StrategyDifference:
    """A strategic difference between channels."""
    strategy: str
    description: str
    your_approach: str
    competitor_approach: str
    recommendation: str
    impact: str  # "high", "medium", "low"


@dataclass
class OpportunityGap:
    """An opportunity gap to exploit."""
    opportunity: str
    description: str
    competitor_does: bool
    potential_impact: str
    action_item: str


@dataclass
class CompetitorReport:
    """Complete competitor comparison report."""
    your_channel: str
    your_channel_id: str
    competitor_channel: str
    competitor_channel_id: str
    
    # Overview metrics
    metrics: List[MetricComparison]
    
    # Strategic differences
    strategy_differences: List[StrategyDifference]
    
    # Opportunities
    opportunities: List[OpportunityGap]
    
    # What they do well (to learn from)
    competitor_strengths: List[str]
    
    # Where you're winning
    your_advantages: List[str]
    
    # Top competitor videos to study
    competitor_top_videos: List[Dict]
    
    # Summary
    key_takeaways: List[str]


class CompetitorAnalyzer:
    """Analyzes your channel vs a competitor."""
    
    def compare(
        self, 
        your_channel_id: str, 
        competitor_channel_id: str
    ) -> Optional[CompetitorReport]:
        """
        Compare your channel to a competitor.
        
        Args:
            your_channel_id: Your YouTube channel ID
            competitor_channel_id: Competitor's YouTube channel ID
            
        Returns:
            CompetitorReport or None if not enough data
        """
        with get_session() as session:
            # Get channels
            your_channel = session.query(Channel).filter_by(
                channel_id=your_channel_id
            ).first()
            comp_channel = session.query(Channel).filter_by(
                channel_id=competitor_channel_id
            ).first()
            
            if not your_channel or not comp_channel:
                return None
            
            # Get videos
            your_videos = session.query(Video).filter_by(
                channel_id=your_channel_id
            ).order_by(Video.published_at.desc()).limit(100).all()
            
            comp_videos = session.query(Video).filter_by(
                channel_id=competitor_channel_id
            ).order_by(Video.published_at.desc()).limit(100).all()
            
            if len(your_videos) < 5 or len(comp_videos) < 5:
                return None
            
            # Get features
            your_video_ids = [v.video_id for v in your_videos]
            comp_video_ids = [v.video_id for v in comp_videos]
            
            your_features = {f.video_id: f for f in session.query(VideoFeatures).filter(
                VideoFeatures.video_id.in_(your_video_ids)
            ).all()}
            
            comp_features = {f.video_id: f for f in session.query(VideoFeatures).filter(
                VideoFeatures.video_id.in_(comp_video_ids)
            ).all()}
            
            # Compare metrics
            metrics = self._compare_metrics(
                your_channel, comp_channel, your_videos, comp_videos
            )
            
            # Find strategy differences
            strategy_diffs = self._find_strategy_differences(
                your_videos, comp_videos, your_features, comp_features
            )
            
            # Find opportunities
            opportunities = self._find_opportunities(
                your_videos, comp_videos, your_features, comp_features
            )
            
            # Competitor strengths
            comp_strengths = self._analyze_competitor_strengths(
                comp_channel, comp_videos, comp_features
            )
            
            # Your advantages
            your_advantages = self._find_your_advantages(
                your_channel, comp_channel, your_videos, comp_videos,
                your_features, comp_features
            )
            
            # Top competitor videos
            top_comp_videos = [
                {
                    "title": v.title,
                    "views": v.view_count,
                    "video_id": v.video_id,
                    "why_study": self._why_study_video(v, comp_channel.avg_views_per_video)
                }
                for v in sorted(comp_videos, key=lambda x: x.view_count, reverse=True)[:5]
            ]
            
            # Key takeaways
            takeaways = self._generate_takeaways(
                metrics, strategy_diffs, opportunities, comp_strengths, your_advantages
            )
            
            return CompetitorReport(
                your_channel=your_channel.channel_name,
                your_channel_id=your_channel_id,
                competitor_channel=comp_channel.channel_name,
                competitor_channel_id=competitor_channel_id,
                metrics=metrics,
                strategy_differences=strategy_diffs,
                opportunities=opportunities,
                competitor_strengths=comp_strengths,
                your_advantages=your_advantages,
                competitor_top_videos=top_comp_videos,
                key_takeaways=takeaways,
            )
    
    def _compare_metrics(
        self,
        your_channel: Channel,
        comp_channel: Channel,
        your_videos: List[Video],
        comp_videos: List[Video]
    ) -> List[MetricComparison]:
        """Compare key metrics."""
        metrics = []
        
        # Subscriber count
        your_subs = your_channel.subscriber_count or 0
        comp_subs = comp_channel.subscriber_count or 0
        if your_subs and comp_subs:
            diff = ((your_subs - comp_subs) / comp_subs * 100) if comp_subs else 0
            metrics.append(MetricComparison(
                metric_name="Subscribers",
                your_value=your_subs,
                competitor_value=comp_subs,
                difference_percent=diff,
                winner="you" if your_subs > comp_subs else "competitor",
                insight=f"You have {abs(diff):.0f}% {'more' if diff > 0 else 'fewer'} subscribers"
            ))
        
        # Average views
        your_avg = your_channel.avg_views_per_video or np.mean([v.view_count for v in your_videos])
        comp_avg = comp_channel.avg_views_per_video or np.mean([v.view_count for v in comp_videos])
        if your_avg and comp_avg:
            diff = ((your_avg - comp_avg) / comp_avg * 100) if comp_avg else 0
            metrics.append(MetricComparison(
                metric_name="Avg Views/Video",
                your_value=your_avg,
                competitor_value=comp_avg,
                difference_percent=diff,
                winner="you" if your_avg > comp_avg else "competitor",
                insight=f"Your videos average {abs(diff):.0f}% {'more' if diff > 0 else 'fewer'} views"
            ))
        
        # Upload frequency (last 30 days)
        now = datetime.utcnow()
        month_ago = now - timedelta(days=30)
        
        your_recent = len([v for v in your_videos if v.published_at and v.published_at > month_ago])
        comp_recent = len([v for v in comp_videos if v.published_at and v.published_at > month_ago])
        
        if your_recent or comp_recent:
            diff = ((your_recent - comp_recent) / max(comp_recent, 1) * 100)
            metrics.append(MetricComparison(
                metric_name="Videos/Month",
                your_value=your_recent,
                competitor_value=comp_recent,
                difference_percent=diff,
                winner="you" if your_recent > comp_recent else ("competitor" if comp_recent > your_recent else "tie"),
                insight=f"You upload {your_recent} vs their {comp_recent} videos per month"
            ))
        
        # Hit rate (videos above 1.5x avg)
        your_hits = len([v for v in your_videos if v.view_count > your_avg * 1.5]) / max(len(your_videos), 1)
        comp_hits = len([v for v in comp_videos if v.view_count > comp_avg * 1.5]) / max(len(comp_videos), 1)
        
        diff = ((your_hits - comp_hits) / max(comp_hits, 0.01) * 100)
        metrics.append(MetricComparison(
            metric_name="Hit Rate",
            your_value=your_hits * 100,
            competitor_value=comp_hits * 100,
            difference_percent=diff,
            winner="you" if your_hits > comp_hits else "competitor",
            insight=f"Your hit rate: {your_hits*100:.1f}% vs their {comp_hits*100:.1f}%"
        ))
        
        # Avg video length
        your_duration = np.mean([v.duration_seconds for v in your_videos if v.duration_seconds]) / 60
        comp_duration = np.mean([v.duration_seconds for v in comp_videos if v.duration_seconds]) / 60
        
        if your_duration and comp_duration:
            diff = ((your_duration - comp_duration) / comp_duration * 100)
            metrics.append(MetricComparison(
                metric_name="Avg Video Length (min)",
                your_value=your_duration,
                competitor_value=comp_duration,
                difference_percent=diff,
                winner="tie",  # Neither is better/worse
                insight=f"You avg {your_duration:.1f} min, they avg {comp_duration:.1f} min"
            ))
        
        return metrics
    
    def _find_strategy_differences(
        self,
        your_videos: List[Video],
        comp_videos: List[Video],
        your_features: Dict[str, VideoFeatures],
        comp_features: Dict[str, VideoFeatures]
    ) -> List[StrategyDifference]:
        """Find strategic differences in approach."""
        diffs = []
        
        your_titles = [v.title for v in your_videos]
        comp_titles = [v.title for v in comp_videos]
        
        # Title style differences
        your_questions = sum(1 for t in your_titles if '?' in t) / len(your_titles)
        comp_questions = sum(1 for t in comp_titles if '?' in t) / len(comp_titles)
        
        if abs(your_questions - comp_questions) > 0.15:
            diffs.append(StrategyDifference(
                strategy="Question Titles",
                description="Use of questions in titles",
                your_approach=f"{your_questions*100:.0f}% of titles are questions",
                competitor_approach=f"{comp_questions*100:.0f}% of titles are questions",
                recommendation="Test question titles if you're not using them" if comp_questions > your_questions else "Your question strategy is working",
                impact="medium"
            ))
        
        # Numbers in titles
        your_numbers = sum(1 for t in your_titles if re.search(r'\d', t)) / len(your_titles)
        comp_numbers = sum(1 for t in comp_titles if re.search(r'\d', t)) / len(comp_titles)
        
        if abs(your_numbers - comp_numbers) > 0.15:
            diffs.append(StrategyDifference(
                strategy="Listicle/Number Titles",
                description="Use of numbers in titles",
                your_approach=f"{your_numbers*100:.0f}% include numbers",
                competitor_approach=f"{comp_numbers*100:.0f}% include numbers",
                recommendation="Numbers add specificity - consider using more" if comp_numbers > your_numbers else "You use numbers more - keep it up",
                impact="medium"
            ))
        
        # Title length
        your_length = np.mean([len(t) for t in your_titles])
        comp_length = np.mean([len(t) for t in comp_titles])
        
        if abs(your_length - comp_length) > 10:
            diffs.append(StrategyDifference(
                strategy="Title Length",
                description="Average title character count",
                your_approach=f"Avg {your_length:.0f} characters",
                competitor_approach=f"Avg {comp_length:.0f} characters",
                recommendation=f"Their {'shorter' if comp_length < your_length else 'longer'} titles might be worth testing",
                impact="low"
            ))
        
        # Thumbnail strategies
        your_feat_list = [your_features.get(v.video_id) for v in your_videos if v.video_id in your_features]
        comp_feat_list = [comp_features.get(v.video_id) for v in comp_videos if v.video_id in comp_features]
        
        your_feat_list = [f for f in your_feat_list if f]
        comp_feat_list = [f for f in comp_feat_list if f]
        
        if your_feat_list and comp_feat_list:
            # Face usage
            your_faces = sum(1 for f in your_feat_list if f.face_count and f.face_count > 0) / len(your_feat_list)
            comp_faces = sum(1 for f in comp_feat_list if f.face_count and f.face_count > 0) / len(comp_feat_list)
            
            if abs(your_faces - comp_faces) > 0.2:
                diffs.append(StrategyDifference(
                    strategy="Face in Thumbnails",
                    description="Whether thumbnails show faces",
                    your_approach=f"{your_faces*100:.0f}% show faces",
                    competitor_approach=f"{comp_faces*100:.0f}% show faces",
                    recommendation="Faces build connection" if comp_faces > your_faces else "Your style is working without faces",
                    impact="high"
                ))
            
            # Text usage
            your_text = sum(1 for f in your_feat_list if f.text_count and f.text_count > 0) / len(your_feat_list)
            comp_text = sum(1 for f in comp_feat_list if f.text_count and f.text_count > 0) / len(comp_feat_list)
            
            if abs(your_text - comp_text) > 0.2:
                diffs.append(StrategyDifference(
                    strategy="Text in Thumbnails",
                    description="Text overlays on thumbnails",
                    your_approach=f"{your_text*100:.0f}% have text",
                    competitor_approach=f"{comp_text*100:.0f}% have text",
                    recommendation="Text can add context - test it" if comp_text > your_text else "Clean thumbnails are working for you",
                    impact="medium"
                ))
        
        return diffs
    
    def _find_opportunities(
        self,
        your_videos: List[Video],
        comp_videos: List[Video],
        your_features: Dict[str, VideoFeatures],
        comp_features: Dict[str, VideoFeatures]
    ) -> List[OpportunityGap]:
        """Find opportunities where competitor does something you don't."""
        opportunities = []
        
        # Consistent upload schedule
        comp_days = Counter()
        for v in comp_videos:
            if v.published_at:
                comp_days[v.published_at.strftime("%A")] += 1
        
        if comp_days:
            most_common_day, count = comp_days.most_common(1)[0]
            if count / len(comp_videos) > 0.3:
                opportunities.append(OpportunityGap(
                    opportunity="Consistent Upload Day",
                    description=f"They upload on {most_common_day}s consistently",
                    competitor_does=True,
                    potential_impact="Builds audience habit",
                    action_item=f"Consider establishing a {most_common_day} upload schedule"
                ))
        
        # Content gaps - find topics they cover that you don't
        comp_keywords = self._extract_keywords(comp_videos)
        your_keywords = self._extract_keywords(your_videos)
        
        gap_keywords = [k for k in comp_keywords[:20] if k not in your_keywords[:30]]
        if gap_keywords[:3]:
            opportunities.append(OpportunityGap(
                opportunity="Topic Gaps",
                description=f"They cover: {', '.join(gap_keywords[:3])}",
                competitor_does=True,
                potential_impact="Could capture new audience segments",
                action_item=f"Consider creating content about: {gap_keywords[0]}"
            ))
        
        # Shorts strategy
        your_shorts = len([v for v in your_videos if v.duration_seconds and v.duration_seconds < 60])
        comp_shorts = len([v for v in comp_videos if v.duration_seconds and v.duration_seconds < 60])
        
        if comp_shorts > your_shorts + 5:
            opportunities.append(OpportunityGap(
                opportunity="Shorts Strategy",
                description=f"They post {comp_shorts} shorts vs your {your_shorts}",
                competitor_does=True,
                potential_impact="Shorts can drive discovery and growth",
                action_item="Consider adding Shorts to your content mix"
            ))
        
        # Series/consistent branding
        comp_brackets = sum(1 for v in comp_videos if '[' in v.title or '#' in v.title)
        your_brackets = sum(1 for v in your_videos if '[' in v.title or '#' in v.title)
        
        if comp_brackets > your_brackets + 3:
            opportunities.append(OpportunityGap(
                opportunity="Content Series",
                description="They use series branding ([Part 1], #shorts, etc.)",
                competitor_does=True,
                potential_impact="Series build watch momentum",
                action_item="Create a branded series format"
            ))
        
        return opportunities
    
    def _analyze_competitor_strengths(
        self,
        comp_channel: Channel,
        comp_videos: List[Video],
        comp_features: Dict[str, VideoFeatures]
    ) -> List[str]:
        """Identify what the competitor does well."""
        strengths = []
        
        avg_views = comp_channel.avg_views_per_video or np.mean([v.view_count for v in comp_videos])
        
        # Consistency
        recent = [v for v in comp_videos if v.published_at and v.published_at > datetime.utcnow() - timedelta(days=90)]
        if len(recent) >= 10:
            strengths.append(f"📅 Consistent uploads: {len(recent)} videos in 3 months")
        
        # Hit rate
        hits = [v for v in comp_videos if v.view_count > avg_views * 2]
        if len(hits) / len(comp_videos) > 0.2:
            strengths.append(f"🎯 High hit rate: {len(hits)/len(comp_videos)*100:.0f}% of videos are hits")
        
        # Engagement
        avg_engagement = np.mean([
            (v.like_count or 0) / max(v.view_count, 1) * 100 
            for v in comp_videos
        ])
        if avg_engagement > 4:
            strengths.append(f"❤️ Strong engagement: {avg_engagement:.1f}% like rate")
        
        # Top video analysis
        top_video = max(comp_videos, key=lambda v: v.view_count)
        if top_video.view_count > avg_views * 5:
            strengths.append(f"🚀 Viral potential: Top video got {top_video.view_count/avg_views:.0f}x their average")
        
        return strengths
    
    def _find_your_advantages(
        self,
        your_channel: Channel,
        comp_channel: Channel,
        your_videos: List[Video],
        comp_videos: List[Video],
        your_features: Dict[str, VideoFeatures],
        comp_features: Dict[str, VideoFeatures]
    ) -> List[str]:
        """Find where you're winning."""
        advantages = []
        
        your_avg = your_channel.avg_views_per_video or np.mean([v.view_count for v in your_videos])
        comp_avg = comp_channel.avg_views_per_video or np.mean([v.view_count for v in comp_videos])
        
        # Higher per-video views (normalized by subs)
        your_subs = your_channel.subscriber_count or 1
        comp_subs = comp_channel.subscriber_count or 1
        
        your_ratio = your_avg / your_subs
        comp_ratio = comp_avg / comp_subs
        
        if your_ratio > comp_ratio * 1.2:
            advantages.append(f"📈 Better reach: You get {your_ratio/comp_ratio:.1f}x more views per subscriber")
        
        # Better engagement
        your_engagement = np.mean([
            (v.like_count or 0) / max(v.view_count, 1) * 100 
            for v in your_videos
        ])
        comp_engagement = np.mean([
            (v.like_count or 0) / max(v.view_count, 1) * 100 
            for v in comp_videos
        ])
        
        if your_engagement > comp_engagement * 1.2:
            advantages.append(f"❤️ More engaged audience: {your_engagement:.1f}% vs {comp_engagement:.1f}% like rate")
        
        # Faster growth
        recent_you = [v for v in your_videos[:20] if v.published_at]
        recent_comp = [v for v in comp_videos[:20] if v.published_at]
        
        if recent_you and recent_comp:
            your_recent_avg = np.mean([v.view_count for v in recent_you[:5]])
            your_older_avg = np.mean([v.view_count for v in recent_you[10:15]] or [your_recent_avg])
            
            if your_recent_avg > your_older_avg * 1.3:
                advantages.append(f"🔥 Growing faster: Recent videos get {(your_recent_avg/your_older_avg-1)*100:.0f}% more views")
        
        # More consistent
        your_std = np.std([v.view_count for v in your_videos]) / your_avg
        comp_std = np.std([v.view_count for v in comp_videos]) / comp_avg
        
        if your_std < comp_std * 0.8:
            advantages.append("📊 More consistent: Your views are more predictable")
        
        return advantages
    
    def _extract_keywords(self, videos: List[Video]) -> List[str]:
        """Extract common keywords from video titles."""
        words = []
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                      'of', 'with', 'by', 'from', 'is', 'it', 'this', 'that', 'my', 'i', 
                      'you', 'we', 'they', 'how', 'what', 'why', 'when', 'where'}
        
        for v in videos:
            title_words = re.findall(r'\b[a-zA-Z]{3,}\b', v.title.lower())
            words.extend([w for w in title_words if w not in stop_words])
        
        return [w for w, _ in Counter(words).most_common(50)]
    
    def _why_study_video(self, video: Video, channel_avg: float) -> str:
        """Explain why this video is worth studying."""
        ratio = video.view_count / channel_avg if channel_avg else 1
        
        if ratio > 5:
            return f"🚀 Viral hit ({ratio:.0f}x their average)"
        elif ratio > 2:
            return f"📈 Strong performer ({ratio:.1f}x average)"
        else:
            return "💎 Consistent performer"
    
    def _generate_takeaways(
        self,
        metrics: List[MetricComparison],
        diffs: List[StrategyDifference],
        opportunities: List[OpportunityGap],
        comp_strengths: List[str],
        your_advantages: List[str]
    ) -> List[str]:
        """Generate key takeaways from the analysis."""
        takeaways = []
        
        # Biggest advantage
        if your_advantages:
            takeaways.append(f"✅ Your edge: {your_advantages[0]}")
        
        # Biggest opportunity
        high_impact_opps = [o for o in opportunities if o.potential_impact]
        if high_impact_opps:
            takeaways.append(f"🎯 Top opportunity: {high_impact_opps[0].action_item}")
        
        # What to learn
        if comp_strengths:
            takeaways.append(f"📚 Learn from them: {comp_strengths[0].split(':')[0]}")
        
        # Key metric difference
        wins = [m for m in metrics if m.winner == "you"]
        losses = [m for m in metrics if m.winner == "competitor"]
        
        if wins:
            takeaways.append(f"📊 You're winning on: {wins[0].metric_name}")
        if losses:
            takeaways.append(f"📈 Room to improve: {losses[0].metric_name}")
        
        # Strategic change to test
        high_impact_diffs = [d for d in diffs if d.impact == "high"]
        if high_impact_diffs:
            takeaways.append(f"🧪 Test this: {high_impact_diffs[0].recommendation}")
        
        return takeaways[:5]


def compare_channels(your_channel_id: str, competitor_channel_id: str) -> Optional[CompetitorReport]:
    """
    Convenience function to compare two channels.
    
    Args:
        your_channel_id: Your channel ID
        competitor_channel_id: Competitor channel ID
        
    Returns:
        CompetitorReport or None
    """
    analyzer = CompetitorAnalyzer()
    return analyzer.compare(your_channel_id, competitor_channel_id)




