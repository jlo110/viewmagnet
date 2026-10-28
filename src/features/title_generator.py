"""
Data-Driven Title Generator

Generates optimized title alternatives based on:
1. YOUR niche-specific patterns (what ACTUALLY correlates with performance)
2. Counter-intuitive findings (what works HERE vs generic advice)
3. Successful title templates extracted from YOUR data
4. Power words that boost performance in THIS niche

NOT generic "add numbers" advice - shows when generic advice is WRONG.
"""
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import re
import structlog
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from src.database.models import Video, Channel, VideoFeatures
from src.features.llm_analyzer import LLMAnalyzer
from src.features.niche_patterns import NichePatternDiscovery, NichePatterns

logger = structlog.get_logger()


@dataclass
class TitleSuggestion:
    """A suggested title with data-driven reasoning."""
    title: str
    reasoning: str  # Why this should work based on DATA
    data_basis: str  # Which specific data point supports this
    predicted_improvement: str  # low, medium, high
    features_changed: List[str]


@dataclass
class TitleGeneratorResult:
    """Result of data-driven title generation."""
    original_title: str
    original_score: float
    
    # Data-driven suggestions
    suggestions: List[TitleSuggestion]
    
    # The data that drove these suggestions
    niche_benchmarks: Dict[str, Any]  # What works in this niche
    successful_examples: List[str]  # Real titles that worked
    
    # Feature analysis
    original_features: Dict[str, Any]
    benchmark_gaps: List[str]  # Where you're below top performers
    
    # NEW: Niche-specific insights
    counter_intuitive: List[str]  # What contradicts generic advice
    niche_power_words: List[str]  # Words that boost performance here
    avoid_in_niche: List[str]  # What to NOT do in this niche
    top_templates: List[str]  # Proven title structures


