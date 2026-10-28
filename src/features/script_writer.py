"""
AI Script Writer - Generate full video scripts using Claude (with Groq fallback) + niche patterns.

Features:
- Hook generation (5 proven hook types per niche)
- Full script structure (intro, sections, CTA, outro)
- Niche-specific language patterns
- Customizable length and style
- Timestamp suggestions
"""

import os
import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum

import structlog

from src.features.llm_client import get_llm_client, LLMClient

logger = structlog.get_logger()


class ScriptStyle(Enum):
    """Script tone/style options."""
    CASUAL = "casual"  # Conversational, like talking to a friend
    PROFESSIONAL = "professional"  # Polished, authoritative
    ENERGETIC = "energetic"  # High energy, enthusiastic
    EDUCATIONAL = "educational"  # Clear, structured teaching
    STORYTELLING = "storytelling"  # Narrative-driven


class HookType(Enum):
    """Types of video hooks."""
    QUESTION = "question"  # Start with a thought-provoking question
    BOLD_CLAIM = "bold_claim"  # Make a surprising statement
    STORY = "story"  # Begin with a personal anecdote
    STATISTIC = "statistic"  # Lead with a compelling number
    PROBLEM = "problem"  # Present a relatable problem
    TEASER = "teaser"  # Show the end result first


@dataclass
class ScriptSection:
    """A section of the video script."""
    title: str
    content: str
    duration_estimate: int  # seconds
    notes: str = ""  # Production notes (B-roll suggestions, etc.)


@dataclass
class VideoScript:
    """Complete video script."""
    title: str
    hook: str
    hook_type: HookType
    intro: str
    sections: List[ScriptSection]
    cta: str
    outro: str
    
    # Metadata
    total_duration: int  # seconds
    word_count: int
    style: ScriptStyle
    category: str
    
    # Extras
    thumbnail_ideas: List[str] = field(default_factory=list)
    title_alternatives: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    
    def to_full_script(self) -> str:
        """Get the complete script as a single string."""
        lines = []
        lines.append(f"# {self.title}\n")
        lines.append(f"**Total Duration:** ~{self.total_duration // 60}:{self.total_duration % 60:02d}")
        lines.append(f"**Word Count:** {self.word_count}")
        lines.append(f"**Style:** {self.style.value.title()}\n")
        lines.append("---\n")
        
        lines.append("## 🎣 HOOK (0:00 - 0:10)\n")
        lines.append(self.hook)
        lines.append("\n---\n")
        
        lines.append("## 📺 INTRO (0:10 - 0:30)\n")
        lines.append(self.intro)
        lines.append("\n---\n")
        
        timestamp = 30
        for i, section in enumerate(self.sections, 1):
            start = f"{timestamp // 60}:{timestamp % 60:02d}"
            end_time = timestamp + section.duration_estimate
            end = f"{end_time // 60}:{end_time % 60:02d}"
            
            lines.append(f"## 📌 SECTION {i}: {section.title} ({start} - {end})\n")
            lines.append(section.content)
            if section.notes:
                lines.append(f"\n*[Production Note: {section.notes}]*")
            lines.append("\n---\n")
            
            timestamp = end_time
        
        lines.append(f"## 🔔 CALL TO ACTION ({timestamp // 60}:{timestamp % 60:02d})\n")
        lines.append(self.cta)
        lines.append("\n---\n")
        
        lines.append("## 👋 OUTRO\n")
        lines.append(self.outro)
        
        if self.thumbnail_ideas:
            lines.append("\n---\n")
            lines.append("## 🖼️ THUMBNAIL IDEAS\n")
            for idea in self.thumbnail_ideas:
                lines.append(f"- {idea}")
        
        if self.title_alternatives:
            lines.append("\n---\n")
            lines.append("## ✏️ ALTERNATIVE TITLES\n")
            for title in self.title_alternatives:
                lines.append(f"- {title}")
        
        return "\n".join(lines)
    
    def to_teleprompter(self) -> str:
        """Get script formatted for teleprompter (large text, no formatting)."""
        lines = []
        lines.append(self.hook.upper())
        lines.append("\n\n---\n\n")
        lines.append(self.intro)
        lines.append("\n\n---\n\n")
        
        for section in self.sections:
            lines.append(section.content)
            lines.append("\n\n---\n\n")
        
        lines.append(self.cta)
        lines.append("\n\n---\n\n")
        lines.append(self.outro)
        
        return "\n".join(lines)


