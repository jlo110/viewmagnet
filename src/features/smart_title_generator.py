"""
Smart Title Generator

Generates optimized title suggestions based on:
1. Niche-specific patterns (what works in YOUR category)
2. Channel history (what works for THIS creator)
3. Current trends (what's hot right now)
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Dict

import numpy as np
import structlog

from src.database.connection import get_session
from src.database.models import Video, Channel

logger = structlog.get_logger(__name__)


@dataclass
class SmartTitleSuggestion:
    """A generated title suggestion from the heuristic SmartTitleGenerator.

    Renamed from ``TitleSuggestion`` to disambiguate from the data-driven
    :class:`src.features.title_generator.TitleSuggestion` (different fields)
    and from the API-layer Pydantic ``TitleSuggestion`` in ``src/api/main.py``.
    A backwards-compatible alias is exported below.
    """
    title: str
    score: float  # 0-100 estimated performance
    reason: str
    pattern_used: str
    improvements: List[str]


# Backwards-compat alias for code/tests that still import the old name.
TitleSuggestion = SmartTitleSuggestion


@dataclass 
class TitleAnalysis:
    """Analysis of the original title."""
    original: str
    score: float
    strengths: List[str]
    weaknesses: List[str]
    suggestions: List[SmartTitleSuggestion]


class SmartTitleGenerator:
    """Generates optimized titles using niche patterns."""
    
    # Proven title templates by category
    TEMPLATES = {
        "gaming": [
            "I {action} for {duration} and {outcome}",
            "{number} {items} That Will {benefit}",
            "How I {achievement} in {game}",
            "This {item} Changed Everything in {game}",
            "{game}: {controversial_statement}",
        ],
        "tech": [
            "The {adjective} {product} Review",
            "{product} vs {product}: Which is Better?",
            "I Switched to {product} for {duration}",
            "{number} {product} Features You Didn't Know",
            "Why {product} is {opinion}",
        ],
        "education": [
            "How to {skill} in {timeframe}",
            "{number} {topic} Tips That Actually Work",
            "The Complete Guide to {topic}",
            "{topic} Explained in {duration}",
            "Why {common_belief} is Wrong",
        ],
        "entertainment": [
            "I Tried {challenge} for {duration}",
            "Reacting to {subject}",
            "The Truth About {topic}",
            "I {action} So You Don't Have To",
            "{number} Things You Didn't Know About {topic}",
        ],
        "lifestyle": [
            "My {timeframe} {routine} Routine",
            "{number} {category} Essentials You Need",
            "How I {transformation} in {timeframe}",
            "{activity} Vlog: {description}",
            "What I {action} in a {timeframe}",
        ],
    }
    
    # Power words that boost performance
    POWER_WORDS = {
        "urgency": ["now", "today", "immediately", "finally", "just"],
        "curiosity": ["secret", "hidden", "truth", "real", "actually", "never"],
        "emotion": ["amazing", "incredible", "insane", "shocking", "epic"],
        "value": ["free", "best", "ultimate", "complete", "essential"],
        "exclusivity": ["only", "first", "exclusive", "limited", "rare"],
    }
    
    # Words to avoid (based on analysis)
    WEAK_WORDS = ["very", "really", "just", "stuff", "things", "basically"]
    
    def __init__(self):
        self.niche_patterns = {}
    
    def generate(
        self,
        original_title: str,
        category: str = "general",
        channel_id: Optional[str] = None,
        num_suggestions: int = 5
    ) -> TitleAnalysis:
        """
        Generate optimized title suggestions.
        
        Args:
            original_title: The creator's original title
            category: Video category (gaming, tech, education, etc.)
            channel_id: Optional channel ID for personalized suggestions
            num_suggestions: Number of suggestions to generate
            
        Returns:
            TitleAnalysis with score and suggestions
        """
        # Analyze original title
        original_score = self._score_title(original_title, category)
        strengths = self._find_strengths(original_title)
        weaknesses = self._find_weaknesses(original_title)
        
        # Get niche patterns
        niche_data = self._get_niche_patterns(category)
        
        # Get channel patterns if available
        channel_patterns = None
        if channel_id:
            channel_patterns = self._get_channel_patterns(channel_id)
        
        # Generate suggestions
        suggestions = []
        
        # 1. Template-based suggestions
        template_suggestions = self._generate_from_templates(
            original_title, category, niche_data
        )
        suggestions.extend(template_suggestions)
        
        # 2. Power word additions
        power_suggestions = self._add_power_words(original_title, category)
        suggestions.extend(power_suggestions)
        
        # 3. Structure improvements
        structure_suggestions = self._improve_structure(original_title)
        suggestions.extend(structure_suggestions)
        
        # 4. Channel-specific if available
        if channel_patterns:
            channel_suggestions = self._generate_from_channel_patterns(
                original_title, channel_patterns
            )
            suggestions.extend(channel_suggestions)
        
        # Score and rank suggestions
        for s in suggestions:
            s.score = self._score_title(s.title, category)
        
        # Sort by score, remove duplicates
        seen = set()
        unique_suggestions = []
        for s in sorted(suggestions, key=lambda x: x.score, reverse=True):
            if s.title.lower() not in seen and s.title.lower() != original_title.lower():
                seen.add(s.title.lower())
                unique_suggestions.append(s)
        
        return TitleAnalysis(
            original=original_title,
            score=original_score,
            strengths=strengths,
            weaknesses=weaknesses,
            suggestions=unique_suggestions[:num_suggestions]
        )
    
    def _score_title(self, title: str, category: str) -> float:
        """Score a title 0-100."""
        score = 50.0  # Base score
        title_lower = title.lower()
        
        # Length optimization (40-60 chars is optimal)
        length = len(title)
        if 40 <= length <= 60:
            score += 10
        elif length < 25:
            score -= 10
        elif length > 75:
            score -= 5
        
        # Has number
        if re.search(r'\d', title):
            score += 8
        
        # Power words
        for category_words in self.POWER_WORDS.values():
            for word in category_words:
                if word in title_lower:
                    score += 3
                    break
        
        # Weak words (penalty)
        for word in self.WEAK_WORDS:
            if word in title_lower:
                score -= 3
        
        # Question mark (curiosity)
        if '?' in title:
            score += 5
        
        # Exclamation (energy)
        if '!' in title:
            score += 3
        
        # Brackets (specificity)
        if '[' in title or '(' in title:
            score += 4
        
        # Emotional intensity
        emotional_words = ["amazing", "incredible", "insane", "epic", "shocking"]
        if any(w in title_lower for w in emotional_words):
            score += 5
        
        return min(100, max(0, score))
    
    def _find_strengths(self, title: str) -> List[str]:
        """Find what's working in the title."""
        strengths = []
        title_lower = title.lower()
        
        if re.search(r'\d', title):
            strengths.append("✅ Contains a number (increases CTR)")
        
        if 40 <= len(title) <= 60:
            strengths.append("✅ Optimal length for mobile")
        
        if '?' in title:
            strengths.append("✅ Question creates curiosity")
        
        emotional_words = ["amazing", "incredible", "insane", "epic"]
        if any(w in title_lower for w in emotional_words):
            strengths.append("✅ Emotional language drives clicks")
        
        if any(w in title_lower for w in ["how to", "tutorial", "guide"]):
            strengths.append("✅ Clear value proposition")
        
        return strengths if strengths else ["No major strengths detected"]
    
    def _find_weaknesses(self, title: str) -> List[str]:
        """Find what could be improved."""
        weaknesses = []
        title_lower = title.lower()
        
        if len(title) > 70:
            weaknesses.append("⚠️ Too long - may get truncated")
        elif len(title) < 30:
            weaknesses.append("⚠️ Too short - add more context")
        
        if not re.search(r'\d', title):
            weaknesses.append("⚠️ No numbers - specificity helps")
        
        for word in self.WEAK_WORDS:
            if word in title_lower:
                weaknesses.append(f"⚠️ Weak word '{word}' - try stronger language")
                break
        
        if title == title.lower():
            weaknesses.append("⚠️ No capitalization - harder to read")
        
        if not any(c in title for c in "?!"):
            weaknesses.append("⚠️ No punctuation - add energy or curiosity")
        
        return weaknesses if weaknesses else ["Looking good!"]
    
    def _get_niche_patterns(self, category: str) -> Dict:
        """Get patterns for this niche from database."""
        try:
            from src.features.niche_patterns import NichePatternDiscovery
            discovery = NichePatternDiscovery()
            return discovery.get_patterns_for_category(category)
        except Exception as e:
            logger.debug("title_gen.niche_patterns_failed", category=category, error=str(e))
            return {}
    
    def _get_channel_patterns(self, channel_id: str) -> Optional[Dict]:
        """Get patterns specific to this channel."""
        try:
            with get_session() as session:
                videos = session.query(Video).filter_by(
                    channel_id=channel_id
                ).order_by(Video.view_count.desc()).limit(20).all()
                
                if not videos:
                    return None
                
                channel = session.query(Channel).filter_by(
                    channel_id=channel_id
                ).first()
                
                avg_views = channel.avg_views_per_video if channel else 0
                
                # Find patterns in top performing titles
                top_titles = [v.title for v in videos[:10]]
                
                # Common patterns
                has_number = sum(1 for t in top_titles if re.search(r'\d', t)) / len(top_titles)
                has_question = sum(1 for t in top_titles if '?' in t) / len(top_titles)
                avg_length = np.mean([len(t) for t in top_titles])
                
                return {
                    "top_titles": top_titles,
                    "number_rate": has_number,
                    "question_rate": has_question,
                    "avg_length": avg_length,
                }
        except Exception as e:
            logger.debug("title_gen.channel_patterns_failed", channel_id=channel_id, error=str(e))
            return None
    
    def _generate_from_templates(
        self, 
        original: str, 
        category: str,
        niche_data: Dict
    ) -> List[TitleSuggestion]:
        """Generate content-aware suggestions."""
        suggestions = []
        original_lower = original.lower()
        
        # Detect content type from title
        is_speedrun = any(w in original_lower for w in ['speedrun', 'speed run', 'speed-run', 'any%', 'wr', 'world record'])
        is_challenge = any(w in original_lower for w in ['challenge', 'hardcore', 'hardmode', 'hard mode', 'impossible', 'can i', 'trying to'])
        is_gameplay = any(w in original_lower for w in ['gameplay', 'playthrough', 'let\'s play', 'playing', 'episode', 'ep'])
        is_tutorial = any(w in original_lower for w in ['how to', 'tutorial', 'guide', 'tips', 'learn'])
        is_review = any(w in original_lower for w in ['review', 'worth', 'honest', 'bought', 'tested'])
        is_vs = ' vs ' in original_lower or ' versus ' in original_lower
        
        # Extract game/product name (capitalize properly)
        game = self._extract_subject(original)
        game_cap = game.title()
        
        # Gaming category
        if category.lower() == "gaming":
            if is_speedrun:
                variations = [
                    (f"{game_cap} Speedrun - Can I Beat the World Record?", "Question hook + challenge"),
                    (f"I Speedran {game_cap} and This Happened...", "Story hook + curiosity"),
                    (f"{game_cap} Speedrun in Under 30 Minutes [Personal Best]", "Specific + achievement"),
                    (f"How Fast Can I Beat {game_cap}? (Speedrun)", "Question + clear format"),
                    (f"{game_cap} Any% Speedrun - Full Run Explained", "Technical + educational"),
                ]
            elif is_challenge:
                variations = [
                    (f"Can I Beat {game_cap}? (Hardcore Challenge)", "Question + challenge"),
                    (f"I Tried {game_cap} Hardcore Mode - Here's What Happened", "Story hook"),
                    (f"{game_cap} But It Gets Harder Every Minute", "Escalating challenge format"),
                    (f"Surviving {game_cap} Hardcore - No Deaths Allowed", "Stakes + rules"),
                    (f"{game_cap} Hardcore is IMPOSSIBLE | Full Attempt", "Emotional + complete"),
                ]
            elif is_gameplay:
                variations = [
                    (f"{game_cap} - This Game is INSANE", "Emotional reaction"),
                    (f"Playing {game_cap} for the First Time", "First experience hook"),
                    (f"{game_cap} Full Playthrough (No Commentary)", "Clear format"),
                    (f"I Finally Played {game_cap} and...", "Delayed reaction hook"),
                    (f"{game_cap} Gameplay - Worth Your Time?", "Value question"),
                ]
            else:
                variations = [
                    (f"{game_cap} - You Need to See This", "Curiosity hook"),
                    (f"I Played {game_cap} So You Don't Have To", "Service to viewer"),
                    (f"{game_cap}: Everything You Need to Know", "Comprehensive"),
                    (f"Why {game_cap} is Taking Over YouTube", "Trend hook"),
                    (f"The {game_cap} Video Everyone's Talking About", "Social proof"),
                ]
        
        # Tech category
        elif category.lower() == "tech":
            is_bought = any(w in original_lower for w in ['i bought', 'i tested', 'i tried', 'i got', 'i used'])
            
            if is_bought:
                variations = [
                    (f"I Bought the {game_cap} So You Don't Have To", "Service to viewer"),
                    (f"Is the {game_cap} Actually Worth It? (Honest Review)", "Direct question"),
                    (f"{game_cap} - My Honest Opinion After 2 Weeks", "Time-tested"),
                    (f"I Tested the {game_cap} - Here's the Truth", "Tested + truth"),
                    (f"The {game_cap}: Should YOU Buy It?", "Direct question"),
                ]
            elif is_review:
                variations = [
                    (f"{game_cap} Review - Honest Opinion After 2 Weeks", "Time-tested credibility"),
                    (f"Is the {game_cap} Worth It? (Full Review)", "Direct question"),
                    (f"{game_cap}: The Good, The Bad, The Truth", "Balanced format"),
                    (f"I Used the {game_cap} for 30 Days - Here's My Verdict", "Extended test"),
                    (f"{game_cap} Review - Don't Buy Before Watching This", "Urgency"),
                ]
            elif is_vs:
                variations = [
                    (f"{original.title()} - Ultimate Comparison", "Comprehensive"),
                    (f"{original.title()} | Which Should You Buy?", "Decision help"),
                    (f"I Tested {original.title()} - Clear Winner", "Tested + verdict"),
                    (f"{original.title()} - The REAL Difference", "Insider knowledge"),
                    (f"{original.title()} Comparison - Surprising Results", "Curiosity"),
                ]
            else:
                variations = [
                    (f"{game_cap} - Everything You Need to Know", "Comprehensive"),
                    (f"The Truth About {game_cap}", "Insider hook"),
                    (f"{game_cap} Explained in 10 Minutes", "Time promise"),
                    (f"Why Everyone is Talking About {game_cap}", "Social proof"),
                    (f"{game_cap} - Is It Worth the Hype?", "Hype check"),
                ]
        
        # Education category
        elif category.lower() == "education":
            # Handle "how to X" or "learn X" patterns
            is_how_to = 'how to' in original_lower
            is_learn = original_lower.startswith('learn')
            
            # Extract the actual skill (remove "learn" prefix if present)
            skill = game
            if skill.lower().startswith('learn '):
                skill = skill[6:].strip()
            skill_cap = skill.title()
            
            if is_how_to or is_learn:
                variations = [
                    (f"Learn {skill_cap} in 20 Minutes - Complete Beginner Guide", "Time + level"),
                    (f"{skill_cap} Tutorial for Absolute Beginners", "Clear entry point"),
                    (f"Master {skill_cap} - Full Crash Course", "Mastery promise"),
                    (f"{skill_cap} - Everything You Need to Know", "Comprehensive"),
                    (f"The Only {skill_cap} Tutorial You'll Ever Need", "Definitive"),
                ]
            else:
                variations = [
                    (f"How to {game_cap} (Step by Step)", "Clear instruction"),
                    (f"{game_cap} Explained - Complete Guide", "Comprehensive"),
                    (f"{game_cap} for Beginners - Start Here", "Clear entry point"),
                    (f"Master {game_cap} in One Video", "Promise"),
                    (f"The Ultimate Guide to {game_cap}", "Definitive"),
                ]
        
        # Lifestyle category
        elif category.lower() == "lifestyle":
            is_routine = 'routine' in original_lower
            is_vlog = 'vlog' in original_lower
            
            if is_routine:
                variations = [
                    (f"My {game_cap} (That Actually Works)", "Credibility"),
                    (f"The Perfect {game_cap} - Full Breakdown", "Comprehensive"),
                    (f"{game_cap} That Changed My Life", "Transformation"),
                    (f"Realistic {game_cap} You Can Actually Follow", "Accessibility"),
                    (f"The {game_cap} Nobody Tells You About", "Insider hook"),
                ]
            elif is_vlog:
                variations = [
                    (f"A Day in My Life: {game_cap}", "Format clarity"),
                    (f"{game_cap} - Full Day Behind the Scenes", "BTS hook"),
                    (f"Come With Me: {game_cap}", "Invitation hook"),
                    (f"{game_cap} Vlog - Raw & Unfiltered", "Authenticity"),
                    (f"24 Hours of {game_cap}", "Time frame"),
                ]
            else:
                variations = [
                    (f"My Honest {game_cap} Experience", "Authenticity"),
                    (f"{game_cap} - What Nobody Tells You", "Insider"),
                    (f"I Tried {game_cap} for 30 Days - Results", "Challenge format"),
                    (f"The Truth About {game_cap}", "Honesty hook"),
                    (f"{game_cap} Changed Everything For Me", "Transformation"),
                ]
        
        # Default/Entertainment
        else:
            variations = [
                (f"I Tried {game_cap} and This is What Happened", "Story hook"),
                (f"{game_cap} - The Full Story", "Comprehensive"),
                (f"The Ultimate {game_cap} Experience", "Superlative"),
                (f"{game_cap}: My Honest Thoughts", "Authenticity"),
                (f"Everything You Need to Know About {game_cap}", "Comprehensive"),
            ]
        
        for title, reason in variations:
            suggestions.append(TitleSuggestion(
                title=title,
                score=0,  # Will be calculated
                reason=reason,
                pattern_used="content_aware_template",
                improvements=[f"Optimized for {category} content"]
            ))
        
        return suggestions
    
    def _extract_subject(self, title: str) -> str:
        """Extract the main subject/game/product from title - returns the core topic."""
        title_lower = title.lower().strip()
        original_title = title
        
        # Check for "I bought/tested/tried X so you don't have to" pattern
        bought_match = re.match(r'i\s+(bought|tested|tried|used|got)\s+(?:the\s+)?(?:new\s+)?(.+?)\s+so\s+you', title_lower)
        if bought_match:
            product = bought_match.group(2).strip()
            return product
        
        # Check for "I bought/tried the X" pattern
        bought_match2 = re.match(r'i\s+(bought|tested|tried|used|got)\s+(?:the\s+)?(?:new\s+)?(.+)', title_lower)
        if bought_match2:
            product = bought_match2.group(2).strip()
            # Clean up endings
            product = re.sub(r'\s+(and|so|for|to|-).*', '', product)
            return product if len(product) > 2 else title
        
        # Check for "how to X" pattern - subject is the skill
        how_to_match = re.match(r'how to\s+(.+)', title_lower)
        if how_to_match:
            skill = how_to_match.group(1).strip()
            return skill
        
        # Check for "learn X" pattern  
        learn_match = re.match(r'learn\s+(.+)', title_lower)
        if learn_match:
            subject = learn_match.group(1).strip()
            subject = re.sub(r'\s+(basics?|tutorial|guide|tips)$', '', subject)
            return subject if subject else title
        
        # Check for "my X routine/experience/journey" pattern
        my_match = re.match(r'my\s+(.+?)\s+(routine|experience|journey|story|vlog)$', title_lower)
        if my_match:
            return my_match.group(1) + ' ' + my_match.group(2)
        
        # Check for "X review" pattern
        review_match = re.match(r'(.+?)\s+review', title_lower)
        if review_match:
            return review_match.group(1).strip()
        
        # Check for "speedrun X" or "X speedrun" patterns
        speedrun_match = re.match(r'(?:speed\s*run|speedrun)\s+(.+)', title_lower)
        if speedrun_match:
            game = speedrun_match.group(1).strip()
            game = re.sub(r'\s+(hardmode|hard\s*mode|hardcore|any%|100%).*', '', game)
            return game if len(game) > 2 else title_lower
        
        # Check for "X speedrun/gameplay" suffix
        suffix_match = re.match(r'(.+?)\s+(speedrun|speed\s*run|gameplay|playthrough)', title_lower)
        if suffix_match:
            game = suffix_match.group(1).strip()
            if len(game) > 2:
                return game
        
        # Remove common prefixes
        prefixes = ['i played', 'i tried', 'playing', 'trying', 'let\'s play', 'my', 'the', 'a', 'an']
        for prefix in prefixes:
            if title_lower.startswith(prefix + ' '):
                title_lower = title_lower[len(prefix):].strip()
                break
        
        # Remove common suffixes
        suffixes = ['gameplay', 'playthrough', 'speedrun', 'speed run', 'challenge', 
                    'full', 'complete', 'part 1', 'part 2', 'ep 1', 'episode 1', 'hardmode', 
                    'hard mode', 'hardcore', '- full run', '| full', 'so you don\'t have to',
                    'so you dont have to']
        for suffix in suffixes:
            if title_lower.endswith(' ' + suffix):
                title_lower = title_lower[:-len(suffix)].strip()
            elif ' ' + suffix + ' ' in title_lower:
                title_lower = title_lower.replace(' ' + suffix + ' ', ' ').strip()
        
        # Clean up extra spaces and punctuation
        title_lower = ' '.join(title_lower.split())
        title_lower = title_lower.strip(' -|:')
        
        # If too short, use first meaningful words from original
        if len(title_lower) < 3:
            words = [w for w in original_title.split() if len(w) > 2]
            return words[0] if words else original_title
        
        return title_lower
    
    def _add_power_words(self, original: str, category: str) -> List[TitleSuggestion]:
        """No longer generates separate power word suggestions - templates handle this."""
        # Power words are now built into the content-aware templates
        # This prevents duplicate/low-quality suggestions
        return []
    
    def _improve_structure(self, original: str, category: str = "general") -> List[TitleSuggestion]:
        """Improve the structure of the title intelligently."""
        suggestions = []
        subject = self._extract_subject(original)
        subject_cap = subject.title()
        original_lower = original.lower()
        
        # Don't add generic improvements - they rarely help
        # Instead, offer properly structured alternatives
        
        # If all lowercase, the main issue is capitalization + structure
        if original == original.lower():
            # Proper capitalization with hook
            enhanced = f"{subject_cap} | Full Experience"
            suggestions.append(TitleSuggestion(
                title=enhanced,
                score=0,
                reason="Proper formatting + context",
                pattern_used="structure",
                improvements=["Capitalized title with clear format indicator"]
            ))
        
        return suggestions
    
    def _generate_from_channel_patterns(
        self,
        original: str,
        patterns: Dict
    ) -> List[TitleSuggestion]:
        """Generate suggestions based on what works for this channel."""
        suggestions = []
        
        # If channel's top videos have numbers
        if patterns.get("number_rate", 0) > 0.5:
            if not re.search(r'\d', original):
                enhanced = f"7 {original}"
                suggestions.append(TitleSuggestion(
                    title=enhanced,
                    score=0,
                    reason="Your top videos use numbers",
                    pattern_used="channel_pattern",
                    improvements=["Matches your proven formula"]
                ))
        
        # If channel's top videos use questions
        if patterns.get("question_rate", 0) > 0.3:
            if '?' not in original:
                enhanced = f"Can You {original}?"
                suggestions.append(TitleSuggestion(
                    title=enhanced,
                    score=0,
                    reason="Your top videos use questions",
                    pattern_used="channel_pattern",
                    improvements=["Matches your proven formula"]
                ))
        
        return suggestions


def generate_titles(
    original: str,
    category: str = "general",
    channel_id: str = None
) -> TitleAnalysis:
    """
    Convenience function to generate title suggestions.
    
    Args:
        original: Original title
        category: Video category
        channel_id: Optional channel ID
        
    Returns:
        TitleAnalysis with suggestions
    """
    generator = SmartTitleGenerator()
    return generator.generate(original, category, channel_id)

