"""
Personalized Recommendation Engine

Generates truly personalized, data-driven recommendations by:
1. Comparing user's video to niche-specific benchmarks
2. Finding similar successful videos as proof points
3. Quantifying the impact of each recommendation
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import logging

from src.ml.niche_benchmarks import get_hierarchical_calculator, NicheBenchmark
from src.ml.similar_video_finder import get_similar_finder, SimilarVideo
from src.ml.improved_predictor_v2 import ImprovedPredictor

logger = logging.getLogger(__name__)


@dataclass
class PersonalizedRecommendation:
    """A single personalized recommendation."""
    priority: int  # 1 = highest priority
    category: str  # 'thumbnail', 'title', 'general'
    title: str  # Short title
    explanation: str  # Why this matters
    user_value: str  # What the user currently has
    benchmark_avg: str  # Category average
    benchmark_top10: str  # Top 10% value
    estimated_impact: str  # e.g., "+15-25% CTR"
    action: str  # What to do


@dataclass
class AnalysisResult:
    """Complete analysis result with personalized recommendations."""
    # Prediction
    prediction: str  # "ABOVE AVERAGE" or "BELOW AVERAGE"
    score: int  # 0-100
    confidence: float  # 0-100%
    expected_views: int
    
    # Comparison table
    comparisons: Dict[str, dict] = field(default_factory=dict)
    
    # Recommendations (prioritized)
    recommendations: List[PersonalizedRecommendation] = field(default_factory=list)
    
    # Similar successful videos
    similar_videos: List[SimilarVideo] = field(default_factory=list)
    
    # Niche info (hierarchical)
    category: str = ""
    category_video_count: int = 0
    micro_niche: Optional[str] = None
    micro_niche_video_count: int = 0
    used_micro_niche: bool = False
    benchmark_level: str = "category"  # "category" or "micro-niche"


class PersonalizedRecommender:
    """Generates personalized, data-driven recommendations."""
    
    def __init__(self):
        self.predictor = ImprovedPredictor()
        self.benchmark_calc = get_hierarchical_calculator()
        self.similar_finder = get_similar_finder()
    
    def analyze(
        self,
        title: str,
        thumbnail_features: dict,
        channel_category: str,
        channel_subscribers: int = 10000,
        channel_size_tier: str = "small",
        channel_hit_rate: float = 0.5,
        channel_avg_views: float = 5000,
        channel_niche_id: Optional[int] = None,
    ) -> AnalysisResult:
        """
        Perform complete personalized analysis.
        
        Args:
            title: Video title
            thumbnail_features: Dict with has_face, brightness, saturation, has_text
            channel_category: e.g., 'gaming', 'education_howto', 'entertainment_vlogs'
            channel_subscribers: Number of subscribers
            channel_size_tier: nano/micro/small/medium/large/mega/top
            channel_hit_rate: Historical success rate (0-1)
            channel_avg_views: Channel's average views per video
            channel_niche_id: Optional micro-niche ID (uses hierarchical fallback)
        
        Returns:
            AnalysisResult with predictions, comparisons, and recommendations
        """
        # Load predictor if needed
        self.predictor.load_or_train()
        
        # 1. Get base prediction
        pred_result = self.predictor.predict(
            title=title,
            thumbnail_features=thumbnail_features,
            channel_subscribers=channel_subscribers,
            channel_size_tier=channel_size_tier,
            channel_hit_rate=channel_hit_rate,
            channel_avg_views=channel_avg_views,
        )
        
        # 2. Get benchmark with hierarchical fallback
        benchmark_result = self.benchmark_calc.get_benchmark(
            category=channel_category, 
            niche_id=channel_niche_id
        )
        benchmark = benchmark_result.benchmark
        
        # 3. Build user metrics for comparison
        user_metrics = {
            'has_face': thumbnail_features.get('has_face', False),
            'has_text': thumbnail_features.get('has_text', False),
            'brightness': thumbnail_features.get('brightness', 0.5),
            'saturation': thumbnail_features.get('saturation', 0.5),
            'title_length': len(title),
            'title_words': len(title.split()),
            'has_number': any(c.isdigit() for c in title),
            'has_question': '?' in title,
        }
        
        # 4. Compare to benchmark
        comparisons = self.benchmark_calc.compare_to_benchmark(benchmark, user_metrics)
        
        # 5. Find similar successful videos
        similar_videos = self.similar_finder.find_similar(title, channel_category, top_k=3)
        
        # 6. Generate personalized recommendations
        recommendations = self._generate_recommendations(
            user_metrics, 
            benchmark, 
            comparisons, 
            similar_videos,
            benchmark.name  # Use actual benchmark name (could be micro-niche)
        )
        
        # 7. Calculate expected views
        expected_views = int(channel_avg_views * pred_result.probability * 2)
        
        return AnalysisResult(
            prediction=pred_result.prediction,
            score=int(pred_result.probability * 100),
            confidence=pred_result.confidence,
            expected_views=expected_views,
            comparisons=comparisons,
            recommendations=recommendations,
            similar_videos=similar_videos,
            category=channel_category,
            category_video_count=self.benchmark_calc.category_benchmarks.get(channel_category, NicheBenchmark(name="", level="", video_count=0)).video_count,
            micro_niche=benchmark_result.micro_niche_name,
            micro_niche_video_count=benchmark.video_count if benchmark.level == 'micro-niche' else 0,
            used_micro_niche=not benchmark_result.used_fallback and benchmark.level == 'micro-niche',
            benchmark_level=benchmark.level,
        )
    
    def _generate_recommendations(
        self,
        user_metrics: dict,
        benchmark: Optional[NicheBenchmark],
        comparisons: dict,
        similar_videos: List[SimilarVideo],
        category: str,
    ) -> List[PersonalizedRecommendation]:
        """Generate prioritized, personalized recommendations."""
        
        recommendations = []
        priority = 1
        
        if not benchmark:
            # Fallback generic recommendations
            return self._generate_generic_recommendations(user_metrics)
        
        # 1. Title Length - HIGH IMPACT
        if comparisons.get('title_length', {}).get('gap') in ['below', 'way_below']:
            chars_needed = comparisons['title_length'].get('chars_needed', 0)
            
            # Find what similar successful videos did
            successful_titles = [v.title for v in similar_videos[:3] if v.performance_ratio > 1.5]
            example = successful_titles[0][:50] if successful_titles else "I [Action] for [Time] and [Result]"
            
            recommendations.append(PersonalizedRecommendation(
                priority=priority,
                category='title',
                title='📝 Title Too Short',
                explanation=f'In {category.replace("_", " ").title()}, longer titles perform better',
                user_value=f'{user_metrics["title_length"]} chars',
                benchmark_avg=f'{benchmark.avg_title_length:.0f} chars',
                benchmark_top10=f'{benchmark.top10_title_length:.0f} chars',
                estimated_impact='+10-20% CTR',
                action=f'Add {chars_needed}+ more characters. Try: "{example}..."',
            ))
            priority += 1
        
        # 2. Face in Thumbnail - HIGH IMPACT FOR MOST NICHES
        if not user_metrics['has_face'] and benchmark.avg_face_rate > 0.4:
            face_gap = benchmark.top10_face_rate - 0  # user has 0
            
            recommendations.append(PersonalizedRecommendation(
                priority=priority,
                category='thumbnail',
                title='👤 Add Face to Thumbnail',
                explanation=f'{category.replace("_", " ").title()} videos with faces get higher CTR',
                user_value='No face',
                benchmark_avg=f'{benchmark.avg_face_rate*100:.0f}% use faces',
                benchmark_top10=f'{benchmark.top10_face_rate*100:.0f}% use faces',
                estimated_impact=f'+{face_gap*30:.0f}% CTR',
                action='Add your reaction face or a person to the thumbnail',
            ))
            priority += 1
        
        # 3. Number in Title - MODERATE IMPACT
        if not user_metrics['has_number'] and benchmark.top10_has_number > 0.3:
            recommendations.append(PersonalizedRecommendation(
                priority=priority,
                category='title',
                title='🔢 Add Number to Title',
                explanation='Numbers create specificity and curiosity',
                user_value='No numbers',
                benchmark_avg=f'{benchmark.avg_has_number*100:.0f}% use numbers',
                benchmark_top10=f'{benchmark.top10_has_number*100:.0f}% use numbers',
                estimated_impact='+5-15% CTR',
                action='Add specifics: "5 ways...", "$1000", "in 24 hours", "100 days"',
            ))
            priority += 1
        
        # 4. Text Overlay - MODERATE IMPACT
        if not user_metrics['has_text'] and benchmark.top10_text_rate > 0.3:
            recommendations.append(PersonalizedRecommendation(
                priority=priority,
                category='thumbnail',
                title='📝 Add Text to Thumbnail',
                explanation='Text overlays help thumbnails stand out in search',
                user_value='No text',
                benchmark_avg=f'{benchmark.avg_text_rate*100:.0f}% use text',
                benchmark_top10=f'{benchmark.top10_text_rate*100:.0f}% use text',
                estimated_impact='+5-10% CTR',
                action='Add 2-4 word hook text to thumbnail',
            ))
            priority += 1
        
        # 5. Brightness - MODERATE IMPACT
        if user_metrics['brightness'] < benchmark.avg_brightness * 0.85:
            recommendations.append(PersonalizedRecommendation(
                priority=priority,
                category='thumbnail',
                title='💡 Brighten Thumbnail',
                explanation='Brighter thumbnails stand out on YouTube\'s white UI',
                user_value=f'{user_metrics["brightness"]:.2f}',
                benchmark_avg=f'{benchmark.avg_brightness:.2f}',
                benchmark_top10=f'{benchmark.top10_brightness:.2f}',
                estimated_impact='+5-10% CTR',
                action=f'Increase brightness by {(benchmark.avg_brightness - user_metrics["brightness"])*100:.0f}%',
            ))
            priority += 1
        
        # 6. Question Format - LOWER IMPACT BUT EASY
        if not user_metrics['has_question'] and benchmark.top10_has_question > 0.15:
            recommendations.append(PersonalizedRecommendation(
                priority=priority,
                category='title',
                title='❓ Try Question Format',
                explanation='Questions trigger curiosity and engagement',
                user_value='Not a question',
                benchmark_avg=f'{benchmark.avg_has_question*100:.0f}% use questions',
                benchmark_top10=f'{benchmark.top10_has_question*100:.0f}% use questions',
                estimated_impact='+3-8% CTR',
                action='Rephrase as: "What happens when...?", "Why do...?", "Can I...?"',
            ))
            priority += 1
        
        return recommendations
    
    def _generate_generic_recommendations(self, user_metrics: dict) -> List[PersonalizedRecommendation]:
        """Fallback generic recommendations when no benchmark available."""
        recommendations = []
        
        if not user_metrics['has_face']:
            recommendations.append(PersonalizedRecommendation(
                priority=1,
                category='thumbnail',
                title='👤 Add Face to Thumbnail',
                explanation='Faces generally increase click-through rate',
                user_value='No face',
                benchmark_avg='~60% of videos',
                benchmark_top10='~80% of top videos',
                estimated_impact='+15-25% CTR',
                action='Add your reaction face or a person to the thumbnail',
            ))
        
        if user_metrics['title_length'] < 40:
            recommendations.append(PersonalizedRecommendation(
                priority=2,
                category='title',
                title='📝 Make Title More Specific',
                explanation='Short generic titles underperform',
                user_value=f'{user_metrics["title_length"]} chars',
                benchmark_avg='~55 chars',
                benchmark_top10='~65 chars',
                estimated_impact='+10-20% CTR',
                action='Add specifics: numbers, timeframes, outcomes',
            ))
        
        return recommendations


def format_analysis_for_display(result: AnalysisResult) -> str:
    """Format analysis result for console display."""
    lines = []
    
    lines.append("╔" + "═"*68 + "╗")
    lines.append("║" + " "*20 + "🎬 ViewMagnet Analysis" + " "*28 + "║")
    lines.append("║" + " "*12 + "(Personalized Recommendations)" + " "*24 + "║")
    lines.append("╠" + "═"*68 + "╣")
    lines.append("║" + " "*68 + "║")
    
    # Prediction
    emoji = "🟢" if result.prediction == "ABOVE AVERAGE" else "🔴"
    lines.append(f"║  {emoji} PREDICTION: {result.prediction} (Score: {result.score}/100)" + " "*(27-len(result.prediction)) + "║")
    lines.append(f"║  📊 Expected Views: ~{result.expected_views:,}" + " "*(44-len(f"{result.expected_views:,}")) + "║")
    lines.append(f"║  🎯 Confidence: {result.confidence:.0f}%" + " "*(50) + "║")
    lines.append("║" + " "*68 + "║")
    
    # Comparison table
    if result.comparisons:
        lines.append("╠" + "═"*68 + "╣")
        
        # Show benchmark source (micro-niche or category)
        if result.used_micro_niche and result.micro_niche:
            niche_display = result.micro_niche[:35].upper().replace('_', ' ')
            lines.append(f"║  📊 HOW YOU COMPARE TO {niche_display}:" + " "*(30-len(niche_display)) + "║")
            lines.append(f"║     (micro-niche: {result.micro_niche_video_count:,} videos)" + " "*35 + "║")
        else:
            lines.append(f"║  📊 HOW YOU COMPARE TO {result.category.upper().replace('_', ' ')}:" + " "*(30-len(result.category)) + "║")
        lines.append("║" + " "*68 + "║")
        lines.append("║" + " "*20 + "You" + " "*10 + "Category Avg" + " "*6 + "Top 10%" + " "*9 + "║")
        lines.append("║  " + "─"*64 + "  ║")
        
        for key, comp in result.comparisons.items():
            label = key.replace('_', ' ').title()[:20]
            user_val = str(comp.get('user', '-'))[:8]
            avg_val = str(comp.get('category_avg', '-'))[:12]
            top_val = str(comp.get('top_10', '-'))[:10]
            gap_icon = "❌" if comp.get('gap') in ['below', 'way_below'] else "✅"
            
            line = f"║  {gap_icon} {label:<16} {user_val:>8}    {avg_val:>12}    {top_val:>10}  ║"
            lines.append(line)
        
        lines.append("║" + " "*68 + "║")
    
    # Recommendations
    if result.recommendations:
        lines.append("╠" + "═"*68 + "╣")
        lines.append("║  🎯 PERSONALIZED RECOMMENDATIONS:" + " "*33 + "║")
        lines.append("║" + " "*68 + "║")
        
        for rec in result.recommendations[:4]:
            lines.append(f"║  {rec.priority}. {rec.title}" + " "*(55-len(rec.title)) + "║")
            lines.append(f"║     • {rec.explanation[:55]}" + " "*(55-len(rec.explanation[:55])) + "  ║")
            lines.append(f"║     • You: {rec.user_value} → Top 10%: {rec.benchmark_top10}" + " "*(35-len(rec.user_value)-len(rec.benchmark_top10)) + "║")
            lines.append(f"║     • Impact: {rec.estimated_impact}" + " "*(51-len(rec.estimated_impact)) + "║")
            lines.append(f"║     → {rec.action[:58]}" + " "*(58-len(rec.action[:58])) + "  ║")
            lines.append("║" + " "*68 + "║")
    
    # Similar videos
    if result.similar_videos:
        lines.append("╠" + "═"*68 + "╣")
        lines.append("║  🏆 SIMILAR SUCCESSFUL VIDEOS:" + " "*36 + "║")
        lines.append("║" + " "*68 + "║")
        
        for video in result.similar_videos[:2]:
            title_display = video.title[:45] + "..." if len(video.title) > 45 else video.title
            lines.append(f"║  \"{title_display}\"" + " "*(55-len(title_display)) + "║")
            lines.append(f"║     {video.view_count:,} views ({video.performance_ratio:.1f}x channel avg)" + " "*(40-len(f"{video.view_count:,}")) + "║")
            face = "✅" if video.has_face else "❌"
            text = "✅" if video.has_text else "❌"
            lines.append(f"║     Face: {face}  Text: {text}  Title: {video.title_length} chars" + " "*24 + "║")
            lines.append("║" + " "*68 + "║")
    
    lines.append("╚" + "═"*68 + "╝")
    
    return "\n".join(lines)


# Demo function
def demo():
    """Demo the personalized recommender."""
    recommender = PersonalizedRecommender()
    
    print("\n" + "="*70)
    print("🎬 PERSONALIZED RECOMMENDER DEMO")
    print("="*70)
    
    # Test case: Gaming channel with poor video
    result = recommender.analyze(
        title="gaming stream",
        thumbnail_features={
            'has_face': False,
            'brightness': 0.3,
            'saturation': 0.5,
            'has_text': False,
        },
        channel_category='gaming',
        channel_subscribers=2500,
        channel_size_tier='nano',
        channel_hit_rate=0.2,
        channel_avg_views=300,
    )
    
    print(format_analysis_for_display(result))


if __name__ == "__main__":
    demo()