class ScriptWriter:
    """
    AI-powered script writer using Claude with Groq fallback.
    
    Generates complete video scripts with:
    - Proven hook patterns for your niche
    - Structured sections with timestamps
    - CTAs and outros
    - Production notes
    """
    
    def __init__(self):
        """Initialize the script writer."""
        self.llm_client = get_llm_client()
        
        # Try to get API key from settings (loads from .env) first, then fallback to os.getenv
        try:
            from src.config import get_settings
            settings = get_settings()
            self.api_key = settings.anthropic_api_key or os.getenv("GROQ_API_KEY")
        except Exception as e:
            logger.debug("script_writer.settings_load_failed", error=str(e))
            self.api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("GROQ_API_KEY")
        
        if not self.api_key:
            logger.warning("No LLM API key set, script generation will use fallback")
        else:
            logger.info("ScriptWriter initialized with LLM API (Anthropic + Groq fallback)")
        
        # Niche-specific patterns (from our data)
        self._niche_patterns = {
            "gaming": {
                "hooks": {
                    HookType.BOLD_CLAIM: "This is the {adjective} {thing} in {game}...",
                    HookType.QUESTION: "What if I told you there's a way to {benefit} in {game}?",
                    HookType.TEASER: "*shows insane moment* This is what happens when you...",
                    HookType.PROBLEM: "Everyone's been playing {game} wrong. Here's why.",
                    HookType.STORY: "So I was just grinding {game} when THIS happened...",
                },
                "power_words": ["insane", "broken", "secret", "nobody knows", "world record", "impossible"],
                "cta_style": "smash that like button",
                "avg_section_duration": 90,
                "style_preference": ScriptStyle.ENERGETIC,
            },
            "tech": {
                "hooks": {
                    HookType.BOLD_CLAIM: "This {product} changes everything.",
                    HookType.QUESTION: "Is the {product} actually worth {price}?",
                    HookType.STATISTIC: "{stat}% of people don't know about this feature...",
                    HookType.PROBLEM: "The biggest problem with {product} that nobody talks about.",
                    HookType.TEASER: "After 30 days with the {product}, here's my honest verdict.",
                },
                "power_words": ["honest", "real world", "actually", "the truth", "game changer", "worth it"],
                "cta_style": "subscribe for more honest reviews",
                "avg_section_duration": 120,
                "style_preference": ScriptStyle.PROFESSIONAL,
            },
            "education": {
                "hooks": {
                    HookType.QUESTION: "Have you ever wondered why {topic}?",
                    HookType.BOLD_CLAIM: "Everything you know about {topic} is wrong.",
                    HookType.STATISTIC: "{stat}% of people fail at {topic} because of this one mistake.",
                    HookType.PROBLEM: "The reason you're struggling with {topic}...",
                    HookType.STORY: "I failed at {topic} for years until I discovered this...",
                },
                "power_words": ["simple", "step by step", "beginner", "finally understand", "the truth", "mistake"],
                "cta_style": "subscribe to learn something new every week",
                "avg_section_duration": 150,
                "style_preference": ScriptStyle.EDUCATIONAL,
            },
            "lifestyle": {
                "hooks": {
                    HookType.STORY: "This completely changed my {aspect of life}...",
                    HookType.QUESTION: "What if you could {benefit} without {common obstacle}?",
                    HookType.TEASER: "*shows transformation* Here's exactly how I did it.",
                    HookType.PROBLEM: "I was stuck in {situation} until I tried this...",
                    HookType.BOLD_CLAIM: "The {habit/routine} that changed my life.",
                },
                "power_words": ["changed my life", "game changer", "you need to try", "honest", "routine", "habit"],
                "cta_style": "join the community",
                "avg_section_duration": 100,
                "style_preference": ScriptStyle.CASUAL,
            },
            "entertainment": {
                "hooks": {
                    HookType.TEASER: "*shows crazy moment* How did we get here? Let me explain...",
                    HookType.BOLD_CLAIM: "This is the most {adjective} thing I've ever {verb}.",
                    HookType.QUESTION: "What happens when you {crazy scenario}?",
                    HookType.STORY: "So this is the story of how I {crazy thing}...",
                    HookType.PROBLEM: "Nobody warned me about what was about to happen...",
                },
                "power_words": ["insane", "you won't believe", "crazy", "epic", "hilarious", "gone wrong"],
                "cta_style": "smash like if you enjoyed this chaos",
                "avg_section_duration": 60,
                "style_preference": ScriptStyle.ENERGETIC,
            },
            "finance": {
                "hooks": {
                    HookType.STATISTIC: "I made ${amount} in {timeframe} doing this...",
                    HookType.QUESTION: "Want to know how to {financial goal} in {timeframe}?",
                    HookType.BOLD_CLAIM: "This is the {thing} that made me financially free.",
                    HookType.PROBLEM: "The money mistake that's costing you ${amount} a year.",
                    HookType.STORY: "I went from ${amount} in debt to ${amount} in savings. Here's how.",
                },
                "power_words": ["passive income", "side hustle", "financial freedom", "wealth", "investing", "money mistake"],
                "cta_style": "subscribe for more money tips",
                "avg_section_duration": 120,
                "style_preference": ScriptStyle.PROFESSIONAL,
            },
        }
        
        # Default for unknown categories
        self._default_patterns = {
            "hooks": {
                HookType.QUESTION: "Have you ever wondered about {topic}?",
                HookType.BOLD_CLAIM: "This is going to change everything you know about {topic}.",
                HookType.STORY: "Let me tell you about the time I {action}...",
                HookType.STATISTIC: "Did you know that {stat}?",
                HookType.PROBLEM: "The biggest problem with {topic} that nobody talks about.",
            },
            "power_words": ["secret", "truth", "amazing", "simple", "powerful", "incredible"],
            "cta_style": "subscribe for more",
            "avg_section_duration": 90,
            "style_preference": ScriptStyle.CASUAL,
        }
    
    def generate_script(
        self,
        topic: str,
        category: str = "general",
        target_duration: int = 480,  # 8 minutes default
        style: Optional[ScriptStyle] = None,
        hook_type: Optional[HookType] = None,
        num_sections: int = 4,
        include_timestamps: bool = True,
        additional_context: str = "",
        # Budget attribution. When provided, the LLM call is metered
        # against the user's daily $ cap; ``None`` routes to the
        # platform-wide anonymous bucket (see llm_client.py).
        user_id: Optional[int] = None,
        plan: str = "free",
    ) -> VideoScript:
        """
        Generate a complete video script.
        
        Args:
            topic: The main topic/title of the video
            category: Content category (gaming, tech, education, etc.)
            target_duration: Target video length in seconds
            style: Script style/tone
            hook_type: Preferred hook type (or auto-select)
            num_sections: Number of main content sections
            include_timestamps: Include timestamp markers
            additional_context: Extra instructions for the AI
            
        Returns:
            Complete VideoScript object
        """
        logger.info(f"Generating script for: {topic} ({category})")
        
        # Get niche patterns
        patterns = self._niche_patterns.get(category.lower(), self._default_patterns)
        
        # Use niche-preferred style if not specified
        if style is None:
            style = patterns.get("style_preference", ScriptStyle.CASUAL)
        
        # Auto-select hook type if not specified
        if hook_type is None:
            hook_type = self._select_best_hook_type(topic, category)
        
        # Calculate section duration
        intro_duration = 20
        hook_duration = 10
        cta_duration = 20
        outro_duration = 15
        main_content_duration = target_duration - intro_duration - hook_duration - cta_duration - outro_duration
        section_duration = main_content_duration // num_sections
        
        # Generate with Claude
        try:
            script_data = self._generate_with_claude(
                topic=topic,
                category=category,
                patterns=patterns,
                style=style,
                hook_type=hook_type,
                num_sections=num_sections,
                section_duration=section_duration,
                additional_context=additional_context,
                user_id=user_id,
                plan=plan,
            )
        except Exception as e:
            logger.error(f"Claude generation failed: {e}")
            # Fallback to template-based generation
            script_data = self._generate_from_templates(
                topic=topic,
                category=category,
                patterns=patterns,
                style=style,
                hook_type=hook_type,
                num_sections=num_sections,
                section_duration=section_duration,
            )
        
        # Build VideoScript object
        sections = []
        for i, section_data in enumerate(script_data.get("sections", [])):
            sections.append(ScriptSection(
                title=section_data.get("title", f"Section {i+1}"),
                content=section_data.get("content", ""),
                duration_estimate=section_data.get("duration", section_duration),
                notes=section_data.get("notes", ""),
            ))
        
        # Calculate totals
        total_duration = hook_duration + intro_duration + sum(s.duration_estimate for s in sections) + cta_duration + outro_duration
        full_text = script_data.get("hook", "") + script_data.get("intro", "") + \
                   " ".join(s.content for s in sections) + script_data.get("cta", "") + script_data.get("outro", "")
        word_count = len(full_text.split())
        
        return VideoScript(
            title=topic,
            hook=script_data.get("hook", ""),
            hook_type=hook_type,
            intro=script_data.get("intro", ""),
            sections=sections,
            cta=script_data.get("cta", ""),
            outro=script_data.get("outro", ""),
            total_duration=total_duration,
            word_count=word_count,
            style=style,
            category=category,
            thumbnail_ideas=script_data.get("thumbnail_ideas", []),
            title_alternatives=script_data.get("title_alternatives", []),
            keywords=script_data.get("keywords", []),
        )
    
    def generate_hook_variations(
        self,
        topic: str,
        category: str = "general",
        num_variations: int = 5,
    ) -> List[Dict[str, str]]:
        """
        Generate multiple hook variations for A/B testing.
        
        Returns list of dicts with 'hook_type', 'hook_text', 'strength'.
        """
        patterns = self._niche_patterns.get(category.lower(), self._default_patterns)
        hooks = []
        
        for hook_type in HookType:
            template = patterns["hooks"].get(hook_type)
            if template:
                # Generate hook using Claude
                hook_text = self._generate_single_hook(topic, hook_type, patterns)
                hooks.append({
                    "hook_type": hook_type.value,
                    "hook_text": hook_text,
                    "strength": self._assess_hook_strength(hook_text, category),
                })
        
        # Sort by strength
        hooks.sort(key=lambda x: x["strength"], reverse=True)
        
        return hooks[:num_variations]
    
    def _generate_with_claude(
        self,
        topic: str,
        category: str,
        patterns: Dict,
        style: ScriptStyle,
        hook_type: HookType,
        num_sections: int,
        section_duration: int,
        additional_context: str,
        user_id: Optional[int] = None,
        plan: str = "free",
    ) -> Dict:
        """Generate script using LLM API with fallback."""
        # Build prompt with niche patterns
        power_words = ", ".join(patterns.get("power_words", []))
        hook_template = patterns["hooks"].get(hook_type, "")
        cta_style = patterns.get("cta_style", "subscribe")
        
        style_instructions = {
            ScriptStyle.CASUAL: "Write in a conversational, friendly tone like talking to a friend. Use contractions, casual language, and natural pauses.",
            ScriptStyle.PROFESSIONAL: "Write in a polished, authoritative tone. Be clear and confident, but not stuffy. Back up claims with reasoning.",
            ScriptStyle.ENERGETIC: "Write with HIGH ENERGY! Use exclamation points, dramatic pauses, and exciting language. Keep the momentum up.",
            ScriptStyle.EDUCATIONAL: "Write clearly and pedagogically. Break down complex ideas, use analogies, and build understanding step by step.",
            ScriptStyle.STORYTELLING: "Write as a narrative. Use story structure, build tension, include characters/scenarios, and create emotional connection.",
        }
        
        system_prompt = f"You are an expert YouTube script writer specializing in {category} content."
        
        user_prompt = f"""Write a complete video script for the topic: "{topic}"

REQUIREMENTS:
- Style: {style.value} - {style_instructions[style]}
- Hook Type: {hook_type.value}
- Number of sections: {num_sections}
- Each section should be ~{section_duration} seconds (~{section_duration * 2.5:.0f} words)
- Total script length: ~{num_sections * section_duration + 60} seconds

NICHE-SPECIFIC PATTERNS (use these - they work in {category}):
- Power words: {power_words}
- CTA style: "{cta_style}"
- Hook template inspiration: "{hook_template}"

{f"ADDITIONAL CONTEXT: {additional_context}" if additional_context else ""}

OUTPUT FORMAT (respond in this exact JSON structure):
{{
    "hook": "The opening 10 seconds - grab attention immediately",
    "intro": "Brief intro ~20 seconds - what they'll learn, why it matters",
    "sections": [
        {{
            "title": "Section title",
            "content": "Full script for this section",
            "duration": {section_duration},
            "notes": "Production notes (B-roll ideas, visuals, emphasis)"
        }}
    ],
    "cta": "Call to action - natural, not pushy",
    "outro": "Brief sign-off with personality",
    "thumbnail_ideas": ["idea 1", "idea 2", "idea 3"],
    "title_alternatives": ["alt title 1", "alt title 2", "alt title 3"],
    "keywords": ["keyword1", "keyword2", "keyword3"]
}}

Write the script now. Make it engaging, natural, and optimized for YouTube retention."""

        # Use unified LLM client with fallback. Feature tag + user_id
        # let the budget tracker attribute spend correctly.
        response = self.llm_client.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=4000,
            temperature=0.7,
            user_id=user_id,
            plan=plan,
            feature="script_writer.generate_script",
        )
        
        if not response.success:
            logger.warning(f"LLM generation failed: {response.error}")
            raise Exception(response.error)
        
        logger.info(f"Script generated using {response.provider}/{response.model}")
        response_text = response.text
        
        # Extract JSON from response
        try:
            # Try to find JSON in the response
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start >= 0 and end > start:
                json_str = response_text[start:end]
                return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        
        # If JSON parsing fails, try to extract sections manually
        logger.warning("Could not parse JSON response, using text extraction")
        return self._parse_text_response(response_text, num_sections)
    
    def _generate_from_templates(
        self,
        topic: str,
        category: str,
        patterns: Dict,
        style: ScriptStyle,
        hook_type: HookType,
        num_sections: int,
        section_duration: int,
    ) -> Dict:
        """Fallback template-based generation when Claude is unavailable."""
        
        # Generate hook from template
        hook_template = patterns["hooks"].get(hook_type, "")
        hook = hook_template.replace("{topic}", topic).replace("{thing}", topic)
        
        # Generate basic sections
        section_titles = [
            f"What is {topic}",
            f"Why {topic} matters",
            f"How to {topic.lower()}",
            f"Common mistakes with {topic}",
            f"My experience with {topic}",
            f"Best tips for {topic}",
        ]
        
        sections = []
        for i in range(min(num_sections, len(section_titles))):
            sections.append({
                "title": section_titles[i],
                "content": f"[Content for: {section_titles[i]}]\n\nAdd your detailed content here about {topic}.",
                "duration": section_duration,
                "notes": "Add B-roll and visuals",
            })
        
        return {
            "hook": hook if hook != hook_template else f"Let's talk about {topic}...",
            "intro": f"In this video, I'm going to show you everything you need to know about {topic}. Stay until the end because the last tip is the most important.",
            "sections": sections,
            "cta": f"If you found this helpful, {patterns.get('cta_style', 'subscribe for more')}.",
            "outro": "Thanks for watching! See you in the next one.",
            "thumbnail_ideas": [f"Excited face + '{topic}'", f"Before/after of {topic}", f"'{topic}?' with arrow"],
            "title_alternatives": [f"The Truth About {topic}", f"{topic} Explained", f"Everything About {topic}"],
            "keywords": [topic.lower()] + topic.lower().split()[:3],
        }
    
    def _select_best_hook_type(self, topic: str, category: str) -> HookType:
        """Auto-select the best hook type based on topic and category."""
        topic_lower = topic.lower()
        
        # Check for question indicators
        if any(word in topic_lower for word in ["how", "why", "what", "when", "should"]):
            return HookType.QUESTION
        
        # Check for story indicators
        if any(word in topic_lower for word in ["my", "i ", "story", "experience", "journey"]):
            return HookType.STORY
        
        # Check for number/stat indicators
        if any(char.isdigit() for char in topic):
            return HookType.STATISTIC
        
        # Check for problem indicators
        if any(word in topic_lower for word in ["mistake", "wrong", "problem", "avoid", "stop"]):
            return HookType.PROBLEM
        
        # Check for reveal/result indicators
        if any(word in topic_lower for word in ["result", "reveal", "happened", "transformation"]):
            return HookType.TEASER
        
        # Default to bold claim (works for most content)
        return HookType.BOLD_CLAIM
    
    def _generate_single_hook(self, topic: str, hook_type: HookType, patterns: Dict) -> str:
        """Generate a single hook of the specified type."""
        template = patterns["hooks"].get(hook_type, "")
        
        if not template:
            return f"Let's talk about {topic}..."
        
        # Simple template filling
        hook = template.replace("{topic}", topic).replace("{thing}", topic)
        hook = hook.replace("{game}", topic).replace("{product}", topic)
        hook = hook.replace("{benefit}", "achieve amazing results")
        hook = hook.replace("{adjective}", "most insane")
        hook = hook.replace("{stat}", "90")
        hook = hook.replace("{price}", "$999")
        
        return hook
    
    def _assess_hook_strength(self, hook_text: str, category: str) -> float:
        """Assess hook strength (0-100)."""
        score = 50.0  # Base score
        
        patterns = self._niche_patterns.get(category.lower(), self._default_patterns)
        power_words = patterns.get("power_words", [])
        
        # Check for power words
        hook_lower = hook_text.lower()
        for word in power_words:
            if word in hook_lower:
                score += 10
        
        # Check for question (engagement)
        if "?" in hook_text:
            score += 5
        
        # Check for specificity (numbers)
        if any(char.isdigit() for char in hook_text):
            score += 5
        
        # Penalize if too long
        if len(hook_text) > 200:
            score -= 10
        
        # Penalize if too short
        if len(hook_text) < 30:
            score -= 10
        
        return min(100, max(0, score))
    
    def _parse_text_response(self, response: str, num_sections: int) -> Dict:
        """Parse a text response when JSON parsing fails."""
        lines = response.split('\n')
        
        sections = []
        current_section = None
        current_content = []
        
        for line in lines:
            if line.startswith('#') or line.startswith('**'):
                if current_section and current_content:
                    sections.append({
                        "title": current_section,
                        "content": '\n'.join(current_content),
                        "duration": 90,
                        "notes": "",
                    })
                current_section = line.strip('#* ')
                current_content = []
            else:
                current_content.append(line)
        
        # Add last section
        if current_section and current_content:
            sections.append({
                "title": current_section,
                "content": '\n'.join(current_content),
                "duration": 90,
                "notes": "",
            })
        
        return {
            "hook": sections[0]["content"] if sections else "Let's get started...",
            "intro": sections[1]["content"] if len(sections) > 1 else "",
            "sections": sections[2:num_sections+2] if len(sections) > 2 else [],
            "cta": "If you found this helpful, subscribe for more!",
            "outro": "Thanks for watching!",
            "thumbnail_ideas": [],
            "title_alternatives": [],
            "keywords": [],
        }


