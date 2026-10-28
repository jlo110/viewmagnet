"""Title feature extraction."""
import re
from dataclasses import dataclass
from typing import Optional
import structlog

logger = structlog.get_logger()


@dataclass
class TitleFeatures:
    """Extracted features from a video title."""
    char_length: int
    word_count: int
    has_number: bool
    number_position: Optional[str]  # start, middle, end, None
    has_question: bool
    has_exclamation: bool
    has_brackets: bool
    caps_ratio: float
    hook_type: Optional[str]
    emotional_score: float
    sentiment: float
    trending_score: float  # Relevance to trending topics, 0-1
    specificity_score: float  # How specific vs vague, 0-1


# Common hook patterns
HOOK_PATTERNS = {
    "how_to": [
        r"^how to\b",
        r"^how i\b",
        r"^learn to\b",
        r"^guide to\b",
    ],
    "listicle": [
        r"^\d+\s+(best|top|ways|things|tips|reasons|tricks)",
        r"^top\s+\d+",
        r"^best\s+\d+",
    ],
    "curiosity_gap": [
        r"you won't believe",
        r"what happens when",
        r"the truth about",
        r"what no one tells you",
        r"secret",
        r"revealed",
        r"shocking",
    ],
    "challenge": [
        r"challenge\b",
        r"vs\b",
        r"battle\b",
        r"competition",
        r"for 24 hours",
        r"for a week",
    ],
    "reaction": [
        r"react(ing|ion)?\b",
        r"response\b",
        r"reacting to\b",
        r"my thoughts on",
    ],
    "story": [
        r"story time",
        r"my experience",
        r"what happened",
        r"the day i",
        r"i tried\b",
        r"i went\b",
    ],
    "tutorial": [
        r"tutorial\b",
        r"explained\b",
        r"beginner",
        r"complete guide",
        r"step by step",
    ],
    "review": [
        r"review\b",
        r"honest review",
        r"unboxing",
        r"first impressions",
        r"worth it\?",
    ],
    "news": [
        r"breaking\b",
        r"update\b",
        r"news\b",
        r"just happened",
        r"announced",
    ],
}

# Emotional/power words
EMOTIONAL_WORDS = {
    "positive": [
        "amazing", "awesome", "incredible", "insane", "epic", "perfect",
        "beautiful", "best", "love", "fantastic", "wonderful", "brilliant",
        "ultimate", "legendary", "satisfying", "relaxing", "cozy",
    ],
    "negative": [
        "worst", "terrible", "awful", "hate", "fail", "disaster",
        "horrible", "scary", "creepy", "disturbing", "painful", "broke",
    ],
    "urgent": [
        "now", "must", "need", "urgent", "immediately", "hurry",
        "finally", "breaking", "new", "just", "today",
    ],
    "curiosity": [
        "secret", "hidden", "unknown", "mystery", "truth", "real",
        "actually", "never", "ever", "only", "first",
    ],
}

# Trending/viral keywords (commonly used in high-performing videos)
TRENDING_KEYWORDS = {
    "viral_phrases": [
        "gone wrong", "gone viral", "went viral", "blew up", "broke the internet",
        "you need to see", "can't believe", "everyone is talking about",
    ],
    "current_trends": [
        "ai", "chatgpt", "tiktok", "viral", "trending", "2024", "2025", "2026",
        "shorts", "reels", "podcast", "mukbang", "asmr", "grwm", "haul",
    ],
    "engagement_bait": [
        "wait for it", "watch till the end", "you won't believe",
        "i can't believe", "this is why", "here's why", "the real reason",
    ],
    "format_trends": [
        "pov", "day in the life", "what i eat", "room tour", "closet tour",
        "q&a", "storytime", "get ready with me", "routine",
    ],
}

# Specificity indicators
SPECIFIC_WORDS = {
    "numbers_units": [
        r"\$\d+", r"\d+%", r"\d+k", r"\d+m", r"\d+ hours?", r"\d+ days?",
        r"\d+ minutes?", r"\d+ seconds?", r"\d+ years?", r"\d+ months?",
    ],
    "proper_nouns_patterns": [
        r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+",  # Multi-word proper nouns
    ],
    "specific_modifiers": [
        "exactly", "specifically", "precisely", "detailed", "complete",
        "full", "entire", "comprehensive", "step-by-step", "in-depth",
    ],
}

VAGUE_WORDS = [
    "things", "stuff", "something", "everything", "anything", "someone",
    "this", "that", "it", "these", "those", "very", "really", "just",
    "some", "many", "few", "lot", "kind of", "sort of", "basically",
]


