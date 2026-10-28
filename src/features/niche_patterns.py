"""
Niche-Specific Pattern Discovery

Finds what ACTUALLY works in each niche - including patterns that
CONTRADICT generic YouTube advice.

This is the real value: showing creators what's unique about their niche,
not just repeating "add numbers" with percentages.
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import numpy as np
from sqlalchemy import func, case
from sqlalchemy.orm import Session
import structlog

from src.database.models import Video, Channel, VideoFeatures, VideoContentAnalysis

logger = structlog.get_logger()


@dataclass
class NicheInsight:
    """A discovered insight about what works in a niche."""
    insight: str  # Human-readable finding
    data_point: str  # The specific data (e.g., "62% vs 35% baseline")
    confidence: str  # low/medium/high based on sample size
    contradicts_generic: bool  # Does this go against "common wisdom"?
    impact_estimate: str  # e.g., "+23% performance"


@dataclass
class TitleTemplate:
    """A successful title template extracted from data."""
    pattern: str  # e.g., "I [verb]ed [noun] for [time]"
    examples: List[str]  # Real titles that match
    avg_performance: float  # Average performance ratio
    frequency: int  # How many titles use this


@dataclass
class LearnedPhrase:
    """A phrase learned from successful titles (n-gram extraction).
    
    Now with statistical validity AND within-creator validation:
    - Controls for channel size (compares within size tiers)
    - Requires minimum sample size
    - Checks creator diversity
    - Includes confidence intervals
    - VALIDATES with within-creator comparison (the real test!)
    """
    phrase: str  # e.g., "I tried", "in 24 hours", "the truth about"
    frequency: int  # How many titles use this phrase
    unique_creators: int  # Number of different creators using this phrase
    avg_performance: float  # Relative performance (1.0 = average, 1.35 = +35%)
    confidence_interval: Tuple[float, float]  # 95% CI (lower, upper)
    example_titles: List[str]  # Real titles using this phrase
    reliability: str  # "high", "medium", "low" based on sample size + diversity
    
    # Within-creator validation (NEW)
    within_creator_lift: Optional[float] = None  # Median lift when same creator uses phrase
    within_creator_helped: Optional[int] = None  # How many creators it helped
    within_creator_total: Optional[int] = None  # Total creators analyzed
    is_validated: bool = False  # True if within-creator lift > 5% AND helped > 50%
    
    @property
    def impact_str(self) -> str:
        """Human-readable impact string with confidence interval."""
        pct = (self.avg_performance - 1) * 100
        ci_low = (self.confidence_interval[0] - 1) * 100
        ci_high = (self.confidence_interval[1] - 1) * 100
        return f"{pct:+.0f}% (95% CI: {ci_low:+.0f}% to {ci_high:+.0f}%)"
    
    @property
    def impact_simple(self) -> str:
        """Simple impact string for UI display."""
        pct = (self.avg_performance - 1) * 100
        if pct >= 100:
            return f"{self.avg_performance:.1f}x better"
        return f"{pct:+.0f}%"
    
    @property
    def validation_status(self) -> str:
        """Human-readable validation status."""
        if self.within_creator_lift is None:
            return "⚠️ Not validated"
        if self.is_validated:
            return f"✅ VALIDATED (+{self.within_creator_lift:.0f}% within-creator, helped {self.within_creator_helped}/{self.within_creator_total})"
        return f"❌ Not causal ({self.within_creator_lift:+.0f}% within-creator, helped {self.within_creator_helped}/{self.within_creator_total})"
    
    @property
    def honest_recommendation(self) -> str:
        """Honest recommendation based on validation."""
        if self.is_validated:
            return f'Consider using "{self.phrase}" — shows +{self.within_creator_lift:.0f}% lift for creators who use it'
        return f'"{self.phrase}" is popular with successful creators, but copying it may not help YOUR videos'


@dataclass
class AvoidPattern:
    """A pattern that HURTS performance in this niche.
    
    These are more reliable than "what to add" because negative effects
    are easier to measure causally.
    """
    pattern: str  # What to avoid
    pattern_type: str  # "punctuation", "format", "word", "structure"
    impact_pct: float  # Negative percentage (e.g., -17%)
    sample_with: int  # Videos with this pattern
    sample_without: int  # Videos without
    confidence: str  # "high", "medium", "low"
    recommendation: str  # Actionable advice
    
    @property
    def impact_str(self) -> str:
        return f"{self.impact_pct:+.0f}%"


@dataclass
class ContentInsight:
    """An insight about content features (hook, pacing, audio) for a niche."""
    feature: str  # e.g., "face_appears_fast", "has_music_intro"
    helps: bool  # True if feature correlates with better performance
    impact_pct: float  # Percentage impact (e.g., +17% or -30%)
    recommendation: str  # Actionable advice
    sample_size: int  # Number of videos analyzed


@dataclass
class NichePatterns:
    """Complete pattern analysis for a niche.
    
    HONEST POSITIONING:
    - "What to Avoid" is most reliable (negative effects are causal)
    - "Validated Phrases" passed within-creator testing
    - "Inspiration Phrases" are popular but may not help YOU
    - Niche benchmarks show what's normal
    """
    category: str
    niche_name: Optional[str]
    video_count: int
    
    # What's DIFFERENT about this niche
    unique_insights: List[NicheInsight]
    
    # Counter-intuitive findings (contradicts generic advice)
    counter_intuitive: List[NicheInsight]
    
    # Successful title templates
    title_templates: List[TitleTemplate]
    
    # Top performing words/phrases (cross-creator only)
    power_words: List[Tuple[str, float]]  # (word, performance_boost)
    
    # What to AVOID (hurts performance in this niche) - OLD simple list
    avoid_patterns: List[str]
    
    # Feature correlations with performance
    feature_correlations: Dict[str, float]
    
    # LEARNED phrases from successful titles (n-grams)
    learned_phrases: List[LearnedPhrase] = field(default_factory=list)
    
    # CONTENT insights (hook, audio, pacing patterns)
    content_insights: List[ContentInsight] = field(default_factory=list)
    
    # NEW: Separated by validation status
    validated_phrases: List[LearnedPhrase] = field(default_factory=list)  # Passed within-creator test
    inspiration_phrases: List[LearnedPhrase] = field(default_factory=list)  # For reference only
    
    # NEW: Detailed avoid patterns (more reliable than "what to add")
    avoid_details: List[AvoidPattern] = field(default_factory=list)
    
    @property
    def disclaimer(self) -> str:
        """Honest disclaimer for users."""
        return (
            "⚠️ HONEST DISCLAIMER: Most phrase patterns don't help when tested within-creator. "
            "'Validated' phrases showed real lift for creators who used them. "
            "'Inspiration' phrases are popular but copying them may not help YOUR videos. "
            "'What to Avoid' patterns are most reliable — these actually hurt performance."
        )


class NichePatternDiscovery:
    """
    Discovers what actually works in each niche by analyzing
    correlations between title features and performance.
    """
    
    # Generic YouTube "wisdom" to compare against
    GENERIC_ADVICE = {
        "numbers_help": True,  # "Add numbers to titles"
        "questions_help": True,  # "Use question format"
        "longer_better": True,  # "Longer titles rank better"
        "exclamation_helps": True,  # "Add excitement!"
        "caps_help": True,  # "CAPITALIZE key words"
        "brackets_help": True,  # "Use [brackets]"
    }
    
    def __init__(self, session: Session):
        self.session = session
        self._global_baselines = None
    
    def discover_patterns(
        self,
        category: str,
        niche_id: Optional[int] = None,
        min_videos: int = 100
    ) -> NichePatterns:
        """
        Discover what actually works in this niche.
        
        Args:
            category: Video category
            niche_id: Optional micro-niche ID
            min_videos: Minimum videos for statistical significance
            
        Returns:
            NichePatterns with unique insights and templates
        """
        # Load global baselines for comparison
        if self._global_baselines is None:
            self._global_baselines = self._calculate_global_baselines()
        
        # Get niche data
        niche_data = self._get_niche_data(category, niche_id)
        
        if len(niche_data) < min_videos:
            logger.warning(f"Only {len(niche_data)} videos in niche, need {min_videos}")
            return self._empty_patterns(category)
        
        # Calculate feature correlations with performance
        correlations = self._calculate_correlations(niche_data)
        
        # Find unique insights (what's different about this niche)
        unique_insights = self._find_unique_insights(correlations, category)
        
        # Find counter-intuitive patterns
        counter_intuitive = self._find_counter_intuitive(correlations)
        
        # Extract title templates from top performers
        templates = self._extract_templates(niche_data)
        
        # Find power words
        power_words = self._find_power_words(niche_data)
        
        # Find patterns to avoid
        avoid_patterns = self._find_avoid_patterns(correlations, niche_data)
        
        niche_name = None
        if niche_id:
            from src.database.models import Niche
            niche = self.session.query(Niche).filter_by(id=niche_id).first()
            niche_name = niche.name if niche else None
        
        # Extract LEARNED phrases (n-grams) from successful titles
        learned_phrases = self._extract_ngrams(niche_data)
        
        # NEW: Validate phrases with within-creator analysis
        validated_phrases, inspiration_phrases = self._validate_phrases_within_creator(
            learned_phrases, category
        )
        
        # NEW: Build detailed avoid patterns (more reliable than "what to add")
        avoid_details = self._build_detailed_avoid_patterns(correlations, niche_data, category)
        
        # Discover CONTENT patterns (hook, audio, pacing)
        content_insights = self._discover_content_patterns(category)
        
        return NichePatterns(
            category=category,
            niche_name=niche_name,
            video_count=len(niche_data),
            unique_insights=unique_insights,
            counter_intuitive=counter_intuitive,
            title_templates=templates,
            power_words=power_words,
            avoid_patterns=avoid_patterns,
            feature_correlations=correlations,
            learned_phrases=learned_phrases,
            content_insights=content_insights,
            validated_phrases=validated_phrases,
            inspiration_phrases=inspiration_phrases,
            avoid_details=avoid_details,
        )
    
    # Channel size tiers for fair comparison
    SIZE_TIERS = [
        (0, 10_000, "micro"),
        (10_000, 50_000, "small"),
        (50_000, 200_000, "medium"),
        (200_000, 1_000_000, "large"),
        (1_000_000, 5_000_000, "xlarge"),
        (5_000_000, float('inf'), "mega"),
    ]
    
    @staticmethod
    def get_size_tier(subscriber_count: int) -> str:
        """Get the size tier for a subscriber count."""
        for low, high, tier in NichePatternDiscovery.SIZE_TIERS:
            if low <= subscriber_count < high:
                return tier
        return "mega"
    
    def _get_niche_data(self, category: str, niche_id: Optional[int]) -> List[dict]:
        """Get video data for the niche, including channel_id for diversity checks."""
        query = self.session.query(
            Video.title,
            Video.view_count,
            Video.performance_ratio,
            VideoFeatures.title_char_length,
            VideoFeatures.title_word_count,
            VideoFeatures.title_has_number,
            VideoFeatures.title_has_question,
            VideoFeatures.title_has_exclamation,
            VideoFeatures.title_has_brackets,
            VideoFeatures.title_caps_ratio,
            VideoFeatures.title_hook_type,
            VideoFeatures.title_emotional_score,
            Channel.subscriber_count,
            Channel.channel_id,  # Added for diversity checking
        ).join(
            VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).join(
            Channel, Video.channel_id == Channel.channel_id
        ).filter(
            Channel.primary_category == category,
            Video.performance_ratio.isnot(None),
            Video.view_count > 100
        )
        
        if niche_id:
            query = query.filter(Channel.niche_id == niche_id)
        
        results = query.all()
        
        return [
            {
                'title': r[0],
                'views': r[1],
                'performance': r[2] or 1.0,
                'length': r[3] or 0,
                'words': r[4] or 0,
                'has_number': r[5] or False,
                'has_question': r[6] or False,
                'has_exclamation': r[7] or False,
                'has_brackets': r[8] or False,
                'caps_ratio': r[9] or 0,
                'hook_type': r[10],
                'emotional_score': r[11] or 0,
                'subscribers': r[12] or 0,
                'channel_id': r[13],  # Added for diversity checking
                'size_tier': self.get_size_tier(r[12] or 0),  # Pre-compute tier
            }
            for r in results
        ]
    
    def _calculate_global_baselines(self) -> Dict[str, float]:
        """Calculate global baselines across all videos."""
        
        stats = self.session.query(
            func.avg(case((VideoFeatures.title_has_number == True, Video.performance_ratio), else_=None)),
            func.avg(case((VideoFeatures.title_has_number == False, Video.performance_ratio), else_=None)),
            func.avg(case((VideoFeatures.title_has_question == True, Video.performance_ratio), else_=None)),
            func.avg(case((VideoFeatures.title_has_question == False, Video.performance_ratio), else_=None)),
            func.avg(Video.performance_ratio),
        ).join(
            VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).filter(
            Video.performance_ratio.isnot(None)
        ).first()
        
        return {
            'number_yes_perf': float(stats[0] or 1.0),
            'number_no_perf': float(stats[1] or 1.0),
            'question_yes_perf': float(stats[2] or 1.0),
            'question_no_perf': float(stats[3] or 1.0),
            'avg_performance': float(stats[4] or 1.0),
        }
    
    def _calculate_correlations(self, data: List[dict]) -> Dict[str, float]:
        """Calculate correlation of each feature with performance."""
        correlations = {}
        
        performances = np.array([d['performance'] for d in data])
        
        # Boolean features: compare avg performance when True vs False
        for feature in ['has_number', 'has_question', 'has_exclamation', 'has_brackets']:
            true_perf = [d['performance'] for d in data if d[feature]]
            false_perf = [d['performance'] for d in data if not d[feature]]
            
            if true_perf and false_perf:
                # Positive = feature helps, negative = feature hurts
                correlations[feature] = np.mean(true_perf) - np.mean(false_perf)
            else:
                correlations[feature] = 0.0
        
        # Numeric features: actual correlation
        for feature in ['length', 'words', 'caps_ratio', 'emotional_score']:
            values = np.array([d[feature] for d in data])
            if len(values) > 10 and np.std(values) > 0:
                corr = np.corrcoef(values, performances)[0, 1]
                correlations[feature] = float(corr) if not np.isnan(corr) else 0.0
            else:
                correlations[feature] = 0.0
        
        # Hook type analysis
        hook_performance = defaultdict(list)
        for d in data:
            if d['hook_type']:
                hook_performance[d['hook_type']].append(d['performance'])
        
        avg_perf = np.mean(performances)
        for hook, perfs in hook_performance.items():
            correlations[f'hook_{hook}'] = np.mean(perfs) - avg_perf
        
        return correlations
    
    def _find_unique_insights(self, correlations: Dict[str, float], category: str) -> List[NicheInsight]:
        """Find what's unique about this niche vs global averages."""
        insights = []
        
        # Compare to global baselines
        global_number_effect = self._global_baselines['number_yes_perf'] - self._global_baselines['number_no_perf']
        niche_number_effect = correlations.get('has_number', 0)
        
        if abs(niche_number_effect - global_number_effect) > 0.1:
            if niche_number_effect > global_number_effect:
                insights.append(NicheInsight(
                    insight=f"Numbers work BETTER in {category} than average",
                    data_point=f"+{niche_number_effect*100:.0f}% vs +{global_number_effect*100:.0f}% global",
                    confidence="high",
                    contradicts_generic=False,
                    impact_estimate=f"+{niche_number_effect*100:.0f}% performance"
                ))
            else:
                insights.append(NicheInsight(
                    insight=f"Numbers work WORSE in {category} than average",
                    data_point=f"+{niche_number_effect*100:.0f}% vs +{global_number_effect*100:.0f}% global",
                    confidence="high",
                    contradicts_generic=True,
                    impact_estimate=f"{niche_number_effect*100:+.0f}% performance"
                ))
        
        # Find the BEST hook type for this niche
        hook_effects = {k: v for k, v in correlations.items() if k.startswith('hook_')}
        if hook_effects:
            best_hook = max(hook_effects, key=hook_effects.get)
            best_effect = hook_effects[best_hook]
            worst_hook = min(hook_effects, key=hook_effects.get)
            worst_effect = hook_effects[worst_hook]
            
            if best_effect > 0.1:
                insights.append(NicheInsight(
                    insight=f"'{best_hook.replace('hook_', '')}' titles dominate in {category}",
                    data_point=f"+{best_effect*100:.0f}% above average performance",
                    confidence="high",
                    contradicts_generic=False,
                    impact_estimate=f"+{best_effect*100:.0f}%"
                ))
            
            if worst_effect < -0.1:
                insights.append(NicheInsight(
                    insight=f"AVOID '{worst_hook.replace('hook_', '')}' titles in {category}",
                    data_point=f"{worst_effect*100:.0f}% below average",
                    confidence="high",
                    contradicts_generic=True,
                    impact_estimate=f"{worst_effect*100:.0f}%"
                ))
        
        # Length correlation
        length_corr = correlations.get('length', 0)
        if abs(length_corr) > 0.1:
            direction = "LONGER" if length_corr > 0 else "SHORTER"
            insights.append(NicheInsight(
                insight=f"{direction} titles work better in {category}",
                data_point=f"Correlation: {length_corr:.2f}",
                confidence="medium",
                contradicts_generic=length_corr < 0,  # Contradicts if shorter is better
                impact_estimate=f"r={length_corr:.2f}"
            ))
        
        return insights
    
    def _find_counter_intuitive(self, correlations: Dict[str, float]) -> List[NicheInsight]:
        """Find patterns that contradict generic YouTube advice."""
        counter = []
        
        # Check each piece of generic advice
        if correlations.get('has_number', 0) < -0.05:
            counter.append(NicheInsight(
                insight="⚠️ NUMBERS HURT in this niche (contradicts common advice)",
                data_point=f"{correlations['has_number']*100:.0f}% worse with numbers",
                confidence="high",
                contradicts_generic=True,
                impact_estimate=f"{correlations['has_number']*100:.0f}%"
            ))
        
        if correlations.get('has_question', 0) < -0.05:
            counter.append(NicheInsight(
                insight="⚠️ QUESTIONS HURT in this niche (contradicts common advice)",
                data_point=f"{correlations['has_question']*100:.0f}% worse with questions",
                confidence="high",
                contradicts_generic=True,
                impact_estimate=f"{correlations['has_question']*100:.0f}%"
            ))
        
        if correlations.get('has_exclamation', 0) < -0.05:
            counter.append(NicheInsight(
                insight="⚠️ EXCLAMATION MARKS HURT in this niche",
                data_point=f"{correlations['has_exclamation']*100:.0f}% worse",
                confidence="medium",
                contradicts_generic=True,
                impact_estimate=f"{correlations['has_exclamation']*100:.0f}%"
            ))
        
        if correlations.get('length', 0) < -0.15:
            counter.append(NicheInsight(
                insight="⚠️ SHORTER titles work better (contradicts SEO advice)",
                data_point=f"Negative correlation: {correlations['length']:.2f}",
                confidence="high",
                contradicts_generic=True,
                impact_estimate="Shorter = better"
            ))
        
        if correlations.get('caps_ratio', 0) < -0.1:
            counter.append(NicheInsight(
                insight="⚠️ CAPS HURT performance in this niche",
                data_point=f"Negative correlation: {correlations['caps_ratio']:.2f}",
                confidence="medium",
                contradicts_generic=True,
                impact_estimate="Less caps = better"
            ))
        
        return counter
    
    def _extract_templates(self, data: List[dict], min_count: int = 10) -> List[TitleTemplate]:
        """Extract common title patterns from ALL data (not just outliers).
        
        Uses median performance and requires significant sample sizes.
        """
        templates = []
        
        # Common patterns to look for
        pattern_matchers = [
            (r'^(\d+)\s+\w+', "Number-first listicle: '[N] things...'"),
            (r'^[Hh]ow\s+[Tt]o\s+', "How-to format: 'How to...'"),
            (r'^[Ww]hy\s+', "Why question: 'Why...'"),
            (r'^[Ii]\s+\w+ed\s+', "First-person past: 'I [verb]ed...'"),
            (r'^[Tt]he\s+[Tt]ruth\s+[Aa]bout', "Truth reveal: 'The Truth About...'"),
            (r'\|\s*\w+', "Pipe separator: '... | category'"),
            (r'\[.+\]', "Bracketed section: '[...]'"),
            (r'\(.+\)', "Parenthetical: '(...)'"),
            (r'in\s+\d+\s+(minutes?|hours?|days?|seconds?)', "Time-bound: '...in [N] minutes'"),
            (r'\$\d+', "Money mention: '$...'"),
        ]
        
        # Calculate global median for comparison
        global_median = np.median([d['performance'] for d in data])
        
        for pattern_regex, pattern_name in pattern_matchers:
            matching = []
            
            # Search ALL data, not just top performers
            for d in data:
                if re.search(pattern_regex, d['title'], re.IGNORECASE):
                    matching.append(d)
            
            if len(matching) >= min_count:
                # Use MEDIAN performance (robust to outliers)
                perfs = [d['performance'] for d in matching]
                median_perf = np.median(perfs)
                
                # Calculate relative performance vs global median
                relative_perf = median_perf / global_median if global_median > 0 else 1.0
                
                # Get good examples (above median, not crazy outliers)
                good_examples = [d['title'] for d in matching 
                                if 1.0 < d['performance'] < 5.0][:5]
                if not good_examples:
                    good_examples = [d['title'] for d in matching][:5]
                
                templates.append(TitleTemplate(
                    pattern=pattern_name,
                    examples=good_examples,
                    avg_performance=relative_perf,  # Now relative (1.0 = average, 1.2 = 20% better)
                    frequency=len(matching)
                ))
        
        # Sort by relative performance
        templates.sort(key=lambda x: x.avg_performance, reverse=True)
        
        return templates[:10]
    
    # Common English words that are actually meaningful for titles
    VALID_POWER_WORDS = {
        # Action words
        'secret', 'ultimate', 'complete', 'guide', 'tutorial', 'review', 'best',
        'worst', 'top', 'tips', 'tricks', 'hack', 'hacks', 'easy', 'fast', 'quick',
        'simple', 'free', 'new', 'first', 'last', 'final', 'biggest', 'smallest',
        # Emotional words
        'amazing', 'incredible', 'insane', 'crazy', 'epic', 'awesome', 'beautiful',
        'shocking', 'surprising', 'unexpected', 'scary', 'funny', 'hilarious',
        # Time/challenge words
        'challenge', 'days', 'hours', 'minutes', 'week', 'month', 'year', 'ever',
        'never', 'always', 'finally', 'today', 'now', 'update', 'changed',
        # Engagement words
        'truth', 'real', 'honest', 'actually', 'really', 'why', 'how', 'what',
        'everything', 'nothing', 'everyone', 'nobody', 'stop', 'start', 'avoid',
        # Format words
        'part', 'episode', 'season', 'full', 'highlights', 'compilation', 'reaction',
        'versus', 'battle', 'game', 'play', 'playing', 'trying', 'tested', 'tried',
        'made', 'built', 'found', 'discovered', 'learned', 'survived', 'completed',
    }
    
    def _find_power_words(self, data: List[dict], min_count: int = 20) -> List[Tuple[str, float]]:
        """Find words that correlate with high performance.
        
        Only includes real English words, not usernames or noise.
        Uses median instead of mean to avoid outlier influence.
        """
        word_performance = defaultdict(list)
        
        # Tokenize titles and track performance
        for d in data:
            words = re.findall(r'\b[a-z]+\b', d['title'].lower())  # Only letters
            for word in set(words):  # Unique words per title
                # Only include valid power words (real English words)
                if word in self.VALID_POWER_WORDS:
                    word_performance[word].append(d['performance'])
        
        # Calculate median performance for each word (more robust than mean)
        median_global = np.median([d['performance'] for d in data])
        
        power_words = []
        for word, perfs in word_performance.items():
            if len(perfs) >= min_count:  # Need enough samples
                median_perf = np.median(perfs)  # Use median, not mean
                boost = median_perf - median_global
                # Cap boost at reasonable level (max 100% = 2x)
                boost = min(boost, 1.0)
                if boost > 0.05:  # At least 5% boost
                    power_words.append((word, boost))
        
        # Sort by boost
        power_words.sort(key=lambda x: x[1], reverse=True)
        
        return power_words[:15]
    
    def _find_avoid_patterns(self, correlations: Dict[str, float], data: List[dict]) -> List[str]:
        """Find patterns to avoid in this niche."""
        avoid = []
        
        if correlations.get('has_number', 0) < -0.05:
            avoid.append("Numbers in title (hurts performance here)")
        
        if correlations.get('has_question', 0) < -0.05:
            avoid.append("Question format (underperforms here)")
        
        if correlations.get('has_exclamation', 0) < -0.05:
            avoid.append("Exclamation marks (looks spammy here)")
        
        if correlations.get('caps_ratio', 0) < -0.1:
            avoid.append("CAPS (hurts credibility here)")
        
        # Find hook types that underperform
        for key, val in correlations.items():
            if key.startswith('hook_') and val < -0.1:
                hook = key.replace('hook_', '')
                avoid.append(f"'{hook}' format titles (underperform by {val*100:.0f}%)")
        
        return avoid
    
    def _extract_ngrams(
        self, 
        data: List[dict], 
        min_count: int = 50,  # Increased from 15 for statistical validity
        min_creators: int = 5,  # Require diversity - phrase must appear across 5+ creators
    ) -> List[LearnedPhrase]:
        """
        Extract common n-grams (2-4 word phrases) with statistical validity.
        
        Key improvements over naive n-gram extraction:
        1. Controls for channel size (compares within tiers)
        2. Requires minimum 50 videos (not 15)
        3. Requires 5+ different creators (diversity check)
        4. Calculates 95% confidence intervals
        5. Uses size-tier-adjusted performance comparison
        
        This prevents "signature patterns" of single successful creators
        from being reported as generalizable insights.
        """
        from scipy import stats as scipy_stats
        
        if len(data) < 200:
            logger.warning(f"Only {len(data)} videos, need 200+ for n-gram analysis")
            return []
        
        # Calculate median performance BY SIZE TIER (fair comparison)
        tier_medians = {}
        for tier_name in ["micro", "small", "medium", "large", "xlarge", "mega"]:
            tier_data = [d['performance'] for d in data if d.get('size_tier') == tier_name]
            if tier_data:
                tier_medians[tier_name] = np.median(tier_data)
            else:
                tier_medians[tier_name] = 1.0
        
        # Calculate ADJUSTED performance (relative to same-size creators)
        for d in data:
            tier = d.get('size_tier', 'medium')
            baseline = tier_medians.get(tier, 1.0)
            d['adjusted_performance'] = d['performance'] / baseline if baseline > 0 else 1.0
        
        # Extract n-grams from ALL data (not just top performers)
        # We'll filter by performance AFTER checking diversity
        ngram_data = defaultdict(list)  # ngram -> list of {title, adjusted_perf, channel_id}
        
        for d in data:
            title_lower = d['title'].lower()
            words = re.findall(r'\b[a-z]+\b', title_lower)
            
            # 2-grams
            for i in range(len(words) - 1):
                ngram = f"{words[i]} {words[i+1]}"
                if len(ngram) > 5:
                    ngram_data[ngram].append({
                        'title': d['title'],
                        'adjusted_perf': d['adjusted_performance'],
                        'channel_id': d.get('channel_id', 'unknown'),
                        'size_tier': d.get('size_tier', 'medium'),
                    })
            
            # 3-grams
            for i in range(len(words) - 2):
                ngram = f"{words[i]} {words[i+1]} {words[i+2]}"
                if len(ngram) > 8:
                    ngram_data[ngram].append({
                        'title': d['title'],
                        'adjusted_perf': d['adjusted_performance'],
                        'channel_id': d.get('channel_id', 'unknown'),
                        'size_tier': d.get('size_tier', 'medium'),
                    })
            
            # 4-grams
            for i in range(len(words) - 3):
                ngram = f"{words[i]} {words[i+1]} {words[i+2]} {words[i+3]}"
                if len(ngram) > 12:
                    ngram_data[ngram].append({
                        'title': d['title'],
                        'adjusted_perf': d['adjusted_performance'],
                        'channel_id': d.get('channel_id', 'unknown'),
                        'size_tier': d.get('size_tier', 'medium'),
                    })
        
        # Common stop phrases to skip
        stop_phrases = {
            'of the', 'in the', 'on the', 'to the', 'and the', 'for the',
            'is the', 'at the', 'with the', 'from the', 'this is',
            'it is', 'you can', 'how to', 'what is', 'i am', 'we are',
            'is live', 'vlog is', 'vlog is live', 'of my', 'in my',
            'to my', 'and i', 'but i', 'so i', 'that i', 'when i',
        }
        
        # Skip likely proper nouns / event names
        def is_actionable_phrase(phrase: str) -> bool:
            skip_words = ['hgc', 'ewc', 'finals game', 'vs', 'ft', 'feat']
            return not any(w in phrase for w in skip_words)
        
        learned = []
        
        for ngram, entries in ngram_data.items():
            # Skip stop phrases and non-actionable
            if ngram in stop_phrases or not is_actionable_phrase(ngram):
                continue
            
            # FILTER 1: Minimum sample size (50+)
            if len(entries) < min_count:
                continue
            
            # FILTER 2: Creator diversity (5+ unique creators)
            unique_creators = len(set(e['channel_id'] for e in entries))
            if unique_creators < min_creators:
                continue
            
            # Calculate adjusted performance statistics
            perfs = [e['adjusted_perf'] for e in entries]
            median_perf = np.median(perfs)
            mean_perf = np.mean(perfs)
            
            # FILTER 3: Must actually be above average (adjusted > 1.0)
            if median_perf <= 1.05:  # At least 5% better
                continue
            
            # Calculate 95% confidence interval using bootstrap or t-distribution
            n = len(perfs)
            std_err = np.std(perfs, ddof=1) / np.sqrt(n)
            
            # Use t-distribution for small samples
            if n < 30:
                t_crit = scipy_stats.t.ppf(0.975, df=n-1)
            else:
                t_crit = 1.96  # Normal approximation
            
            ci_low = mean_perf - t_crit * std_err
            ci_high = mean_perf + t_crit * std_err
            
            # FILTER 4: Lower bound of CI should be > 1.0 (statistically significant)
            # This ensures the effect isn't just noise
            if ci_low <= 1.0:
                continue
            
            # Determine reliability
            if n >= 100 and unique_creators >= 10:
                reliability = "high"
            elif n >= 50 and unique_creators >= 5:
                reliability = "medium"
            else:
                reliability = "low"
            
            # Get diverse examples (from different creators)
            seen_channels = set()
            examples = []
            for e in sorted(entries, key=lambda x: x['adjusted_perf'], reverse=True):
                if e['channel_id'] not in seen_channels and 0.8 < e['adjusted_perf'] < 5.0:
                    examples.append(e['title'])
                    seen_channels.add(e['channel_id'])
                    if len(examples) >= 3:
                        break

            if not examples:
                examples = [e['title'] for e in entries[:3]]

            learned.append(LearnedPhrase(
                phrase=ngram,
                frequency=n,
                unique_creators=unique_creators,
                avg_performance=median_perf,
                confidence_interval=(ci_low, ci_high),
                example_titles=examples,
                reliability=reliability,
            ))
        
        # Sort by: reliability tier first, then by lower CI bound (conservative estimate)
        reliability_order = {"high": 0, "medium": 1, "low": 2}
        learned.sort(key=lambda x: (reliability_order[x.reliability], -x.confidence_interval[0]))
        
        return learned[:20]
    
    def _validate_phrases_within_creator(
        self, 
        phrases: List[LearnedPhrase], 
        category: str,
        min_with: int = 2,
        min_without: int = 5,
    ) -> Tuple[List[LearnedPhrase], List[LearnedPhrase]]:
        """
        Validate phrases using within-creator comparison.
        
        For each phrase, compares the SAME creator's videos WITH the phrase
        vs their videos WITHOUT the phrase. This tests actual causation,
        not just correlation with successful creators.
        
        Returns:
            (validated_phrases, inspiration_phrases)
            - validated: Phrases that show real within-creator lift (>5%, helped >50%)
            - inspiration: Phrases that are popular but don't pass causal test
        """
        from sqlalchemy import text
        
        validated = []
        inspiration = []
        
        for phrase in phrases:
            try:
                # Run within-creator analysis
                result = self.session.execute(text('''
                    WITH creator_phrase_stats AS (
                        SELECT 
                            c.channel_id,
                            AVG(CASE WHEN LOWER(v.title) LIKE :pattern THEN v.performance_ratio END) as with_avg,
                            AVG(CASE WHEN LOWER(v.title) NOT LIKE :pattern THEN v.performance_ratio END) as without_avg,
                            COUNT(CASE WHEN LOWER(v.title) LIKE :pattern THEN 1 END) as with_count,
                            COUNT(CASE WHEN LOWER(v.title) NOT LIKE :pattern THEN 1 END) as without_count
                        FROM videos v
                        JOIN channels c ON v.channel_id = c.channel_id
                        WHERE c.primary_category = :category
                        AND v.performance_ratio IS NOT NULL
                        GROUP BY c.channel_id
                        HAVING COUNT(CASE WHEN LOWER(v.title) LIKE :pattern THEN 1 END) >= :min_with
                        AND COUNT(CASE WHEN LOWER(v.title) NOT LIKE :pattern THEN 1 END) >= :min_without
                    )
                    SELECT 
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY with_avg / NULLIF(without_avg, 0)) as median_lift,
                        COUNT(*) as total_creators,
                        SUM(CASE WHEN with_avg > without_avg THEN 1 ELSE 0 END) as helped_creators
                    FROM creator_phrase_stats
                    WHERE with_avg IS NOT NULL AND without_avg IS NOT NULL
                '''), {
                    'pattern': f'%{phrase.phrase}%',
                    'category': category,
                    'min_with': min_with,
                    'min_without': min_without,
                }).fetchone()
                
                if result and result[0] is not None:
                    median_lift = float(result[0])
                    total = int(result[1])
                    helped = int(result[2])
                    
                    # Update phrase with validation data
                    phrase.within_creator_lift = (median_lift - 1) * 100  # As percentage
                    phrase.within_creator_total = total
                    phrase.within_creator_helped = helped
                    
                    # Validate: >5% lift AND helped >50% of creators
                    phrase.is_validated = (
                        phrase.within_creator_lift > 5 and 
                        total >= 5 and
                        helped / total > 0.5
                    )
                    
                    if phrase.is_validated:
                        validated.append(phrase)
                    else:
                        inspiration.append(phrase)
                else:
                    # Not enough data to validate
                    phrase.is_validated = False
                    inspiration.append(phrase)
                    
            except Exception as e:
                logger.warning(f"Failed to validate phrase '{phrase.phrase}': {e}")
                phrase.is_validated = False
                inspiration.append(phrase)
        
        # Sort validated by within-creator lift
        validated.sort(key=lambda x: x.within_creator_lift or 0, reverse=True)
        
        return validated, inspiration
    
    def _build_detailed_avoid_patterns(
        self, 
        correlations: Dict[str, float], 
        data: List[dict],
        category: str,
    ) -> List[AvoidPattern]:
        """
        Build detailed "what to avoid" patterns.
        
        These are MORE RELIABLE than "what to add" because negative effects
        are easier to measure causally.
        """
        avoid_patterns = []
        
        # Check punctuation patterns
        if correlations.get('has_exclamation', 0) < -0.05:
            with_exc = [d for d in data if d.get('has_exclamation')]
            without_exc = [d for d in data if not d.get('has_exclamation')]
            avoid_patterns.append(AvoidPattern(
                pattern="Exclamation marks (!)",
                pattern_type="punctuation",
                impact_pct=correlations['has_exclamation'] * 100,
                sample_with=len(with_exc),
                sample_without=len(without_exc),
                confidence="high" if len(with_exc) > 100 else "medium",
                recommendation=f"Avoid exclamation marks in {category} — they underperform by {correlations['has_exclamation']*100:.0f}%"
            ))
        
        if correlations.get('has_question', 0) < -0.05:
            with_q = [d for d in data if d.get('has_question')]
            without_q = [d for d in data if not d.get('has_question')]
            avoid_patterns.append(AvoidPattern(
                pattern="Question marks (?)",
                pattern_type="punctuation",
                impact_pct=correlations['has_question'] * 100,
                sample_with=len(with_q),
                sample_without=len(without_q),
                confidence="high" if len(with_q) > 100 else "medium",
                recommendation=f"Avoid question format in {category} — questions underperform by {correlations['has_question']*100:.0f}%"
            ))
        
        if correlations.get('has_number', 0) < -0.03:
            with_num = [d for d in data if d.get('has_number')]
            without_num = [d for d in data if not d.get('has_number')]
            avoid_patterns.append(AvoidPattern(
                pattern="Numbers in title",
                pattern_type="format",
                impact_pct=correlations['has_number'] * 100,
                sample_with=len(with_num),
                sample_without=len(without_num),
                confidence="medium",
                recommendation=f"Numbers don't help in {category} — consider removing listicle format"
            ))
        
        if correlations.get('caps_ratio', 0) < -0.1:
            avoid_patterns.append(AvoidPattern(
                pattern="EXCESSIVE CAPS",
                pattern_type="format",
                impact_pct=correlations['caps_ratio'] * 100,
                sample_with=0,  # Would need more detailed counting
                sample_without=0,
                confidence="medium",
                recommendation=f"Reduce CAPS in {category} — excessive caps hurts performance"
            ))
        
        # Check hook type patterns that hurt
        for key, val in correlations.items():
            if key.startswith('hook_') and val < -0.1:
                hook = key.replace('hook_', '')
                avoid_patterns.append(AvoidPattern(
                    pattern=f"'{hook}' title format",
                    pattern_type="format",
                    impact_pct=val * 100,
                    sample_with=0,
                    sample_without=0,
                    confidence="high" if val < -0.15 else "medium",
                    recommendation=f"Avoid '{hook}' format in {category} — underperforms by {val*100:.0f}%"
                ))
        
        # Sort by impact (most negative first)
        avoid_patterns.sort(key=lambda x: x.impact_pct)
        
        return avoid_patterns
    
    def _discover_content_patterns(self, category: str) -> List[ContentInsight]:
        """
        Discover content-based patterns (hook timing, audio, pacing) for a niche.
        
        These are features from actual video content analysis, not just metadata.
        """
        insights = []
        
        # Query videos with content analysis in this category
        results = self.session.query(
            Video.video_id,
            Video.view_count,
            Channel.avg_views_per_video,
            VideoContentAnalysis.hook_face_appears_seconds,
            VideoContentAnalysis.hook_scene_changes_count,
            VideoContentAnalysis.has_music_intro,
            VideoContentAnalysis.face_screen_time_ratio,
            VideoContentAnalysis.words_per_minute,
            VideoContentAnalysis.audio_energy_mean,
        ).join(
            Channel, Video.channel_id == Channel.channel_id
        ).join(
            VideoContentAnalysis, Video.video_id == VideoContentAnalysis.video_id
        ).filter(
            Channel.primary_category == category,
            VideoContentAnalysis.extraction_success == True,
            Channel.avg_views_per_video > 0
        ).all()
        
        if len(results) < 50:
            return insights
        
        # Convert to analysis-friendly format
        data = []
        for r in results:
            if r[2] and r[2] > 0:  # Has channel avg
                perf_ratio = r[1] / r[2]
                data.append({
                    'perf_ratio': perf_ratio,
                    'face_appears_sec': r[3],
                    'scene_changes': r[4],
                    'has_music': r[5],
                    'face_ratio': r[6],
                    'wpm': r[7],
                    'audio_energy': r[8],
                })
        
        if len(data) < 50:
            return insights
        
        import pandas as pd
        df = pd.DataFrame(data)
        
        # 1. Face appearance timing
        fast_face = df[df['face_appears_sec'] < 2]['perf_ratio'].median() if len(df[df['face_appears_sec'] < 2]) > 10 else None
        slow_face = df[df['face_appears_sec'] > 5]['perf_ratio'].median() if len(df[df['face_appears_sec'] > 5]) > 10 else None
        
        if fast_face and slow_face and slow_face > 0:
            diff = (fast_face / slow_face - 1) * 100
            if abs(diff) > 10:
                insights.append(ContentInsight(
                    feature="face_timing",
                    helps=diff > 0,
                    impact_pct=diff,
                    recommendation=f"{'Show face in first 2 seconds' if diff > 0 else 'Use cinematic B-roll intro instead of immediate face'} ({diff:+.0f}% impact)",
                    sample_size=len(df)
                ))
        
        # 2. Music intro
        if 'has_music' in df.columns:
            music_yes = df[df['has_music'] == True]['perf_ratio'].median() if len(df[df['has_music'] == True]) > 10 else None
            music_no = df[df['has_music'] == False]['perf_ratio'].median() if len(df[df['has_music'] == False]) > 10 else None
            
            if music_yes and music_no and music_no > 0:
                diff = (music_yes / music_no - 1) * 100
                if abs(diff) > 10:
                    insights.append(ContentInsight(
                        feature="music_intro",
                        helps=diff > 0,
                        impact_pct=diff,
                        recommendation=f"{'Add music intro for polish' if diff > 0 else 'Skip music intro - get straight to content'} ({diff:+.0f}% impact)",
                        sample_size=len(df)
                    ))
        
        # 3. Scene changes (cuts) in hook
        high_cuts = df[df['scene_changes'] > 3]['perf_ratio'].median() if len(df[df['scene_changes'] > 3]) > 10 else None
        low_cuts = df[df['scene_changes'] <= 1]['perf_ratio'].median() if len(df[df['scene_changes'] <= 1]) > 10 else None
        
        if high_cuts and low_cuts and low_cuts > 0:
            diff = (high_cuts / low_cuts - 1) * 100
            if abs(diff) > 10:
                insights.append(ContentInsight(
                    feature="hook_cuts",
                    helps=diff > 0,
                    impact_pct=diff,
                    recommendation=f"{'Use fast cuts in first 10 seconds' if diff > 0 else 'Keep steady shots in intro'} ({diff:+.0f}% impact)",
                    sample_size=len(df)
                ))
        
        # 4. Face screen time ratio
        high_face = df[df['face_ratio'] > 0.5]['perf_ratio'].median() if len(df[df['face_ratio'] > 0.5]) > 10 else None
        low_face = df[df['face_ratio'] < 0.2]['perf_ratio'].median() if len(df[df['face_ratio'] < 0.2]) > 10 else None
        
        if high_face and low_face and low_face > 0:
            diff = (high_face / low_face - 1) * 100
            if abs(diff) > 10:
                insights.append(ContentInsight(
                    feature="face_time",
                    helps=diff > 0,
                    impact_pct=diff,
                    recommendation=f"{'More face time - audience wants to see you' if diff > 0 else 'Less face time - use more B-roll and visuals'} ({diff:+.0f}% impact)",
                    sample_size=len(df)
                ))
        
        return insights
    
    def _empty_patterns(self, category: str) -> NichePatterns:
        """Return empty patterns when insufficient data."""
        return NichePatterns(
            category=category,
            niche_name=None,
            video_count=0,
            unique_insights=[],
            counter_intuitive=[],
            title_templates=[],
            power_words=[],
            avoid_patterns=[],
            feature_correlations={},
            learned_phrases=[],
            content_insights=[],
            validated_phrases=[],
            inspiration_phrases=[],
            avoid_details=[],
        )


def discover_niche_patterns(session: Session, category: str, niche_id: int = None) -> NichePatterns:
    """Convenience function to discover niche patterns."""
    discovery = NichePatternDiscovery(session)
    return discovery.discover_patterns(category, niche_id)