# ==================== Viral Frameworks ====================
# Based on Chris Girbu's framework system for engineered virality.
# Each framework has a clear primary goal (trust, saves, retention, leads).


class ScriptFramework(str, Enum):
    """Viral script frameworks - each engineered for a specific goal."""
    AUTHORITY_MYTH_BUSTER = "authority_myth_buster"      # builds trust fast
    DELTA_SHIFT = "delta_shift"                          # drives saves
    PROGRESSIVE_DEBUNKING = "progressive_debunking"      # max watch time
    # Internal slug stays ``hype_heit`` to keep URL params, DB rows,
    # and deep links stable; the user-facing display is
    # "Lead Magnet Framework" — see ``FRAMEWORK_TEMPLATES`` below.
    HYPE_HEIT = "hype_heit"                              # lead generation


FRAMEWORK_TEMPLATES: Dict[ScriptFramework, Dict] = {
    ScriptFramework.AUTHORITY_MYTH_BUSTER: {
        "name": "Authority Myth-Buster",
        "primary_goal": "trust",
        "goal_description": "Build trust fast with new audiences",
        "sections": [
            {"key": "contrarian_hook", "label": "Contrarian Hook", "duration": 8,
             "instruction": "Open by challenging a widely-held belief in this niche. Make the viewer instantly question something they thought was true."},
            {"key": "authority_anchor", "label": "Authority Anchor", "duration": 10,
             "instruction": "Drop credentials immediately - what you've done, built, managed, or achieved that gives you the right to challenge the belief."},
            {"key": "solution_part_1", "label": "Solution Part 1", "duration": 30,
             "instruction": "First of three concrete points. Be specific and actionable."},
            {"key": "solution_part_2", "label": "Solution Part 2", "duration": 30,
             "instruction": "Second concrete point. Build on point 1 or contrast with it."},
            {"key": "solution_part_3", "label": "Solution Part 3", "duration": 30,
             "instruction": "Third concrete point. Often the most important / counterintuitive."},
            {"key": "ideological_cta", "label": "Ideological CTA", "duration": 15,
             "instruction": "Belief-based call to action. Something like: 'If you believe X, follow for more.'"},
        ],
    },
    ScriptFramework.DELTA_SHIFT: {
        "name": "Delta Shift",
        "primary_goal": "saves",
        "goal_description": "Drive saves and shares (highest save rate format)",
        "sections": [
            {"key": "baseline", "label": "Baseline", "duration": 15,
             "instruction": "Show what the AVERAGE person does. Be specific - 'Most creators post 3 times a week and...'"},
            {"key": "delta", "label": "Delta (The Top 1% Move)", "duration": 25,
             "instruction": "Reveal what the TOP 1% does instead. The contrast should be sharp and surprising."},
            {"key": "single_takeaway", "label": "Single Takeaway", "duration": 15,
             "instruction": "ONE immediately actionable thing the viewer can do. Don't list five. One."},
            {"key": "save_cta", "label": "Save CTA", "duration": 5,
             "instruction": "Prompt to save: 'Save this so you don't forget' or similar."},
        ],
    },
    ScriptFramework.PROGRESSIVE_DEBUNKING: {
        "name": "Progressive Debunking (Iceberg)",
        "primary_goal": "retention",
        "goal_description": "Maximize watch time - the viewer keeps expecting the next revelation",
        "sections": [
            {"key": "polarizing_topic", "label": "Polarizing Topic", "duration": 10,
             "instruction": "Pick a hot debate in the niche. State the controversial topic upfront."},
            {"key": "dismiss_surface", "label": "Dismiss the Surface", "duration": 25,
             "instruction": "'Everyone obsesses over X. That's noise.' Dismiss the surface-level tactics that everyone talks about."},
            {"key": "reveal_layer_1", "label": "Reveal Layer 1", "duration": 25,
             "instruction": "'The real mechanic is Y.' First deeper revelation - what people who go a level deeper understand."},
            {"key": "reveal_layer_2", "label": "Reveal Layer 2", "duration": 25,
             "instruction": "'But underneath that is Z.' Even deeper. This is what experts think about."},
            {"key": "final_revelation", "label": "Final Revelation", "duration": 25,
             "instruction": "The deepest truth - what only the top 0.1% understand. Make it feel like insider knowledge."},
            {"key": "loop_back", "label": "Loop Back", "duration": 5,
             "instruction": "End by referencing the polarizing topic from the hook - make the viewer want to rewatch."},
        ],
    },
    ScriptFramework.HYPE_HEIT: {
        "name": "Lead Magnet Framework",
        "primary_goal": "leads",
        "goal_description": "Lead generation - fills auto-DM funnels with keyword CTAs",
        "sections": [
            {"key": "named_system_promise", "label": "Named System Promise", "duration": 8,
             "instruction": "Promise a NAMED system. Invent a short, memorable acronym or label for the method (e.g. 'The [ACRONYM] framework I use to...'). Do NOT reuse generic names — the keyword the viewer will DM you later is this same name, so it must be distinctive."},
            {"key": "blurred_asset_tease", "label": "Blurred Asset Tease", "duration": 10,
             "instruction": "Mention that the deliverable is shown blurred on screen. Tease the asset's value."},
            {"key": "rapid_breakdown_1", "label": "Rapid Breakdown 1", "duration": 15,
             "instruction": "First part of the framework. Quick, punchy, just enough detail to validate."},
            {"key": "rapid_breakdown_2", "label": "Rapid Breakdown 2", "duration": 15,
             "instruction": "Second part. Same energy."},
            {"key": "rapid_breakdown_3", "label": "Rapid Breakdown 3", "duration": 15,
             "instruction": "Third part. Build hunger for the full asset."},
            {"key": "keyword_cta", "label": "Keyword CTA", "duration": 7,
             "instruction": "'Comment KEYWORD and I'll send it to you.' The keyword should match the framework name."},
        ],
    },
}


