"""
Transcript analysis for video content features.

Analyzes speech patterns, pacing, engagement techniques, and content quality.
"""
import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import numpy as np
import structlog

logger = structlog.get_logger()


# Filler words by category
FILLER_WORDS = {
    "hesitation": [
        "um", "uh", "uhh", "umm", "er", "err", "ah", "ahh", "hmm", "hm"
    ],
    "hedge": [
        "like", "you know", "i mean", "kind of", "sort of", "basically",
        "actually", "literally", "honestly", "right", "okay so"
    ],
    "repetition": [
        "and and", "the the", "i i", "so so", "but but", "that that"
    ]
}

# Engagement trigger phrases
ENGAGEMENT_TRIGGERS = {
    "direct_address": [
        "you", "your", "you're", "you'll", "you've"
    ],
    "questions": [
        "?", "why", "how", "what", "when", "where", "who", "which",
        "have you ever", "did you know", "can you", "do you"
    ],
    "calls_to_action": [
        "subscribe", "like", "comment", "share", "hit the bell",
        "notification", "turn on notifications", "let me know",
        "leave a comment", "drop a like", "smash that", "click"
    ],
    "open_loops": [
        "later in this video", "coming up", "stick around",
        "by the end of this video", "wait until you see",
        "but first", "before we get to that", "stay tuned"
    ],
    "social_proof": [
        "million", "thousand", "viewers", "subscribers", "people",
        "everyone", "most people", "studies show", "research shows",
        "according to", "experts say"
    ],
    "urgency": [
        "now", "today", "right now", "immediately", "don't miss",
        "limited", "before it's too late", "hurry", "quick"
    ],
    "controversy": [
        "wrong", "mistake", "lie", "truth", "actually", "myth",
        "controversial", "unpopular opinion", "hot take", "debate"
    ]
}

# Hook pattern starters
HOOK_PATTERNS = {
    "question": [
        r"^(have you|did you|do you|what if|why do|how do|can you|would you)",
        r"^(what|why|how|when|where|who)\b",
        r"\?$"
    ],
    "statement": [
        r"^(i'm going to|today we|in this video|let me show)",
        r"^(this is|here's|here is|there's|there is)"
    ],
    "story": [
        r"^(so|okay so|alright so|last week|yesterday|the other day)",
        r"^(i was|we were|when i|i remember)"
    ],
    "statistic": [
        r"^\d+%",
        r"^(according to|studies show|research shows|data shows)",
        r"\d+ (percent|million|billion|thousand)"
    ],
    "teaser": [
        r"(you won't believe|wait until|this is crazy|insane)",
        r"(changed my life|blew my mind|game changer)"
    ],
    "cold_open": [
        r"^[\"']",  # Starts with quote (in media res)
        r"^(boom|bang|crash|suddenly|and then)"
    ]
}


@dataclass
class TranscriptFeatures:
    """Extracted features from video transcript."""
    # Basic metrics
    word_count: int
    sentence_count: int
    avg_sentence_length: float
    
    # Pacing
    words_per_minute: Optional[float]
    estimated_speaking_rate: str  # slow, medium, fast
    
    # Filler analysis
    filler_word_count: int
    filler_word_ratio: float  # filler / total words
    filler_assessment: str  # minimal, moderate, excessive
    filler_breakdown: Dict[str, int]  # by category
    
    # Engagement
    question_count: int
    cta_count: int  # calls to action
    direct_address_count: int
    open_loop_count: int
    engagement_score: float  # 0-1 composite
    
    # Hook analysis
    detected_hook_type: Optional[str]
    hook_strength_score: float  # 0-1
    first_hook_word_position: int  # Where first engaging element appears
    
    # Hook classification (enhanced)
    hook_classification: str  # question, story, statistic, teaser, cold_open, statement, none
    hook_classification_confidence: float  # 0-1 confidence in classification
    hook_elements: List[str]  # specific elements detected (e.g., "question", "urgency", "statistic")
    hook_pattern_matches: Dict[str, int]  # count of matches per hook type
    
    # Content structure
    has_clear_intro: bool
    has_clear_outro: bool
    topic_coherence_score: float  # 0-1 (placeholder for future)
    
    # Engagement triggers found
    triggers_found: List[str]