class TitleAnalyzer:
    """Extracts features from video titles."""
    
    def analyze(self, title: str) -> TitleFeatures:
        """
        Extract features from a video title.
        
        Args:
            title: The video title
            
        Returns:
            TitleFeatures with all extracted features
        """
        if not title:
            return self._empty_features()
        
        title_lower = title.lower()
        
        return TitleFeatures(
            char_length=len(title),
            word_count=len(title.split()),
            has_number=self._has_number(title),
            number_position=self._get_number_position(title),
            has_question=self._has_question(title),
            has_exclamation=self._has_exclamation(title),
            has_brackets=self._has_brackets(title),
            caps_ratio=self._get_caps_ratio(title),
            hook_type=self._detect_hook_type(title_lower),
            emotional_score=self._get_emotional_score(title_lower),
            sentiment=self._get_sentiment(title_lower),
            trending_score=self._get_trending_score(title_lower),
            specificity_score=self._get_specificity_score(title, title_lower),
        )
    
    def _empty_features(self) -> TitleFeatures:
        """Return empty features for missing title."""
        return TitleFeatures(
            char_length=0,
            word_count=0,
            has_number=False,
            number_position=None,
            has_question=False,
            has_exclamation=False,
            has_brackets=False,
            caps_ratio=0.0,
            hook_type=None,
            emotional_score=0.0,
            sentiment=0.0,
            trending_score=0.0,
            specificity_score=0.0,
        )
    
    def _has_number(self, title: str) -> bool:
        """Check if title contains a number."""
        return bool(re.search(r'\d', title))
    
    def _get_number_position(self, title: str) -> Optional[str]:
        """Determine where numbers appear in the title."""
        if not self._has_number(title):
            return None
        
        words = title.split()
        if not words:
            return None
        
        # Check first word
        if re.search(r'\d', words[0]):
            return "start"
        
        # Check last word
        if re.search(r'\d', words[-1]):
            return "end"
        
        return "middle"
    
    def _has_question(self, title: str) -> bool:
        """Check if title contains a question mark."""
        return "?" in title
    
    def _has_exclamation(self, title: str) -> bool:
        """Check if title contains an exclamation mark."""
        return "!" in title
    
    def _has_brackets(self, title: str) -> bool:
        """Check if title contains brackets or parentheses."""
        return bool(re.search(r'[\[\]\(\)\{\}]', title))
    
    def _get_caps_ratio(self, title: str) -> float:
        """Calculate ratio of uppercase letters."""
        letters = [c for c in title if c.isalpha()]
        if not letters:
            return 0.0
        
        uppercase = sum(1 for c in letters if c.isupper())
        return uppercase / len(letters)
    
    def _detect_hook_type(self, title_lower: str) -> Optional[str]:
        """Detect the type of hook used in the title."""
        for hook_type, patterns in HOOK_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, title_lower):
                    return hook_type
        return None
    
    def _get_emotional_score(self, title_lower: str) -> float:
        """
        Calculate emotional intensity score.
        
        Returns a value from 0 to 1 based on presence of emotional words.
        """
        words = set(title_lower.split())
        
        emotional_count = 0
        for category in EMOTIONAL_WORDS.values():
            for word in category:
                if word in words or word in title_lower:
                    emotional_count += 1
        
        # Normalize: assume 3+ emotional elements is max
        return min(1.0, emotional_count / 3.0)
    
    def _get_sentiment(self, title_lower: str) -> float:
        """
        Calculate sentiment polarity.
        
        Returns a value from -1 (negative) to 1 (positive).
        """
        positive_count = 0
        negative_count = 0
        
        for word in EMOTIONAL_WORDS["positive"]:
            if word in title_lower:
                positive_count += 1
        
        for word in EMOTIONAL_WORDS["negative"]:
            if word in title_lower:
                negative_count += 1
        
        total = positive_count + negative_count
        if total == 0:
            return 0.0
        
        return (positive_count - negative_count) / total
    
    def _get_trending_score(self, title_lower: str) -> float:
        """
        Calculate trending keyword relevance score.
        
        Returns a value from 0 to 1 based on presence of trending keywords.
        """
        trending_count = 0
        
        for category in TRENDING_KEYWORDS.values():
            for keyword in category:
                if keyword in title_lower:
                    trending_count += 1
        
        # Normalize: 3+ trending elements is considered max
        return min(1.0, trending_count / 3.0)
    
    def _get_specificity_score(self, title: str, title_lower: str) -> float:
        """
        Calculate specificity score.
        
        Higher score = more specific title (numbers, proper nouns, details)
        Lower score = vague, generic title
        
        Returns a value from 0 to 1.
        """
        specific_count = 0
        vague_count = 0
        
        # Check for specific indicators
        for category, patterns in SPECIFIC_WORDS.items():
            for pattern in patterns:
                if re.search(pattern, title if category == "proper_nouns_patterns" else title_lower):
                    specific_count += 1
        
        # Check for vague words
        for word in VAGUE_WORDS:
            if word in title_lower:
                vague_count += 1
        
        # Also consider:
        # - Longer titles tend to be more specific
        word_count = len(title.split())
        if word_count >= 8:
            specific_count += 1
        
        # - Having numbers (already detected, use as bonus)
        if self._has_number(title):
            specific_count += 1
        
        # Calculate score: specific indicators vs vague indicators
        total_indicators = specific_count + vague_count
        if total_indicators == 0:
            return 0.5  # Neutral
        
        # Base score from specificity ratio
        specificity_ratio = specific_count / (specific_count + vague_count + 1)
        
        # Normalize to 0-1
        return min(1.0, specificity_ratio * 1.5)