@dataclass
class FrameworkSection:
    """A section in a framework-based script."""
    key: str
    label: str
    content: str
    duration: int


@dataclass
class FrameworkScript:
    """A script generated using one of the viral frameworks."""
    framework: ScriptFramework
    framework_name: str
    primary_goal: str
    goal_description: str
    topic: str
    sections: List[FrameworkSection]
    estimated_duration_sec: int
    word_count: int
    
    def to_full_script(self) -> str:
        """Format as readable script."""
        lines = [
            f"# {self.topic}",
            f"**Framework:** {self.framework_name}",
            f"**Primary Goal:** {self.primary_goal}",
            f"**Estimated Duration:** {self.estimated_duration_sec}s",
            "",
            "---",
            "",
        ]
        ts = 0
        for section in self.sections:
            mins = ts // 60
            secs = ts % 60
            lines.append(f"## {section.label} ({mins}:{secs:02d})")
            lines.append("")
            lines.append(section.content)
            lines.append("")
            lines.append("---")
            lines.append("")
            ts += section.duration
        return "\n".join(lines)


def generate_framework_script(
    topic: str,
    framework: ScriptFramework,
    target_duration: int = 60,
    additional_context: str = "",
    llm_client: Optional[LLMClient] = None,
    # Budget attribution — see ``ScriptWriter.generate_script`` for why.
    user_id: Optional[int] = None,
    plan: str = "free",
) -> FrameworkScript:
    """
    Generate a script using one of the 4 viral frameworks.
    
    Each framework is engineered for a specific algorithmic goal:
    - AUTHORITY_MYTH_BUSTER: trust building
    - DELTA_SHIFT: save rate
    - PROGRESSIVE_DEBUNKING: retention / watch time
    - HYPE_HEIT (display name "Lead Magnet Framework"): lead generation via keyword CTAs
    """
    if llm_client is None:
        llm_client = get_llm_client()
    
    template = FRAMEWORK_TEMPLATES[framework]
    framework_name = template["name"]
    primary_goal = template["primary_goal"]
    goal_description = template["goal_description"]
    section_specs = template["sections"]
    
    # Scale durations to hit target_duration
    base_total = sum(s["duration"] for s in section_specs)
    scale = target_duration / base_total if base_total > 0 else 1.0
    
    # Build the prompt
    sections_block = "\n".join(
        f"{i+1}. **{s['label']}** (~{int(s['duration'] * scale)}s): {s['instruction']}"
        for i, s in enumerate(section_specs)
    )
    
    system_prompt = (
        f"You are a viral content writer trained on the {framework_name} framework. "
        f"This framework's primary goal is: {goal_description}. "
        "You write tight, punchy scripts with no filler. Every sentence earns its place."
    )
    
    json_keys = ", ".join(f'"{s["key"]}"' for s in section_specs)
    json_template = ",\n  ".join(
        f'"{s["key"]}": "<content for {s["label"]}>"' for s in section_specs
    )
    
    user_prompt = f"""Write a {framework_name} script for this topic:

TOPIC: {topic}

The framework has these sections (write content for each):
{sections_block}

{f"ADDITIONAL CONTEXT: {additional_context}" if additional_context else ""}

Rules:
- Each section's content should match its target duration (about 2.5 words per second)
- No greetings, no "hey guys"
- No section labels in the content - just the spoken words
- Match the energy of viral short-form content (concrete, specific, no filler)

Respond with ONLY valid JSON containing keys: {json_keys}

{{
  {json_template}
}}"""
    
    response = llm_client.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=2000,
        temperature=0.75,
        user_id=user_id,
        plan=plan,
        feature=f"script_writer.framework.{framework.value if hasattr(framework, 'value') else framework}",
    )

    # Parse response
    sections_data: Dict[str, str] = {}
    if response.success:
        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        try:
            # Find JSON object in response
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                sections_data = json.loads(text[start:end])
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse framework script JSON: {e}")
    else:
        logger.warning(f"LLM failed for framework script: {response.error}")
    
    # Build sections (with fallback content if any are missing)
    sections: List[FrameworkSection] = []
    total_duration = 0
    for spec in section_specs:
        scaled_dur = int(spec["duration"] * scale)
        content = sections_data.get(spec["key"], "").strip()
        if not content:
            content = f"[{spec['label']}] {spec['instruction']}"
        sections.append(
            FrameworkSection(
                key=spec["key"],
                label=spec["label"],
                content=content,
                duration=scaled_dur,
            )
        )
        total_duration += scaled_dur
    
    word_count = sum(len(s.content.split()) for s in sections)
    
    return FrameworkScript(
        framework=framework,
        framework_name=framework_name,
        primary_goal=primary_goal,
        goal_description=goal_description,
        topic=topic,
        sections=sections,
        estimated_duration_sec=total_duration,
        word_count=word_count,
    )


def get_framework_info() -> List[Dict]:
    """Return metadata for all 4 frameworks for use in UIs."""
    return [
        {
            "id": fw.value,
            "name": template["name"],
            "primary_goal": template["primary_goal"],
            "goal_description": template["goal_description"],
            "sections": [
                {"key": s["key"], "label": s["label"], "duration": s["duration"]}
                for s in template["sections"]
            ],
        }
        for fw, template in FRAMEWORK_TEMPLATES.items()
    ]


# ==================== Quick Access Functions ====================

def generate_script(topic: str, category: str = "general", duration: int = 480) -> VideoScript:
    """Quick function to generate a video script."""
    writer = ScriptWriter()
    return writer.generate_script(topic, category, duration)


def generate_hooks(topic: str, category: str = "general") -> List[Dict]:
    """Quick function to generate hook variations."""
    writer = ScriptWriter()
    return writer.generate_hook_variations(topic, category)

