"""
Title Optimizer

Analyzes video titles and provides improvement suggestions based on
patterns from successful videos in your database.
"""
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy import func, desc
from sqlalchemy.orm import Session
import structlog

from src.database.models import Video, VideoFeatures, Channel

logger = structlog.get_logger()


@dataclass
class TitleAnalysis:
    """Analysis of a single title."""
    title: str
    char_length: int
    word_count: int
    has_number: bool
    number_position: Optional[str]  # start, middle, end
    has_question: bool
    has_exclamation: bool
    has_brackets: bool
    caps_ratio: float
    hook_type: str
    power_words: List[str]
    issues: List[str]
    suggestions: List[str]
    score: int  # 0-100
    

@dataclass
class NicheTitleBenchmarks:
    """Title benchmarks for a specific niche."""
    niche_name: str
    avg_length: float
    avg_words: float
    number_rate: float
    question_rate: float
    exclamation_rate: float
    top_hook_types: List[Tuple[str, float]]
    top_power_words: List[str]
    sample_top_titles: List[str]


class TitleOptimizer:
    """
    Analyzes and optimizes video titles based on successful patterns.
    """
    
    # Power words that drive clicks
    POWER_WORDS = {
        'urgency': ['now', 'today', 'hurry', 'limited', 'last', 'final', 'ending'],
        'curiosity': ['secret', 'hidden', 'revealed', 'truth', 'shocking', 'surprising', 'unexpected'],
        'value': ['free', 'best', 'top', 'ultimate', 'complete', 'full', 'easy', 'simple'],
        'emotion': ['amazing', 'incredible', 'insane', 'crazy', 'epic', 'awesome', 'beautiful'],
        'social': ['everyone', 'nobody', 'people', 'viral', 'famous', 'celebrity'],
        'negative': ['worst', 'fail', 'mistake', 'wrong', 'never', 'stop', 'avoid', 'bad'],
    }
    
    # Hook patterns
    HOOK_PATTERNS = {
        'how_to': r'^how\s+to\b',
        'listicle': r'^\d+\s+\w+',
        'question': r'\?$',
        'challenge': r'\b(challenge|vs\.?|versus|battle)\b',
        'reaction': r'\b(react|reaction|reacting|responding)\b',
        'story': r'\b(story|storytime|happened|experience)\b',
        'reveal': r'\b(reveal|revealing|unveiled|finally)\b',
        'tutorial': r'\b(tutorial|guide|learn|explained)\b',
        'review': r'\b(review|honest|testing|tried)\b',
    }
    
    def __init__(self, session: Optional[Session] = None):
        """Initialize optimizer."""
        self.session = session
        self._benchmarks_cache: Dict[int, NicheTitleBenchmarks] = {}
        self._global_benchmarks: Optional[Dict] = None
    
    def analyze_title(
        self, 
        title: str, 
        niche_id: Optional[int] = None,
        category: Optional[str] = None,
    ) -> TitleAnalysis:
        """
        Analyze a title and provide suggestions.
        
        Args:
            title: The video title to analyze
            niche_id: Optional niche ID for comparison
            category: Optional category for comparison
            
        Returns:
            TitleAnalysis with score and suggestions
        """
        # Basic metrics
        char_length = len(title)
        words = title.split()
        word_count = len(words)
        
        # Number detection
        has_number = bool(re.search(r'\d+', title))
        number_position = self._get_number_position(title) if has_number else None
        
        # Punctuation
        has_question = '?' in title
        has_exclamation = '!' in title
        has_brackets = bool(re.search(r'[\[\]\(\)]', title))
        
        # Caps ratio
        alpha_chars = [c for c in title if c.isalpha()]
        caps_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) if alpha_chars else 0
        
        # Hook type detection
        hook_type = self._detect_hook_type(title)
        
        # Power words
        power_words = self._find_power_words(title)
        
        # Get benchmarks for comparison
        benchmarks = self._get_benchmarks(niche_id, category)
        
        # Generate issues and suggestions
        issues, suggestions = self._generate_feedback(
            title, char_length, word_count, has_number, has_question,
            has_exclamation, caps_ratio, hook_type, power_words, benchmarks
        )
        
        # Calculate score
        score = self._calculate_score(
            char_length, word_count, has_number, has_question,
            hook_type, power_words, caps_ratio, issues, benchmarks
        )
        
        return TitleAnalysis(
            title=title,
            char_length=char_length,
            word_count=word_count,
            has_number=has_number,
            number_position=number_position,
            has_question=has_question,
            has_exclamation=has_exclamation,
            has_brackets=has_brackets,
            caps_ratio=caps_ratio,
            hook_type=hook_type,
            power_words=power_words,
            issues=issues,
            suggestions=suggestions,
            score=score,
        )
    
    def _get_number_position(self, title: str) -> str:
        """Determine where the number appears in the title."""
        match = re.search(r'\d+', title)
        if not match:
            return None
        
        pos = match.start() / len(title)
        if pos < 0.2:
            return 'start'
        elif pos > 0.7:
            return 'end'
        return 'middle'
    
    def _detect_hook_type(self, title: str) -> str:
        """Detect the hook pattern used in the title."""
        title_lower = title.lower()
        
        for hook_name, pattern in self.HOOK_PATTERNS.items():
            if re.search(pattern, title_lower):
                return hook_name
        
        return 'statement'  # Default
    
    def _find_power_words(self, title: str) -> List[str]:
        """Find power words in the title."""
        title_lower = title.lower()
        words_found = []
        
        for category, words in self.POWER_WORDS.items():
            for word in words:
                if re.search(rf'\b{word}\b', title_lower):
                    words_found.append(word)
        
        return words_found
    
    def _get_benchmarks(
        self, 
        niche_id: Optional[int], 
        category: Optional[str]
    ) -> Dict:
        """Get benchmarks for comparison."""
        if self._global_benchmarks is None:
            self._load_global_benchmarks()
        
        return self._global_benchmarks
    
    def _load_global_benchmarks(self):
        """Load global title benchmarks from database."""
        if self.session is None:
            # Default benchmarks if no database
            self._global_benchmarks = {
                'avg_length': 50,
                'avg_words': 8,
                'optimal_length_range': (40, 70),
                'number_rate': 0.35,
                'question_rate': 0.15,
                'top_hooks': ['how_to', 'listicle', 'question'],
            }
            return
        
        # Query database for benchmarks
        from sqlalchemy import Integer
        stats = self.session.query(
            func.avg(VideoFeatures.title_char_length),
            func.avg(VideoFeatures.title_word_count),
            func.sum(VideoFeatures.title_has_number.cast(Integer)),
            func.sum(VideoFeatures.title_has_question.cast(Integer)),
            func.count(VideoFeatures.id),
        ).filter(
            VideoFeatures.title_char_length.isnot(None)
        ).first()
        
        total = stats[4] if stats[4] > 0 else 1
        
        self._global_benchmarks = {
            'avg_length': stats[0] or 50,
            'avg_words': stats[1] or 8,
            'optimal_length_range': (40, 70),
            'number_rate': (stats[2] or 0) / total,
            'question_rate': (stats[3] or 0) / total,
            'top_hooks': ['how_to', 'listicle', 'question'],
        }
    
    def _generate_feedback(
        self, title, length, words, has_number, has_question,
        has_exclamation, caps_ratio, hook_type, power_words, benchmarks
    ) -> Tuple[List[str], List[str]]:
        """Generate issues and suggestions for a title."""
        issues = []
        suggestions = []
        
        # Length check
        if length < 30:
            issues.append("Title is too short")
            suggestions.append("📏 Expand your title to 40-70 characters for better visibility")
        elif length > 80:
            issues.append("Title is too long (may get cut off)")
            suggestions.append("✂️ Shorten to under 70 characters - YouTube cuts off long titles")
        
        # Word count
        if words < 4:
            issues.append("Too few words")
            suggestions.append("📝 Add more descriptive words to improve searchability")
        elif words > 15:
            issues.append("Too many words")
            suggestions.append("📝 Simplify - shorter titles are easier to read quickly")
        
        # Number check
        if not has_number and benchmarks.get('number_rate', 0) > 0.3:
            suggestions.append("🔢 Add a number - titles with numbers get 36% more clicks (e.g., '5 Ways to...', '10 Best...')")
        
        # Hook type
        if hook_type == 'statement':
            suggestions.append("🎣 Add a hook - try a question, how-to, or listicle format")
        
        # Power words
        if not power_words:
            suggestions.append("💪 Add power words like 'amazing', 'secret', 'best', 'easy' to increase clicks")
        
        # Caps check
        if caps_ratio > 0.5:
            issues.append("Too many CAPS (looks spammy)")
            suggestions.append("🔤 Reduce caps usage - it looks clickbaity and unprofessional")
        elif caps_ratio < 0.05 and length > 20:
            suggestions.append("🔠 Consider capitalizing key words for emphasis")
        
        # Question check
        if not has_question and hook_type != 'question':
            if benchmarks.get('question_rate', 0) > 0.15:
                suggestions.append("❓ Questions in titles create curiosity and boost CTR")
        
        # Brackets suggestion
        if not any(c in title for c in '[]()'):
            suggestions.append("📌 Try adding [BRACKETS] to highlight key info (e.g., [2024], [FULL GUIDE])")
        
        return issues, suggestions[:5]  # Limit suggestions
    
    def _calculate_score(
        self, length, words, has_number, has_question,
        hook_type, power_words, caps_ratio, issues, benchmarks
    ) -> int:
        """Calculate a title optimization score (0-100)."""
        score = 50  # Base score
        
        # Length bonus/penalty
        if 40 <= length <= 70:
            score += 15
        elif length < 30 or length > 90:
            score -= 15
        else:
            score += 5
        
        # Word count
        if 5 <= words <= 12:
            score += 10
        elif words < 4 or words > 15:
            score -= 10
        
        # Number bonus
        if has_number:
            score += 10
        
        # Question bonus
        if has_question:
            score += 5
        
        # Hook type bonus
        if hook_type in ['how_to', 'listicle', 'question', 'challenge']:
            score += 10
        elif hook_type != 'statement':
            score += 5
        
        # Power words bonus
        score += min(len(power_words) * 5, 15)
        
        # Caps penalty
        if caps_ratio > 0.5:
            score -= 15
        
        # Issues penalty
        score -= len(issues) * 5
        
        return max(0, min(100, score))
    
    def get_top_titles_in_niche(
        self, 
        niche_id: int, 
        limit: int = 10
    ) -> List[Tuple[str, int]]:
        """Get top performing titles in a niche for inspiration."""
        if self.session is None:
            return []
        
        results = self.session.query(
            Video.title,
            Video.view_count
        ).join(
            Channel, Video.channel_id == Channel.channel_id
        ).filter(
            Channel.niche_id == niche_id,
            Video.view_count > 10000
        ).order_by(
            desc(Video.view_count)
        ).limit(limit).all()
        
        return [(title, views) for title, views in results]
    
    def suggest_alternatives(self, title: str, style: str = 'mixed') -> List[str]:
        """
        Suggest alternative title formulations.
        
        Args:
            title: Original title
            style: 'question', 'listicle', 'how_to', or 'mixed'
            
        Returns:
            List of alternative title suggestions
        """
        alternatives = []
        words = title.split()
        
        # Extract key topic (simplified)
        topic = ' '.join(words[:5]) if len(words) > 5 else title
        topic = re.sub(r'[^\w\s]', '', topic)
        
        if style in ['question', 'mixed']:
            alternatives.append(f"Why {topic} Is More Important Than You Think")
            alternatives.append(f"What Nobody Tells You About {topic}")
            alternatives.append(f"Is {topic} Worth It? The Truth")
        
        if style in ['listicle', 'mixed']:
            alternatives.append(f"7 Things You Need to Know About {topic}")
            alternatives.append(f"5 {topic} Mistakes Everyone Makes")
            alternatives.append(f"Top 10 {topic} Tips for Beginners")
        
        if style in ['how_to', 'mixed']:
            alternatives.append(f"How to Master {topic} (Complete Guide)")
            alternatives.append(f"{topic} Explained in 10 Minutes")
            alternatives.append(f"The Ultimate {topic} Tutorial for 2024")
        
        return alternatives[:5]