class TranscriptAnalyzer:
    """Analyze video transcripts for content quality and engagement features."""
    
    def __init__(self):
        self.filler_patterns = self._compile_filler_patterns()
        self.hook_patterns = self._compile_hook_patterns()
    
    def _compile_filler_patterns(self) -> Dict[str, List[re.Pattern]]:
        """Compile regex patterns for filler detection."""
        compiled = {}
        for category, words in FILLER_WORDS.items():
            compiled[category] = [
                re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
                for word in words
            ]
        return compiled
    
    def _compile_hook_patterns(self) -> Dict[str, List[re.Pattern]]:
        """Compile regex patterns for hook detection."""
        compiled = {}
        for hook_type, patterns in HOOK_PATTERNS.items():
            compiled[hook_type] = [
                re.compile(pattern, re.IGNORECASE)
                for pattern in patterns
            ]
        return compiled
    
    def analyze(self, transcript: str, duration_seconds: Optional[float] = None) -> TranscriptFeatures:
        """
        Analyze a transcript for content features.
        
        Args:
            transcript: Full video transcript text
            duration_seconds: Video duration for WPM calculation
            
        Returns:
            TranscriptFeatures with all extracted features
        """
        if not transcript or not transcript.strip():
            return self._empty_features()
        
        # Clean transcript
        transcript_clean = self._clean_transcript(transcript)
        transcript_lower = transcript_clean.lower()
        
        # Basic metrics
        words = transcript_clean.split()
        word_count = len(words)
        
        sentences = self._split_sentences(transcript_clean)
        sentence_count = len(sentences)
        avg_sentence_length = word_count / max(sentence_count, 1)
        
        # Pacing
        wpm = None
        speaking_rate = "medium"
        if duration_seconds and duration_seconds > 0:
            wpm = (word_count / duration_seconds) * 60
            if wpm < 120:
                speaking_rate = "slow"
            elif wpm > 160:
                speaking_rate = "fast"
        
        # Filler analysis
        filler_count, filler_breakdown = self._count_fillers(transcript_lower)
        filler_ratio = filler_count / max(word_count, 1)
        
        filler_assessment = "minimal"
        if filler_ratio > 0.03:
            filler_assessment = "moderate"
        if filler_ratio > 0.06:
            filler_assessment = "excessive"
        
        # Engagement analysis
        question_count = self._count_questions(transcript_clean)
        cta_count = self._count_ctas(transcript_lower)
        direct_address_count = self._count_direct_address(transcript_lower)
        open_loop_count = self._count_open_loops(transcript_lower)
        
        triggers_found = self._find_engagement_triggers(transcript_lower)
        
        # Calculate engagement score (0-1)
        engagement_score = self._calculate_engagement_score(
            word_count, question_count, cta_count, direct_address_count,
            open_loop_count, len(triggers_found)
        )
        
        # Hook analysis (first 100 words)
        first_100_words = " ".join(words[:100])
        hook_type, hook_strength = self._analyze_hook(first_100_words)
        first_hook_pos = self._find_first_hook_position(words)
        
        # Enhanced hook classification
        hook_classification = self._classify_hook(first_100_words)
        
        # Structure analysis
        has_intro = self._has_clear_intro(first_100_words.lower())
        has_outro = self._has_clear_outro(" ".join(words[-50:]).lower())
        
        return TranscriptFeatures(
            word_count=word_count,
            sentence_count=sentence_count,
            avg_sentence_length=avg_sentence_length,
            words_per_minute=wpm,
            estimated_speaking_rate=speaking_rate,
            filler_word_count=filler_count,
            filler_word_ratio=filler_ratio,
            filler_assessment=filler_assessment,
            filler_breakdown=filler_breakdown,
            question_count=question_count,
            cta_count=cta_count,
            direct_address_count=direct_address_count,
            open_loop_count=open_loop_count,
            engagement_score=engagement_score,
            detected_hook_type=hook_type,
            hook_strength_score=hook_strength,
            first_hook_word_position=first_hook_pos,
            hook_classification=hook_classification["hook_classification"],
            hook_classification_confidence=hook_classification["hook_classification_confidence"],
            hook_elements=hook_classification["hook_elements"],
            hook_pattern_matches=hook_classification["hook_pattern_matches"],
            has_clear_intro=has_intro,
            has_clear_outro=has_outro,
            topic_coherence_score=0.5,  # Placeholder - would need NLP
            triggers_found=triggers_found
        )
    
    def _empty_features(self) -> TranscriptFeatures:
        """Return empty features for missing transcript."""
        return TranscriptFeatures(
            word_count=0,
            sentence_count=0,
            avg_sentence_length=0,
            words_per_minute=None,
            estimated_speaking_rate="unknown",
            filler_word_count=0,
            filler_word_ratio=0,
            filler_assessment="unknown",
            filler_breakdown={},
            question_count=0,
            cta_count=0,
            direct_address_count=0,
            open_loop_count=0,
            engagement_score=0,
            detected_hook_type=None,
            hook_strength_score=0,
            first_hook_word_position=-1,
            hook_classification="none",
            hook_classification_confidence=0.0,
            hook_elements=[],
            hook_pattern_matches={},
            has_clear_intro=False,
            has_clear_outro=False,
            topic_coherence_score=0,
            triggers_found=[]
        )
    
    def _clean_transcript(self, transcript: str) -> str:
        """Clean transcript for analysis."""
        # Remove timestamps if present
        cleaned = re.sub(r'\[\d+:\d+:\d+\]', '', transcript)
        cleaned = re.sub(r'\d+:\d+', '', cleaned)
        # Remove speaker labels
        cleaned = re.sub(r'^[A-Z]+:', '', cleaned, flags=re.MULTILINE)
        # Normalize whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned
    
    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        # Simple sentence splitting
        sentences = re.split(r'[.!?]+', text)
        return [s.strip() for s in sentences if s.strip()]
    
    def _count_fillers(self, transcript_lower: str) -> tuple:
        """Count filler words by category."""
        breakdown = {}
        total = 0
        
        for category, patterns in self.filler_patterns.items():
            count = 0
            for pattern in patterns:
                matches = pattern.findall(transcript_lower)
                count += len(matches)
            breakdown[category] = count
            total += count
        
        return total, breakdown
    
    def _count_questions(self, transcript: str) -> int:
        """Count questions in transcript."""
        return transcript.count('?')
    
    def _count_ctas(self, transcript_lower: str) -> int:
        """Count calls to action."""
        count = 0
        for phrase in ENGAGEMENT_TRIGGERS["calls_to_action"]:
            count += transcript_lower.count(phrase.lower())
        return count
    
    def _count_direct_address(self, transcript_lower: str) -> int:
        """Count direct audience addresses (you, your, etc.)."""
        count = 0
        for word in ENGAGEMENT_TRIGGERS["direct_address"]:
            # Use word boundaries
            matches = re.findall(r'\b' + word + r'\b', transcript_lower)
            count += len(matches)
        return count
    
    def _count_open_loops(self, transcript_lower: str) -> int:
        """Count open loop/teaser phrases."""
        count = 0
        for phrase in ENGAGEMENT_TRIGGERS["open_loops"]:
            count += transcript_lower.count(phrase.lower())
        return count
    
    def _find_engagement_triggers(self, transcript_lower: str) -> List[str]:
        """Find which engagement trigger categories are present."""
        found = []
        for category, phrases in ENGAGEMENT_TRIGGERS.items():
            for phrase in phrases:
                if phrase.lower() in transcript_lower:
                    if category not in found:
                        found.append(category)
                    break
        return found
    
    def _calculate_engagement_score(self, word_count: int, questions: int,
                                     ctas: int, direct: int, loops: int,
                                     trigger_types: int) -> float:
        """Calculate composite engagement score."""
        if word_count == 0:
            return 0.0
        
        # Normalize counts per 1000 words
        norm = 1000 / max(word_count, 100)
        
        # Score components
        question_score = min(1.0, questions * norm * 0.1)  # ~10 questions per 1000 words = max
        cta_score = min(1.0, ctas * norm * 0.2)  # ~5 CTAs per 1000 words = max
        direct_score = min(1.0, direct * norm * 0.02)  # Plenty of "you" is good
        loop_score = min(1.0, loops * norm * 0.3)  # ~3 open loops per 1000 words = max
        variety_score = trigger_types / len(ENGAGEMENT_TRIGGERS)  # Variety of techniques
        
        # Weighted average
        score = (
            question_score * 0.2 +
            cta_score * 0.15 +
            direct_score * 0.25 +
            loop_score * 0.15 +
            variety_score * 0.25
        )
        
        return float(np.clip(score, 0, 1))
    
    def _analyze_hook(self, first_100_words: str) -> tuple:
        """Analyze the hook type and strength."""
        first_lower = first_100_words.lower()
        
        detected_type = None
        max_matches = 0
        
        for hook_type, patterns in self.hook_patterns.items():
            matches = 0
            for pattern in patterns:
                if pattern.search(first_lower):
                    matches += 1
            if matches > max_matches:
                max_matches = matches
                detected_type = hook_type
        
        # Hook strength based on:
        # - Pattern match
        # - Direct address in first 100 words
        # - Question in first 100 words
        strength = 0.0
        
        if detected_type:
            strength += 0.3
        
        if "you" in first_lower or "your" in first_lower:
            strength += 0.2
        
        if "?" in first_100_words:
            strength += 0.2
        
        # Check for power words
        power_words = ["secret", "amazing", "incredible", "shocking", "never", "always"]
        for word in power_words:
            if word in first_lower:
                strength += 0.1
                break
        
        # Penalize slow starts
        if first_lower.startswith(("so", "okay", "alright", "hey guys", "what's up")):
            strength -= 0.1
        
        return detected_type, float(np.clip(strength, 0, 1))
    
    def _classify_hook(self, first_100_words: str) -> Dict[str, Any]:
        """
        Enhanced hook classification with confidence and element detection.
        
        Returns:
            Dict with classification, confidence, elements, and pattern_matches
        """
        first_lower = first_100_words.lower()
        
        # Count matches for each hook type
        pattern_matches: Dict[str, int] = {}
        for hook_type, patterns in self.hook_patterns.items():
            matches = 0
            for pattern in patterns:
                if pattern.search(first_lower):
                    matches += 1
            pattern_matches[hook_type] = matches
        
        # Detect specific elements
        elements: List[str] = []
        
        # Question detection
        if "?" in first_100_words or any(
            w in first_lower for w in ["why", "how", "what", "who", "when", "where"]
        ):
            elements.append("question")
        
        # Direct address
        if any(w in first_lower for w in ["you", "your", "you're"]):
            elements.append("direct_address")
        
        # Statistic/number
        if re.search(r'\d+%|\d+ (million|thousand|billion|percent)', first_lower):
            elements.append("statistic")
        
        # Story indicator
        if any(first_lower.startswith(s) for s in ["so ", "when i ", "last ", "i was ", "we were "]):
            elements.append("story_start")
        
        # Teaser/curiosity
        if any(t in first_lower for t in ["wait until", "you won't believe", "incredible", "insane", "crazy"]):
            elements.append("teaser")
        
        # Urgency
        if any(u in first_lower for u in ["right now", "today", "immediately", "don't miss"]):
            elements.append("urgency")
        
        # Cold open (quote or action)
        if first_100_words.strip().startswith('"') or first_100_words.strip().startswith("'"):
            elements.append("cold_open_quote")
        
        # Promise
        if any(p in first_lower for p in ["by the end", "you'll learn", "i'm going to show", "in this video"]):
            elements.append("promise")
        
        # Determine best classification
        total_matches = sum(pattern_matches.values())
        if total_matches == 0:
            classification = "none"
            confidence = 0.0
        else:
            # Sort by match count
            sorted_types = sorted(pattern_matches.items(), key=lambda x: -x[1])
            classification = sorted_types[0][0] if sorted_types[0][1] > 0 else "none"
            
            # Confidence based on match dominance
            best_count = sorted_types[0][1]
            second_count = sorted_types[1][1] if len(sorted_types) > 1 else 0
            
            if best_count == 0:
                confidence = 0.0
            elif best_count == second_count:
                confidence = 0.5  # Tie
            else:
                confidence = min(1.0, 0.4 + (best_count - second_count) * 0.2)
        
        # Boost confidence based on element count
        if len(elements) >= 3:
            confidence = min(1.0, confidence + 0.2)
        elif len(elements) >= 2:
            confidence = min(1.0, confidence + 0.1)
        
        return {
            "hook_classification": classification,
            "hook_classification_confidence": confidence,
            "hook_elements": elements,
            "hook_pattern_matches": pattern_matches,
        }
    
    def _find_first_hook_position(self, words: List[str]) -> int:
        """Find position of first engaging element."""
        engaging_starts = ["you", "this", "here's", "why", "how", "what"]
        
        for i, word in enumerate(words[:50]):
            word_lower = word.lower().strip('.,!?')
            if word_lower in engaging_starts:
                return i
            if '?' in word:
                return i
        
        return -1  # No clear hook found
    
    def _has_clear_intro(self, first_100_lower: str) -> bool:
        """Check if there's a clear intro/value proposition."""
        intro_signals = [
            "in this video", "today we", "i'm going to", "let me show",
            "by the end", "you'll learn", "we're going to", "i'll show"
        ]
        return any(signal in first_100_lower for signal in intro_signals)
    
    def _has_clear_outro(self, last_50_lower: str) -> bool:
        """Check if there's a clear outro."""
        outro_signals = [
            "thanks for watching", "see you", "next video", "subscribe",
            "let me know", "in the comments", "bye", "peace"
        ]
        return any(signal in last_50_lower for signal in outro_signals)


def analyze_transcript(transcript: str, duration_seconds: float = None) -> TranscriptFeatures:
    """Convenience function to analyze a transcript."""
    analyzer = TranscriptAnalyzer()
    return analyzer.analyze(transcript, duration_seconds)

