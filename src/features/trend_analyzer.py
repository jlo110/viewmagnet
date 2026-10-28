"""
Google Trends integration for topic timing analysis.

Helps creators understand if their topic is:
- Trending up (good time to post)
- Stable (consistent interest)
- Trending down (might be late)
- Seasonal (best times of year)
"""

import re
import time
from dataclasses import dataclass
from typing import List, Dict
from datetime import datetime

try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False


@dataclass
class TrendResult:
    """Result of a trend analysis."""
    keyword: str
    trend_direction: str  # "rising", "stable", "falling", "breakout"
    change_7d: float  # Percentage change over 7 days
    change_30d: float  # Percentage change over 30 days
    current_interest: int  # 0-100 relative interest
    peak_interest: int  # Peak in last 90 days
    is_seasonal: bool
    best_months: List[str]  # Best months if seasonal
    related_rising: List[str]  # Related rising queries
    recommendation: str  # Timing recommendation


@dataclass
class TopicTiming:
    """Timing recommendation for a topic."""
    topic: str
    should_post_now: bool
    urgency: str  # "now", "soon", "wait", "anytime"
    reason: str
    trend_score: float  # -1 to 1 (negative = falling, positive = rising)


class TrendAnalyzer:
    """Analyzes Google Trends data for video topic timing."""
    
    def __init__(self, geo: str = "US", language: str = "en-US"):
        """
        Initialize the trend analyzer.
        
        Args:
            geo: Geographic region (default: US)
            language: Language for trends (default: en-US)
        """
        if not PYTRENDS_AVAILABLE:
            raise ImportError("pytrends not installed. Run: pip install pytrends")
        
        self.geo = geo
        self.language = language
        self.pytrends = TrendReq(hl=language, tz=360)
    
    def analyze_topic(self, topic: str, compare_to: List[str] = None) -> TrendResult:
        """
        Analyze trend data for a topic.
        
        Args:
            topic: The topic/keyword to analyze
            compare_to: Optional list of topics to compare against
            
        Returns:
            TrendResult with trend analysis
        """
        keywords = [topic]
        if compare_to:
            keywords.extend(compare_to[:4])  # Max 5 keywords
        
        try:
            # Get interest over time (last 90 days)
            self.pytrends.build_payload(keywords, timeframe='today 3-m', geo=self.geo)
            interest_df = self.pytrends.interest_over_time()
            
            if interest_df.empty:
                return self._empty_result(topic, "No data available")
            
            # Get the main topic's data
            topic_data = interest_df[topic]
            
            # Calculate metrics
            current = topic_data.iloc[-1]
            week_ago = topic_data.iloc[-8] if len(topic_data) > 7 else topic_data.iloc[0]
            month_ago = topic_data.iloc[-31] if len(topic_data) > 30 else topic_data.iloc[0]
            peak = topic_data.max()
            
            # Calculate changes — cast to Python floats so the response is
            # JSON-serialisable (numpy.float64 is fine for math but FastAPI's
            # jsonable_encoder treats numpy scalars as opaque).
            change_7d = float(((current - week_ago) / max(week_ago, 1)) * 100)
            change_30d = float(((current - month_ago) / max(month_ago, 1)) * 100)

            # Determine trend direction
            if change_7d > 50:
                trend_direction = "breakout"
            elif change_7d > 10:
                trend_direction = "rising"
            elif change_7d < -20:
                trend_direction = "falling"
            else:
                trend_direction = "stable"

            # Check seasonality (simple variance check) — bool() to drop the
            # numpy.bool_ wrapper that the comparison returns.
            variance = topic_data.std() / max(topic_data.mean(), 1)
            is_seasonal = bool(variance > 0.3)
            
            # Find best months if seasonal
            best_months = []
            if is_seasonal:
                monthly = topic_data.groupby(topic_data.index.month).mean()
                top_months = monthly.nlargest(3).index.tolist()
                month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                best_months = [month_names[m-1] for m in top_months]
            
            # Get related rising queries
            related_rising = []
            try:
                self.pytrends.build_payload([topic], timeframe='today 3-m', geo=self.geo)
                related = self.pytrends.related_queries()
                if topic in related and related[topic]['rising'] is not None:
                    rising_df = related[topic]['rising']
                    related_rising = rising_df['query'].head(5).tolist()
            except:
                pass
            
            # Generate recommendation
            recommendation = self._generate_recommendation(
                trend_direction, change_7d, change_30d, current, peak, is_seasonal, best_months
            )
            
            return TrendResult(
                keyword=topic,
                trend_direction=trend_direction,
                change_7d=change_7d,
                change_30d=change_30d,
                current_interest=int(current),
                peak_interest=int(peak),
                is_seasonal=is_seasonal,
                best_months=best_months,
                related_rising=related_rising,
                recommendation=recommendation
            )
            
        except Exception as e:
            return self._empty_result(topic, f"Error: {str(e)}")
    
    def get_topic_timing(self, title: str) -> TopicTiming:
        """
        Get timing recommendation based on video title.
        
        Args:
            title: Video title to extract topic from
            
        Returns:
            TopicTiming with recommendation
        """
        # Extract main topic from title
        topic = self._extract_topic(title)
        
        if not topic:
            return TopicTiming(
                topic=title[:30],
                should_post_now=True,
                urgency="anytime",
                reason="Could not extract clear topic",
                trend_score=0.0
            )
        
        result = self.analyze_topic(topic)
        
        # Calculate trend score (-1 to 1)
        trend_score = min(1.0, max(-1.0, result.change_7d / 50))
        
        # Determine urgency
        if result.trend_direction == "breakout":
            urgency = "now"
            should_post = True
            reason = f"'{topic}' is breaking out (+{result.change_7d:.0f}% this week)! Post ASAP."
        elif result.trend_direction == "rising":
            urgency = "soon"
            should_post = True
            reason = f"'{topic}' is trending up (+{result.change_7d:.0f}%). Good time to post."
        elif result.trend_direction == "falling":
            urgency = "wait"
            should_post = False
            reason = f"'{topic}' is declining ({result.change_7d:.0f}%). Consider a different angle."
        else:
            urgency = "anytime"
            should_post = True
            reason = f"'{topic}' has stable interest. Post when ready."
        
        return TopicTiming(
            topic=topic,
            should_post_now=should_post,
            urgency=urgency,
            reason=reason,
            trend_score=trend_score
        )
    
    def compare_topics(self, topics: List[str]) -> Dict[str, TrendResult]:
        """
        Compare multiple topics and rank by trend potential.
        
        Args:
            topics: List of topics to compare
            
        Returns:
            Dict of topic -> TrendResult, sorted by potential
        """
        results = {}
        
        for topic in topics[:5]:  # Limit to 5
            try:
                result = self.analyze_topic(topic)
                results[topic] = result
                time.sleep(1)  # Rate limiting
            except:
                continue
        
        # Sort by trend score
        sorted_results = dict(sorted(
            results.items(),
            key=lambda x: x[1].change_7d,
            reverse=True
        ))
        
        return sorted_results
    
    def _extract_topic(self, title: str) -> str:
        """Extract main topic from title."""
        # Remove common YouTube title patterns
        title = re.sub(r'\|.*$', '', title)  # Remove pipe sections
        title = re.sub(r'\[.*?\]', '', title)  # Remove brackets
        title = re.sub(r'\(.*?\)', '', title)  # Remove parentheses
        title = re.sub(r'#\w+', '', title)  # Remove hashtags
        title = re.sub(r'\d+', '', title)  # Remove numbers
        
        # Common words to remove
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                     'i', 'you', 'we', 'they', 'my', 'your', 'our', 'this', 'that',
                     'how', 'why', 'what', 'when', 'where', 'who', 'which',
                     'to', 'for', 'of', 'in', 'on', 'at', 'with', 'about',
                     'new', 'best', 'top', 'first', 'last', 'full', 'official'}
        
        words = title.lower().split()
        words = [w for w in words if w not in stop_words and len(w) > 2]
        
        # Take first 2-3 meaningful words
        topic = ' '.join(words[:3]).strip()
        
        return topic if topic else None
    
    def _generate_recommendation(
        self, direction: str, change_7d: float, change_30d: float,
        current: int, peak: int, is_seasonal: bool, best_months: List[str]
    ) -> str:
        """Generate timing recommendation."""
        
        if direction == "breakout":
            return f"🔥 BREAKOUT! Topic is exploding (+{change_7d:.0f}%). Post immediately to catch the wave."
        
        elif direction == "rising":
            return f"📈 Rising trend (+{change_7d:.0f}%). Good timing - post within the next few days."
        
        elif direction == "falling":
            if change_30d > 0:
                return "📉 Cooling off from recent peak. Consider a fresh angle or wait for next surge."
            else:
                return f"⬇️ Declining interest ({change_7d:.0f}%). May want to pivot or wait."
        
        else:  # stable
            if is_seasonal and best_months:
                current_month = datetime.now().strftime('%b')
                if current_month in best_months:
                    return f"📊 Stable topic, and {current_month} is a peak month. Good to post!"
                else:
                    return f"📊 Stable topic. Peak months are {', '.join(best_months)}."
            else:
                return "📊 Consistent interest. Post whenever you're ready."
    
    def _empty_result(self, topic: str, reason: str) -> TrendResult:
        """Return empty result when data unavailable."""
        return TrendResult(
            keyword=topic,
            trend_direction="unknown",
            change_7d=0.0,
            change_30d=0.0,
            current_interest=0,
            peak_interest=0,
            is_seasonal=False,
            best_months=[],
            related_rising=[],
            recommendation=f"⚠️ {reason}"
        )


def analyze_video_timing(title: str, geo: str = "US") -> TopicTiming:
    """
    Convenience function to analyze timing for a video title.
    
    Args:
        title: Video title
        geo: Geographic region
        
    Returns:
        TopicTiming recommendation
    """
    analyzer = TrendAnalyzer(geo=geo)
    return analyzer.get_topic_timing(title)


def get_trend_data(topic: str, geo: str = "US") -> TrendResult:
    """
    Convenience function to get trend data for a topic.
    
    Args:
        topic: Topic keyword
        geo: Geographic region
        
    Returns:
        TrendResult with analysis
    """
    analyzer = TrendAnalyzer(geo=geo)
    return analyzer.analyze_topic(topic)