class TitleGenerator:
    """
    Generate optimized titles based on YOUR DATA.
    
    The ML model identifies what features matter.
    The benchmarks show what top performers do.
    This generator creates titles that match those patterns.
    """
    
    def __init__(self, session: Optional[Session] = None):
        self.session = session
        self.llm = LLMAnalyzer()
    
    def generate(
        self,
        original_title: str,
        category: str,
        benchmark_comparisons: Dict[str, dict] = None,
        shap_values: Dict[str, float] = None,
        channel_name: Optional[str] = None,
        niche_id: Optional[int] = None,
        count: int = 5
    ) -> TitleGeneratorResult:
        """
        Generate data-driven title alternatives.
        
        Args:
            original_title: Current video title
            category: Video category (gaming, tech, etc.)
            benchmark_comparisons: From personalized_recommender (how user compares to niche)
            shap_values: From ML model (which features matter)
            channel_name: Optional channel context
            niche_id: Optional niche for micro-niche benchmarks
            count: Number of suggestions
            
        Returns:
            TitleGeneratorResult with data-driven suggestions
        """
        # Discover niche-specific patterns (counter-intuitive findings, power words, etc.)
        niche_patterns = None
        if self.session:
            pattern_discovery = NichePatternDiscovery(self.session)
            niche_patterns = pattern_discovery.discover_patterns(category, niche_id)
        
        # Get niche data from database
        niche_benchmarks = self._get_niche_title_benchmarks(category, niche_id)
        successful_examples = self._get_successful_titles(category, niche_id, limit=15)
        
        # Analyze original title
        original_features = self._analyze_title(original_title)
        original_score = self._calculate_score(original_features, niche_benchmarks)
        
        # Find gaps vs benchmarks
        benchmark_gaps = self._identify_gaps(original_features, niche_benchmarks)
        
        # Generate suggestions based on NICHE-SPECIFIC patterns
        suggestions = self._generate_from_patterns(
            original_title, original_features,
            niche_patterns, successful_examples, count
        )
        
        # Extract niche-specific insights for the result
        counter_intuitive = []
        niche_power_words = []
        avoid_in_niche = []
        top_templates = []
        
        if niche_patterns:
            counter_intuitive = [ci.insight for ci in niche_patterns.counter_intuitive[:3]]
            niche_power_words = [w for w, _ in niche_patterns.power_words[:10]]
            avoid_in_niche = niche_patterns.avoid_patterns[:5]
            top_templates = [t.pattern for t in niche_patterns.title_templates[:5]]
        
        return TitleGeneratorResult(
            original_title=original_title,
            original_score=original_score,
            suggestions=suggestions,
            niche_benchmarks=niche_benchmarks,
            successful_examples=successful_examples,
            original_features=original_features,
            benchmark_gaps=benchmark_gaps,
            counter_intuitive=counter_intuitive,
            niche_power_words=niche_power_words,
            avoid_in_niche=avoid_in_niche,
            top_templates=top_templates
        )
    
    def _get_niche_title_benchmarks(self, category: str, niche_id: Optional[int]) -> Dict[str, Any]:
        """Get what actually works for titles in this niche."""
        benchmarks = {
            "avg_length": 50,
            "top10_length": 65,
            "avg_words": 8,
            "top10_words": 10,
            "number_rate": 0.35,
            "top10_number_rate": 0.55,
            "question_rate": 0.15,
            "top10_question_rate": 0.25,
            "exclamation_rate": 0.10,
            "top_hook_types": ["how_to", "listicle", "question"],
            "top_patterns": [],
            "video_count": 0
        }
        
        if not self.session:
            return benchmarks
        
        try:
            from sqlalchemy import Integer
            
            # Query high-performing videos in this niche
            query = self.session.query(
                func.avg(VideoFeatures.title_char_length),
                func.avg(VideoFeatures.title_word_count),
                func.sum(VideoFeatures.title_has_number.cast(Integer)),
                func.sum(VideoFeatures.title_has_question.cast(Integer)),
                func.sum(VideoFeatures.title_has_exclamation.cast(Integer)),
                func.count(VideoFeatures.id)
            ).join(
                Video, VideoFeatures.video_id == Video.video_id
            ).join(
                Channel, Video.channel_id == Channel.channel_id
            ).filter(
                Channel.primary_category == category,
                Video.view_count > 0
            )
            
            if niche_id:
                query = query.filter(Channel.niche_id == niche_id)
            
            stats = query.first()
            
            if stats and stats[5] > 0:
                total = stats[5]
                benchmarks["avg_length"] = float(stats[0] or 50)
                benchmarks["avg_words"] = float(stats[1] or 8)
                benchmarks["number_rate"] = (stats[2] or 0) / total
                benchmarks["question_rate"] = (stats[3] or 0) / total
                benchmarks["exclamation_rate"] = (stats[4] or 0) / total
                benchmarks["video_count"] = total
            
            # Get top 10% benchmarks (high performers)
            top_query = self.session.query(
                func.avg(VideoFeatures.title_char_length),
                func.avg(VideoFeatures.title_word_count),
                func.sum(VideoFeatures.title_has_number.cast(Integer)),
                func.sum(VideoFeatures.title_has_question.cast(Integer)),
                func.count(VideoFeatures.id)
            ).join(
                Video, VideoFeatures.video_id == Video.video_id
            ).join(
                Channel, Video.channel_id == Channel.channel_id
            ).filter(
                Channel.primary_category == category,
                Video.performance_ratio > 1.5  # Top performers
            )
            
            if niche_id:
                top_query = top_query.filter(Channel.niche_id == niche_id)
            
            top_stats = top_query.first()
            
            if top_stats and top_stats[4] > 0:
                top_total = top_stats[4]
                benchmarks["top10_length"] = float(top_stats[0] or 65)
                benchmarks["top10_words"] = float(top_stats[1] or 10)
                benchmarks["top10_number_rate"] = (top_stats[2] or 0) / top_total
                benchmarks["top10_question_rate"] = (top_stats[3] or 0) / top_total
            
            # Get most common hook types among top performers
            hook_counts = self.session.query(
                VideoFeatures.title_hook_type,
                func.count(VideoFeatures.id)
            ).join(
                Video, VideoFeatures.video_id == Video.video_id
            ).join(
                Channel, Video.channel_id == Channel.channel_id
            ).filter(
                Channel.primary_category == category,
                Video.performance_ratio > 1.5,
                VideoFeatures.title_hook_type.isnot(None)
            ).group_by(
                VideoFeatures.title_hook_type
            ).order_by(
                desc(func.count(VideoFeatures.id))
            ).limit(5).all()
            
            if hook_counts:
                benchmarks["top_hook_types"] = [h[0] for h in hook_counts]
                
        except Exception as e:
            logger.error(f"Error getting niche benchmarks: {e}")
        
        return benchmarks
    
    def _get_successful_titles(self, category: str, niche_id: Optional[int], limit: int = 15) -> List[str]:
        """Get actual successful titles from the database."""
        if not self.session:
            return []
        
        try:
            query = self.session.query(Video.title).join(
                Channel, Video.channel_id == Channel.channel_id
            ).filter(
                Channel.primary_category == category,
                Video.performance_ratio > 1.5,  # Outperformed channel average
                Video.view_count > 10000
            )
            
            if niche_id:
                query = query.filter(Channel.niche_id == niche_id)
            
            results = query.order_by(desc(Video.performance_ratio)).limit(limit).all()
            return [r[0] for r in results]
            
        except Exception as e:
            logger.error(f"Error getting successful titles: {e}")
            return []
    
    def _analyze_title(self, title: str) -> Dict[str, Any]:
        """Analyze title features."""
        return {
            "length": len(title),
            "word_count": len(title.split()),
            "has_number": bool(re.search(r'\d', title)),
            "has_question": '?' in title,
            "has_exclamation": '!' in title,
            "has_brackets": bool(re.search(r'[\[\]\(\)]', title)),
            "caps_ratio": sum(1 for c in title if c.isupper()) / max(len(title), 1),
            "hook_type": self._detect_hook_type(title)
        }
    
    def _detect_hook_type(self, title: str) -> str:
        """Detect hook type in title."""
        title_lower = title.lower()
        
        if re.search(r'^how\s+(to|i)\b', title_lower):
            return "how_to"
        if title_lower[0].isdigit() or re.search(r'^\d+\s+\w+', title_lower):
            return "listicle"
        if '?' in title:
            return "question"
        if any(w in title_lower for w in ['vs', 'versus', 'challenge', 'battle']):
            return "challenge"
        if any(w in title_lower for w in ['react', 'reaction', 'responding']):
            return "reaction"
        if any(w in title_lower for w in ['truth', 'secret', 'reveal', 'finally']):
            return "reveal"
        if any(w in title_lower for w in ['review', 'honest', 'testing', 'tried']):
            return "review"
        if any(w in title_lower for w in ['story', 'happened', 'experience']):
            return "story"
        
        return "statement"
    
    def _calculate_score(self, features: Dict[str, Any], benchmarks: Dict[str, Any]) -> float:
        """Calculate title score based on how well it matches niche benchmarks."""
        score = 50.0
        
        # Length (closer to top10 = better)
        target_length = benchmarks.get("top10_length", 65)
        length_diff = abs(features["length"] - target_length)
        if length_diff < 10:
            score += 15
        elif length_diff < 20:
            score += 5
        else:
            score -= 10
        
        # Word count
        target_words = benchmarks.get("top10_words", 10)
        word_diff = abs(features["word_count"] - target_words)
        if word_diff < 3:
            score += 10
        
        # Number usage (if common in niche)
        if features["has_number"] and benchmarks.get("top10_number_rate", 0) > 0.3:
            score += 10
        elif not features["has_number"] and benchmarks.get("top10_number_rate", 0) > 0.4:
            score -= 5
        
        # Question usage
        if features["has_question"] and benchmarks.get("top10_question_rate", 0) > 0.15:
            score += 5
        
        # Hook type
        if features["hook_type"] in benchmarks.get("top_hook_types", []):
            score += 10
        elif features["hook_type"] == "statement":
            score -= 5
        
        return min(100, max(0, score))
    
    def _identify_gaps(self, features: Dict[str, Any], benchmarks: Dict[str, Any]) -> List[str]:
        """Identify where user's title is below top performers."""
        gaps = []
        
        if features["length"] < benchmarks.get("top10_length", 65) * 0.7:
            gaps.append(f"Title too short: {features['length']} chars vs {benchmarks.get('top10_length', 65):.0f} for top 10%")
        
        if not features["has_number"] and benchmarks.get("top10_number_rate", 0) > 0.4:
            gaps.append(f"No number: {benchmarks.get('top10_number_rate', 0)*100:.0f}% of top performers use numbers")
        
        if not features["has_question"] and benchmarks.get("top10_question_rate", 0) > 0.2:
            gaps.append(f"Not a question: {benchmarks.get('top10_question_rate', 0)*100:.0f}% of top performers use questions")
        
        if features["hook_type"] == "statement":
            top_hooks = benchmarks.get("top_hook_types", ["how_to", "listicle"])
            gaps.append(f"No hook: top performers use {', '.join(top_hooks[:3])}")
        
        return gaps
    
    def _generate_from_patterns(
        self,
        original_title: str,
        original_features: Dict[str, Any],
        niche_patterns: Optional[NichePatterns],
        successful_examples: List[str],
        count: int
    ) -> List[TitleSuggestion]:
        """Generate titles based on niche-specific patterns."""
        
        suggestions = []
        topic = self._extract_topic(original_title)
        
        if not niche_patterns:
            return self._generate_fallback(original_title, successful_examples, count)
        
        # 1. Apply best template from data
        if niche_patterns.title_templates:
            best_template = niche_patterns.title_templates[0]
            if best_template.examples:
                suggestions.append(TitleSuggestion(
                    title=f"Use template: '{best_template.pattern}'",
                    reasoning=f"This pattern averages {best_template.avg_performance:.1f}x performance in your niche",
                    data_basis=f"Based on {best_template.frequency} videos with this pattern",
                    predicted_improvement="high",
                    features_changed=["template"]
                ))
                # Show an example
                suggestions.append(TitleSuggestion(
                    title=f"Example: {best_template.examples[0][:60]}...",
                    reasoning="Real title that used this pattern successfully",
                    data_basis="From your database",
                    predicted_improvement="high",
                    features_changed=["example"]
                ))
        
        # 2. Apply counter-intuitive findings
        for ci in niche_patterns.counter_intuitive[:2]:
            # If user is doing something that HURTS in this niche, warn them
            if "NUMBERS HURT" in ci.insight and original_features['has_number']:
                suggestions.append(TitleSuggestion(
                    title="Remove numbers: '" + re.sub(r'\d+', '', original_title).strip() + "'",
                    reasoning=f"⚠️ {ci.insight}",
                    data_basis=ci.data_point,
                    predicted_improvement="medium",
                    features_changed=["remove_number"]
                ))
            
            if "QUESTIONS HURT" in ci.insight and original_features['has_question']:
                suggestions.append(TitleSuggestion(
                    title=f"Remove question: '{original_title.replace('?', '')}'",
                    reasoning=f"⚠️ {ci.insight}",
                    data_basis=ci.data_point,
                    predicted_improvement="medium",
                    features_changed=["remove_question"]
                ))
            
            if "EXCLAMATION" in ci.insight and original_features['has_exclamation']:
                suggestions.append(TitleSuggestion(
                    title=f"Remove exclamation: '{original_title.replace('!', '')}'",
                    reasoning=f"⚠️ {ci.insight}",
                    data_basis=ci.data_point,
                    predicted_improvement="medium",
                    features_changed=["remove_exclamation"]
                ))
        
        # 3. Add power words from this niche
        if niche_patterns.power_words:
            top_power = [w for w, boost in niche_patterns.power_words[:5] if len(w) > 3 and boost > 0.2]
            if top_power:
                power_word = top_power[0]
                boost = dict(niche_patterns.power_words).get(power_word, 0)
                suggestions.append(TitleSuggestion(
                    title=f"Add power word: '{topic} - {power_word.title()}'",
                    reasoning=f"'{power_word}' boosts performance by +{boost*100:.0f}% in your niche",
                    data_basis=f"Power word analysis from {niche_patterns.video_count:,} videos",
                    predicted_improvement="medium",
                    features_changed=["power_word"]
                ))
        
        # 4. Use best hook type
        best_hooks = [k.replace('hook_', '') for k, v in niche_patterns.feature_correlations.items() 
                      if k.startswith('hook_') and v > 0.1]
        if best_hooks and original_features['hook_type'] not in best_hooks:
            best_hook = best_hooks[0]
            hook_boost = niche_patterns.feature_correlations.get(f'hook_{best_hook}', 0)
            
            # Generate title with best hook
            if best_hook == 'listicle':
                new_title = f"7 {topic} Tips That Actually Work"
            elif best_hook == 'how_to':
                new_title = f"How to {topic} (The Right Way)"
            elif best_hook == 'story':
                new_title = f"I Tried {topic} for 30 Days"
            elif best_hook == 'reveal':
                new_title = f"The Truth About {topic}"
            elif best_hook == 'tutorial':
                new_title = f"{topic} Tutorial - Complete Guide"
            else:
                new_title = f"{topic} - {best_hook.title()}"
            
            suggestions.append(TitleSuggestion(
                title=new_title,
                reasoning=f"'{best_hook}' format outperforms by +{hook_boost*100:.0f}% in your niche",
                data_basis=f"Hook analysis: current='{original_features['hook_type']}', best='{best_hook}'",
                predicted_improvement="high",
                features_changed=[f"hook_{best_hook}"]
            ))
        
        # 5. Warn about what to avoid
        for avoid in niche_patterns.avoid_patterns[:2]:
            suggestions.append(TitleSuggestion(
                title=f"⚠️ AVOID: {avoid}",
                reasoning="This pattern underperforms in your niche",
                data_basis=f"From {niche_patterns.video_count:,} video analysis",
                predicted_improvement="warning",
                features_changed=["warning"]
            ))
        
        # 6. Add successful examples from the niche
        if successful_examples:
            for ex in successful_examples[:2]:
                suggestions.append(TitleSuggestion(
                    title=f"Study: '{ex[:55]}...'",
                    reasoning="High-performing title in your niche - learn from its structure",
                    data_basis="Top performer from your database",
                    predicted_improvement="varies",
                    features_changed=["learn_structure"]
                ))
        
        return suggestions[:count]
    
    def _generate_fallback(
        self,
        original_title: str,
        successful_examples: List[str],
        count: int
    ) -> List[TitleSuggestion]:
        """Fallback when no niche patterns available."""
        suggestions = []
        topic = self._extract_topic(original_title)
        
        suggestions.append(TitleSuggestion(
            title=f"How to {topic} (Complete Guide)",
            reasoning="How-to format generally performs well",
            data_basis="Generic pattern",
            predicted_improvement="medium",
            features_changed=["hook_type"]
        ))
        
        if successful_examples:
            suggestions.append(TitleSuggestion(
                title=f"Study: '{successful_examples[0][:55]}...'",
                reasoning="Learn from successful titles in your category",
                data_basis="From database",
                predicted_improvement="varies",
                features_changed=["learn_structure"]
            ))
        
        return suggestions[:count]
    
    def _generate_with_llm(
        self,
        original_title: str,
        category: str,
        benchmark_comparisons: Dict[str, dict],
        successful_examples: List[str],
        shap_values: Dict[str, float],
        niche_benchmarks: Dict[str, Any],
        count: int
    ) -> List[TitleSuggestion]:
        """Generate titles using LLM but based on YOUR data."""
        
        results = self.llm.generate_model_driven_titles(
            original_title=original_title,
            category=category,
            benchmark_comparisons=benchmark_comparisons,
            similar_successful_titles=successful_examples,
            shap_values=shap_values,
            count=count
        )
        
        if not results:
            return self._generate_from_data(
                original_title, self._analyze_title(original_title),
                niche_benchmarks, successful_examples, [], count
            )
        
        suggestions = []
        for r in results:
            suggestions.append(TitleSuggestion(
                title=r.get("title", ""),
                reasoning=r.get("reasoning", ""),
                data_basis=r.get("data_basis", "niche benchmarks"),
                predicted_improvement="medium",
                features_changed=self._compare_features(
                    original_title, r.get("title", "")
                )
            ))
        
        return suggestions
    
    def _generate_from_data(
        self,
        original_title: str,
        original_features: Dict[str, Any],
        niche_benchmarks: Dict[str, Any],
        successful_examples: List[str],
        gaps: List[str],
        count: int
    ) -> List[TitleSuggestion]:
        """Generate titles based purely on database patterns."""
        
        suggestions = []
        topic = self._extract_topic(original_title)
        
        # 1. Match top performer length if too short
        if original_features["length"] < niche_benchmarks.get("top10_length", 65) * 0.8:
            target = niche_benchmarks.get("top10_length", 65)
            suggestions.append(TitleSuggestion(
                title=f"{original_title} - The Complete Guide You Need",
                reasoning=f"Top 10% in {niche_benchmarks.get('video_count', 0):,} videos average {target:.0f} chars",
                data_basis=f"benchmark: top10_length = {target:.0f}",
                predicted_improvement="medium",
                features_changed=["length"]
            ))
        
        # 2. Add number if top performers use them
        if not original_features["has_number"] and niche_benchmarks.get("top10_number_rate", 0) > 0.3:
            rate = niche_benchmarks.get("top10_number_rate", 0) * 100
            suggestions.append(TitleSuggestion(
                title=f"7 {topic} Tips That Actually Work",
                reasoning=f"{rate:.0f}% of top performers in this niche use numbers in titles",
                data_basis=f"benchmark: top10_number_rate = {rate:.0f}%",
                predicted_improvement="medium",
                features_changed=["has_number", "hook_type"]
            ))
        
        # 3. Try question format if it works in niche
        if not original_features["has_question"] and niche_benchmarks.get("top10_question_rate", 0) > 0.15:
            rate = niche_benchmarks.get("top10_question_rate", 0) * 100
            suggestions.append(TitleSuggestion(
                title=f"Why Does {topic} Work So Well?",
                reasoning=f"{rate:.0f}% of top performers use question format",
                data_basis=f"benchmark: top10_question_rate = {rate:.0f}%",
                predicted_improvement="low",
                features_changed=["has_question"]
            ))
        
        # 4. Use top hook type from niche
        top_hooks = niche_benchmarks.get("top_hook_types", [])
        if top_hooks and original_features["hook_type"] not in top_hooks:
            if "how_to" in top_hooks:
                suggestions.append(TitleSuggestion(
                    title=f"How to Master {topic} (Step by Step)",
                    reasoning="'how_to' is the #1 hook type among top performers",
                    data_basis=f"benchmark: top_hook_types = {top_hooks[:3]}",
                    predicted_improvement="medium",
                    features_changed=["hook_type"]
                ))
            elif "listicle" in top_hooks:
                suggestions.append(TitleSuggestion(
                    title=f"5 {topic} Secrets Nobody Talks About",
                    reasoning="'listicle' format dominates top performers in this niche",
                    data_basis=f"benchmark: top_hook_types = {top_hooks[:3]}",
                    predicted_improvement="medium",
                    features_changed=["hook_type", "has_number"]
                ))
        
        # 5. Learn from actual successful titles
        if successful_examples:
            # Find a pattern from a successful title
            for example in successful_examples[:3]:
                if len(example) > 30 and example != original_title:
                    suggestions.append(TitleSuggestion(
                        title=f"Pattern from: {example[:60]}",
                        reasoning="This title outperformed in your niche - study its structure",
                        data_basis="successful video in your database",
                        predicted_improvement="varies",
                        features_changed=["learn_from_success"]
                    ))
                    break
        
        return suggestions[:count]
    
    def _extract_topic(self, title: str) -> str:
        """Extract core topic from title."""
        # Remove common prefixes/suffixes
        topic = re.sub(r'^(how to|why|what|the|my|a|an)\s+', '', title.lower())
        topic = re.sub(r'[^\w\s]', '', topic)
        words = topic.split()[:4]
        return ' '.join(words).title()
    
    def _compare_features(self, original: str, new: str) -> List[str]:
        """Identify which features changed."""
        orig_f = self._analyze_title(original)
        new_f = self._analyze_title(new)
        
        changed = []
        if new_f["length"] > orig_f["length"] + 10:
            changed.append("length_increased")
        if new_f["has_number"] and not orig_f["has_number"]:
            changed.append("added_number")
        if new_f["has_question"] and not orig_f["has_question"]:
            changed.append("added_question")
        if new_f["hook_type"] != orig_f["hook_type"]:
            changed.append(f"hook_{new_f['hook_type']}")
        
        return changed if changed else ["general"]


def generate_titles(
    original_title: str,
    category: str,
    session: Optional[Session] = None,
    benchmark_comparisons: Dict[str, dict] = None,
    count: int = 5
) -> TitleGeneratorResult:
    """Convenience function for data-driven title generation."""
    generator = TitleGenerator(session)
    return generator.generate(
        original_title, category, 
        benchmark_comparisons=benchmark_comparisons,
        count=count
    )
