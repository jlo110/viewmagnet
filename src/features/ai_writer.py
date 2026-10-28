"""
AI Writing Tools - LLM-Powered with Niche Insights

Uses Claude (with Groq fallback) + YOUR discovered patterns to generate:
- Video descriptions optimized for YOUR niche
- Tags based on what works in YOUR category
- Hook scripts using proven patterns from YOUR data
"""

import re
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime

import structlog

from src.config import get_settings
from src.features.llm_client import get_llm_client

logger = structlog.get_logger(__name__)


@dataclass
class GeneratedDescription:
    """Generated video description."""
    description: str
    word_count: int
    has_timestamps: bool
    has_cta: bool
    seo_keywords: List[str]
    niche_optimizations: List[str]


@dataclass
class GeneratedTags:
    """Generated video tags."""
    tags: List[str]
    primary_tags: List[str]
    secondary_tags: List[str]
    long_tail_tags: List[str]
    total_characters: int
    niche_specific_tags: List[str]


@dataclass
class GeneratedHook:
    """A generated hook script."""
    hook_type: str
    script: str
    duration_seconds: int
    why_it_works: str
    niche_insight: str


@dataclass
class GeneratedHooks:
    """Collection of hook options."""
    title: str
    category: str
    hooks: List[GeneratedHook]
    recommended: GeneratedHook
    recommendation_reason: str


class AIWriter:
    """LLM-powered content generation using Claude (with Groq fallback) + niche patterns."""
    
    def __init__(self):
        self.llm_client = get_llm_client()
        self.niche_patterns = {}
        
        # Check if we have any LLM configured
        settings = get_settings()
        has_anthropic = bool(settings.anthropic_api_key)
        has_groq = bool(settings.groq_api_key if hasattr(settings, 'groq_api_key') else None) or bool(__import__('os').getenv("GROQ_API_KEY"))
        
        if has_anthropic or has_groq:
            print(f"AI Writer: LLM client initialized (Anthropic: {has_anthropic}, Groq fallback: {has_groq})")
        else:
            print("AI Writer: No LLM API keys configured - using fallback generation")
        
        # Load niche patterns
        self._load_niche_patterns()
    
    def _load_niche_patterns(self):
        """Load discovered niche patterns from our data."""
        try:
            from src.features.niche_patterns import NichePatternDiscovery
            discovery = NichePatternDiscovery()
            
            for category in ["Gaming", "Science & Technology", "Education", "Entertainment", "People & Blogs"]:
                try:
                    patterns = discovery.get_patterns_for_category(category)
                    if patterns:
                        self.niche_patterns[category.lower()] = patterns
                except Exception as e:
                    logger.debug("ai_writer.niche_patterns_failed", category=category, error=str(e))
        except Exception as e:
            logger.debug("ai_writer.niche_discovery_failed", error=str(e))
        
        # Fallback patterns based on our analysis
        self.discovered_insights = {
            "gaming": {
                "power_words": ["challenge", "survived", "gameplay", "pvp", "insane"],
                "title_patterns": ["I [verb]ed for [duration]", "[number] [things] that [outcome]"],
                "hook_style": "Jump straight into action, show the payoff first",
                "description_style": "Casual, energetic, game-specific terms, chapter timestamps",
                "avg_title_length": 52,
                "findings": [
                    "Exclamation marks HURT performance (-13%)",
                    "Numbers boost CTR (+8%)",
                    "Challenge format works well (+15%)",
                    "High cuts in first 10s correlate with success"
                ]
            },
            "tech": {
                "power_words": ["review", "honest", "worth it", "comparison", "first look"],
                "title_patterns": ["[Product] Review: [Opinion]", "[Product] vs [Product]"],
                "hook_style": "State the verdict upfront, then explain why",
                "description_style": "Specs-focused, structured, links to products",
                "avg_title_length": 48,
                "findings": [
                    "Questions HURT performance (-6%)",
                    "Music intros boost engagement (+18%)",
                    "Face in first 2 seconds helps (+12%)",
                    "'the first look' phrase = 20x median performance"
                ]
            },
            "education": {
                "power_words": ["how to", "learn", "tutorial", "complete guide", "step by step"],
                "title_patterns": ["How to [skill] in [timeframe]", "[topic] Explained Simply"],
                "hook_style": "Promise clear outcome, show credibility",
                "description_style": "Structured with sections, resource links, timestamps essential",
                "avg_title_length": 55,
                "findings": [
                    "Questions work well (+4%)",
                    "Specific numbers in titles boost CTR",
                    "Longer videos perform better in this niche",
                    "Clear promise = better retention"
                ]
            },
            "entertainment": {
                "power_words": ["reaction", "try", "first time", "challenge", "honest"],
                "title_patterns": ["I Tried [thing] for [duration]", "Reacting to [subject]"],
                "hook_style": "Tease the best moment, create curiosity gap",
                "description_style": "Personality-driven, casual, social links prominent",
                "avg_title_length": 45,
                "findings": [
                    "'first time reaction' = 3.6x median",
                    "Less face time can help (+14%)",
                    "Shock value in thumbnails works",
                    "Shorter, punchier titles win"
                ]
            },
            "lifestyle": {
                "power_words": ["routine", "day in my life", "haul", "aesthetic", "vlog"],
                "title_patterns": ["My [timeframe] [routine]", "[number] [items] You Need"],
                "hook_style": "Cinematic B-roll intro, NOT face-first",
                "description_style": "Personal, product links, aesthetic formatting",
                "avg_title_length": 42,
                "findings": [
                    "Face in first 2s HURTS (-30%)",
                    "High cuts help (+25%)",
                    "Aesthetic thumbnails outperform",
                    "Shorter titles perform better"
                ]
            }
        }
    
    def _get_insights_for_category(self, category: str) -> Dict:
        """Get insights for a category."""
        category_lower = category.lower()
        
        # Map common names to our categories
        category_map = {
            "gaming": "gaming",
            "tech": "tech",
            "technology": "tech",
            "science & technology": "tech",
            "education": "education",
            "entertainment": "entertainment",
            "lifestyle": "lifestyle",
            "people & blogs": "lifestyle",
            "general": "entertainment"
        }
        
        mapped = category_map.get(category_lower, "entertainment")
        return self.discovered_insights.get(mapped, self.discovered_insights["entertainment"])
    
    def _call_claude(
        self,
        prompt: str,
        max_tokens: int = 1500,
        # Plumbed through every AIWriter generator so the LLM call meters
        # against the right user. AIWriter instances should set
        # ``self._budget_user_id`` / ``self._budget_plan`` once at the
        # top-level entry point (router) and every nested call inherits
        # them — keeps callers from having to thread it through 8 layers.
        feature: str = "ai_writer.generic",
    ) -> str:
        """Call LLM API with fallback (Claude -> Synthetic -> Groq)."""
        try:
            print("AI Writer: Calling LLM API...")
            response = self.llm_client.generate(
                system_prompt="You are a YouTube content optimization expert.",
                user_prompt=prompt,
                max_tokens=max_tokens,
                temperature=0.7,
                user_id=getattr(self, "_budget_user_id", None),
                plan=getattr(self, "_budget_plan", "free"),
                feature=feature,
            )

            if not response.success:
                print(f"AI Writer: LLM API error - {response.error}")
                return None

            print(f"AI Writer: Response received from {response.provider}/{response.model}")
            return response.text
        except Exception as e:
            print(f"AI Writer: LLM API error - {e}")
            return None

    def set_budget_context(self, user_id: Optional[int], plan: str = "free") -> None:
        """One-time setter the router calls so every downstream
        ``_call_claude`` invocation is attributed. Cleaner than threading
        user_id through every public method signature on AIWriter."""
        self._budget_user_id = user_id
        self._budget_plan = plan
    
    def generate_description(
        self,
        title: str,
        category: str = "general",
        video_summary: str = "",
        include_timestamps: bool = True,
        include_cta: bool = True,
        channel_name: str = ""
    ) -> GeneratedDescription:
        """
        Generate an optimized video description using LLM + niche insights.
        """
        insights = self._get_insights_for_category(category)
        
        prompt = f"""You are a YouTube optimization expert. Generate a video description for this SPECIFIC video.

VIDEO TITLE: "{title}"
CATEGORY: {category}
CHANNEL: {channel_name or "Creator"}
VIDEO SUMMARY: {video_summary or "Not provided - infer from title"}

FIRST, understand what this video is about based on the title:
- If title mentions a place (Japan, Tokyo, etc.) → it's likely travel/experience content
- If title mentions food → it's culinary/food content  
- If title says "how to" → it's tutorial content
- If title has "favorite", "best", "top" → it's list/ranking content

NICHE INSIGHTS FROM OUR DATA:
- Style that works for {category}: {insights['description_style']}
- Key findings: {'; '.join(insights['findings'][:2])}

GENERATE A DESCRIPTION THAT:
1. Opens with a hook sentence SPECIFIC to "{title}" (not generic!)
   - Bad: "In this video I cover everything about..."
   - Good: "From hidden gems in back alleys to famous spots everyone talks about, here's my honest take on..."
   
2. Briefly describes what viewers will see/learn (be specific to the actual content)

{'3. Includes timestamps - make them SPECIFIC to this topic:' + chr(10) + '   Example for Japan food: "0:00 - Intro / 1:00 - Street food finds / 3:00 - Best ramen spot / 5:00 - Surprising favorite"' if include_timestamps else ''}

{'4. Includes a CTA that fits ' + category + ' content' if include_cta else ''}

5. Social links section

6. 3-5 hashtags relevant to THIS specific video topic

RULES:
- Make it sound like a real person wrote it, not a template
- Reference specific things from the title (places, foods, topics)
- Keep it 150-250 words
- Use emojis sparingly

Generate the description now:"""

        llm_response = self._call_claude(prompt)
        
        if llm_response:
            description = llm_response
        else:
            # Fallback if no LLM
            description = self._generate_fallback_description(title, category, insights, include_timestamps, include_cta)
        
        # Extract keywords
        keywords = re.findall(r'#(\w+)', description)
        if not keywords:
            keywords = insights['power_words'][:5]
        
        return GeneratedDescription(
            description=description,
            word_count=len(description.split()),
            has_timestamps=include_timestamps and ("TIMESTAMPS" in description or "0:00" in description),
            has_cta=include_cta,
            seo_keywords=keywords,
            niche_optimizations=insights['findings'][:3]
        )
    
    def generate_tags(
        self,
        title: str,
        category: str = "general",
        channel_name: str = "",
        additional_context: str = ""
    ) -> GeneratedTags:
        """
        Generate optimized video tags using LLM + niche insights.
        """
        insights = self._get_insights_for_category(category)
        
        prompt = f"""You are a YouTube SEO expert. Generate optimal video tags for this SPECIFIC video.

VIDEO TITLE: "{title}"
CATEGORY: {category}
CHANNEL: {channel_name or "Not specified"}
ADDITIONAL CONTEXT: {additional_context or "None"}

FIRST, analyze the title to understand what tags would help:
- What specific topics are mentioned? (Japan, food, travel, etc.)
- What would someone search to find this video?
- What related topics would viewers also be interested in?

Example for "favorite foods in japan":
- PRIMARY: japan food, japanese cuisine, japan travel, what to eat in japan, tokyo food
- SECONDARY: japan travel 2026, japanese street food, best ramen, sushi japan, food tour
- LONG-TAIL: what to eat in tokyo, must try food japan, japan food guide, best japanese food, hidden gems japan food

NOW generate tags for "{title}":

TAG STRATEGY:
1. PRIMARY TAGS (5): Exact topics FROM THIS TITLE - be specific!
2. SECONDARY TAGS (5): Related searches people might do
3. LONG-TAIL TAGS (5): Specific search phrases (3-5 words)

RULES:
- Tags must be RELEVANT to "{title}" specifically
- Total under 500 characters
- Include year ({datetime.now().year}) in 1-2 tags
- NO generic tags like "video" or "youtube"
- NO hashtags, just comma-separated words/phrases

Output format (just the tags, nothing else):
PRIMARY: [5 tags specific to this video]
SECONDARY: [5 related tags]
LONG-TAIL: [5 search phrases]"""

        llm_response = self._call_claude(prompt, max_tokens=500)
        
        if llm_response:
            # Parse LLM response
            primary, secondary, long_tail = self._parse_tags_response(llm_response, title, insights)
        else:
            # Fallback
            primary, secondary, long_tail = self._generate_fallback_tags(title, category, insights, channel_name)
        
        # Combine and dedupe
        all_tags = primary + secondary + long_tail
        all_tags = list(dict.fromkeys(all_tags))
        
        # Enforce 500 char limit
        total_chars = sum(len(t) for t in all_tags) + len(all_tags) - 1
        while total_chars > 500 and all_tags:
            all_tags.pop()
            total_chars = sum(len(t) for t in all_tags) + len(all_tags) - 1
        
        return GeneratedTags(
            tags=all_tags,
            primary_tags=primary[:5],
            secondary_tags=secondary[:5],
            long_tail_tags=long_tail[:5],
            total_characters=total_chars,
            niche_specific_tags=[t for t in all_tags if any(pw in t.lower() for pw in insights['power_words'])]
        )
    
    def generate_hooks(
        self,
        title: str,
        category: str = "general",
        target_duration: int = 15,
        num_options: int = 5
    ) -> GeneratedHooks:
        """
        Generate multiple hook script options using LLM + niche insights.
        """
        insights = self._get_insights_for_category(category)
        
        prompt = f"""You are a YouTube hook expert. Generate {num_options} different hook scripts for this SPECIFIC video.

VIDEO TITLE: "{title}"
CATEGORY: {category}
TARGET DURATION: {target_duration} seconds (about {target_duration * 2.5:.0f} words)

FIRST, understand what this video is about:
- What is the topic? (e.g., if title is "favorite foods in japan" → it's about Japanese cuisine experiences)
- What would viewers expect to see? (food visuals, reactions, recommendations)
- What makes this topic interesting? (cultural experience, taste reactions, hidden gems)

NICHE INSIGHTS FROM OUR DATA:
- Hook style for {category}: {insights['hook_style']}
- Key findings: {'; '.join(insights['findings'][:2])}

NOW generate {num_options} hooks that are SPECIFIC to "{title}":

1. [QUESTION HOOK]
Script: [A question ABOUT THIS SPECIFIC TOPIC - e.g., for Japan food: "What food made me completely rethink everything I knew about Japanese cuisine?"]
Why it works: [1 sentence]

2. [STORY HOOK]  
Script: [A mini-story ABOUT THIS SPECIFIC EXPERIENCE - e.g., "I walked into this tiny restaurant in Tokyo with no English menu, pointed at something random, and what came out changed my life..."]
Why it works: [1 sentence]

3. [SHOCK HOOK]
Script: [A surprising fact ABOUT THIS TOPIC - e.g., "The best food I had in Japan wasn't sushi, ramen, or anything you'd expect..."]
Why it works: [1 sentence]

4. [PROMISE HOOK]
Script: [What viewers will get from THIS video - e.g., "I'm going to show you 5 foods you HAVE to try in Japan - and 2 you should skip"]
Why it works: [1 sentence]

5. [PATTERN INTERRUPT]
Script: [Start with unexpected moment FROM THIS CONTENT - e.g., show yourself taking first bite with reaction, then "Okay, we need to talk about this..."]
Why it works: [1 sentence]

CRITICAL RULES:
- Every hook must be SPECIFICALLY about "{title}" - no generic templates!
- Reference actual things from the topic (foods, places, experiences, etc.)
- Make it sound natural, like you're actually talking about THIS video
- Do NOT use placeholder text like "[topic]" - be specific!

Generate all {num_options} hooks now:"""

        llm_response = self._call_claude(prompt, max_tokens=2000)
        
        if llm_response:
            hooks = self._parse_hooks_response(llm_response, title, category, insights, target_duration)
        else:
            hooks = self._generate_fallback_hooks(title, category, insights, target_duration)
        
        # Select recommended based on niche
        recommended_type = {
            "gaming": "pattern_interrupt",
            "tech": "promise",
            "education": "promise",
            "entertainment": "story",
            "lifestyle": "story"
        }.get(category.lower(), "question")
        
        recommended = hooks[0]  # Default to first
        for h in hooks:
            if recommended_type in h.hook_type.lower():
                recommended = h
                break
        
        return GeneratedHooks(
            title=title,
            category=category,
            hooks=hooks,
            recommended=recommended,
            recommendation_reason=f"Based on our data, '{recommended.hook_type}' hooks work best in {category}. {insights['hook_style']}"
        )
    
    def _parse_tags_response(self, response: str, title: str, insights: Dict) -> tuple:
        """Parse LLM tags response."""
        primary = []
        secondary = []
        long_tail = []
        
        lines = response.strip().split('\n')
        current_type = None
        
        for line in lines:
            line = line.strip()
            if line.startswith('PRIMARY:'):
                current_type = 'primary'
                tags = line.replace('PRIMARY:', '').strip()
            elif line.startswith('SECONDARY:'):
                current_type = 'secondary'
                tags = line.replace('SECONDARY:', '').strip()
            elif line.startswith('LONG-TAIL:'):
                current_type = 'long_tail'
                tags = line.replace('LONG-TAIL:', '').strip()
            else:
                continue
            
            parsed = [t.strip() for t in tags.split(',') if t.strip()]
            
            if current_type == 'primary':
                primary = parsed
            elif current_type == 'secondary':
                secondary = parsed
            elif current_type == 'long_tail':
                long_tail = parsed
        
        # Fallback if parsing failed
        if not primary:
            primary = self._extract_keywords(title)[:5]
        if not secondary:
            secondary = insights['power_words'][:5]
        if not long_tail:
            topic = self._extract_topic(title)
            long_tail = [f"{topic} {datetime.now().year}", f"best {topic}", f"{topic} tutorial"]
        
        return primary, secondary, long_tail
    
    def _parse_hooks_response(self, response: str, title: str, category: str, insights: Dict, duration: int) -> List[GeneratedHook]:
        """Parse LLM hooks response."""
        hooks = []
        
        # Split by hook sections
        sections = re.split(r'\[([A-Z\s]+(?:HOOK|INTERRUPT))\]', response)
        
        i = 1  # Skip first empty section
        while i < len(sections) - 1:
            hook_type = sections[i].strip().lower().replace(' hook', '').replace(' ', '_')
            content = sections[i + 1].strip()
            
            # Extract script and why
            script_match = re.search(r'Script:\s*(.+?)(?=Why it works:|$)', content, re.DOTALL)
            why_match = re.search(r'Why it works:\s*(.+?)(?=---|$)', content, re.DOTALL)
            
            script = script_match.group(1).strip() if script_match else content[:200]
            why = why_match.group(1).strip() if why_match else insights['hook_style']
            
            # Clean up script
            script = script.replace('"', '').replace('"', '').strip()
            
            if script:
                hooks.append(GeneratedHook(
                    hook_type=hook_type,
                    script=script,
                    duration_seconds=duration,
                    why_it_works=why,
                    niche_insight=insights['findings'][0] if insights['findings'] else ""
                ))
            
            i += 2
        
        # Ensure we have at least some hooks
        if len(hooks) < 3:
            hooks.extend(self._generate_fallback_hooks(title, category, insights, duration))
        
        return hooks[:5]
    
    def _generate_fallback_description(self, title: str, category: str, insights: Dict, timestamps: bool, cta: bool) -> str:
        """Generate description without LLM."""
        topic = self._extract_topic(title)
        
        desc = f"""🎬 {title}

{insights['description_style'].split(',')[0]}! In this video, I dive deep into {topic} and share everything you need to know.

"""
        if timestamps:
            desc += """⏱️ TIMESTAMPS:
0:00 - Intro
0:30 - Main Content
[Add your timestamps here]

"""
        if cta:
            ctas = {
                "gaming": "🎮 SMASH that like button if you enjoyed! Subscribe for more gaming content!",
                "tech": "👍 If this helped you decide, like & subscribe for honest tech reviews!",
                "education": "📚 Found this helpful? Like & Subscribe! Drop questions in the comments!",
                "entertainment": "😂 Enjoyed? LIKE and SUBSCRIBE for more!",
                "lifestyle": "✨ If you loved this, give it a thumbs up and join the family!"
            }
            desc += ctas.get(category.lower(), ctas["entertainment"]) + "\n\n"
        
        desc += """📱 CONNECT:
► Instagram: [YOUR_LINK]
► Twitter: [YOUR_LINK]
► Discord: [YOUR_LINK]

"""
        # Add hashtags from power words
        hashtags = ' '.join([f"#{pw.replace(' ', '')}" for pw in insights['power_words'][:4]])
        desc += hashtags
        
        return desc
    
    def _generate_fallback_tags(self, title: str, category: str, insights: Dict, channel: str) -> tuple:
        """Generate tags without LLM."""
        topic = self._extract_topic(title)
        keywords = self._extract_keywords(title)
        
        primary = keywords[:5] if keywords else [topic]
        if channel:
            primary.insert(0, channel)
        
        secondary = insights['power_words'][:5]
        
        long_tail = [
            f"{topic} {datetime.now().year}",
            f"best {topic}",
            f"{topic} tutorial",
            f"how to {topic}",
            f"{topic} tips"
        ]
        
        return primary, secondary, long_tail
    
    def _generate_fallback_hooks(self, title: str, category: str, insights: Dict, duration: int) -> List[GeneratedHook]:
        """Generate content-aware hooks without LLM."""
        topic = self._extract_topic(title)
        
        # Analyze the title to understand context
        title_lower = title.lower()
        
        # Detect content type from title
        is_food = any(w in title_lower for w in ['food', 'eat', 'restaurant', 'cook', 'recipe', 'meal', 'dish'])
        is_travel = any(w in title_lower for w in ['japan', 'tokyo', 'travel', 'trip', 'visit', 'tour', 'country', 'city'])
        is_review = any(w in title_lower for w in ['review', 'honest', 'worth', 'test', 'so you don\'t have to', 'so you dont have to', 'bought', 'tried', 'tested'])
        is_tutorial = any(w in title_lower for w in ['how to', 'tutorial', 'guide', 'learn', 'tips'])
        is_list = any(w in title_lower for w in ['favorite', 'best', 'top', 'worst', 'must'])
        
        # Generate context-aware hooks
        if is_review and not is_food:
            # Review content (tech, products, etc.)
            hooks = [
                GeneratedHook(
                    hook_type="question",
                    script=f"Is the {topic} actually worth your money? I spent my own cash to find out.",
                    duration_seconds=duration,
                    why_it_works="Direct question about purchase decision viewers are considering",
                    niche_insight=insights['hook_style']
                ),
                GeneratedHook(
                    hook_type="story",
                    script=f"I've been using the {topic} for a while now, and I have some thoughts. Some good, some... not so much.",
                    duration_seconds=duration,
                    why_it_works="Teases mixed review, creates curiosity about the negatives",
                    niche_insight=insights['hook_style']
                ),
                GeneratedHook(
                    hook_type="shock",
                    script=f"After using the {topic}, I can tell you right now - it's not what you think. Let me explain.",
                    duration_seconds=duration,
                    why_it_works="Subverts expectations, makes viewers want to know the truth",
                    niche_insight=insights['findings'][0] if insights['findings'] else ""
                ),
                GeneratedHook(
                    hook_type="promise",
                    script=f"Here's my honest verdict on the {topic}: the good, the bad, and whether you should actually buy it.",
                    duration_seconds=duration,
                    why_it_works="Promises comprehensive, honest review - exactly what viewers want",
                    niche_insight=insights['findings'][0] if insights['findings'] else ""
                ),
                GeneratedHook(
                    hook_type="pattern_interrupt",
                    script=f"*holds up the {topic}* Okay, I need to talk about this. Is it worth it? Here's my take.",
                    duration_seconds=duration,
                    why_it_works="Direct, visual opening that gets straight to the point",
                    niche_insight=insights['hook_style']
                )
            ]
        elif is_food and is_travel:
            # Food + Travel content
            hooks = [
                GeneratedHook(
                    hook_type="question",
                    script=f"What's the one dish that completely changed how I think about {topic.split()[-1] if topic.split() else 'food'}?",
                    duration_seconds=duration,
                    why_it_works="Food questions trigger curiosity about taste experiences",
                    niche_insight=insights['hook_style']
                ),
                GeneratedHook(
                    hook_type="story",
                    script="I walked into this tiny place with no expectations, pointed at something on the menu I couldn't read, and what came out... let me just show you.",
                    duration_seconds=duration,
                    why_it_works="Personal food stories are relatable and build anticipation",
                    niche_insight=insights['hook_style']
                ),
                GeneratedHook(
                    hook_type="shock",
                    script="The best thing I ate wasn't what you'd expect. It wasn't the famous stuff everyone talks about...",
                    duration_seconds=duration,
                    why_it_works="Subverting expectations grabs attention",
                    niche_insight=insights['findings'][0] if insights['findings'] else ""
                ),
                GeneratedHook(
                    hook_type="promise",
                    script="I'm going to show you exactly what to eat, where to find it, and what to skip. This is everything I wish I knew before my trip.",
                    duration_seconds=duration,
                    why_it_works="Clear value proposition for viewers planning similar experiences",
                    niche_insight=insights['findings'][0] if insights['findings'] else ""
                ),
                GeneratedHook(
                    hook_type="pattern_interrupt",
                    script="*takes first bite* ...okay we need to talk about this. *intro rolls*",
                    duration_seconds=duration,
                    why_it_works="Starting with the reaction creates immediate curiosity",
                    niche_insight=insights['hook_style']
                )
            ]
        elif is_list:
            # List/favorites content - USE THE ACTUAL TOPIC
            hooks = [
                GeneratedHook(
                    hook_type="question",
                    script=f"Can you guess which {topic} ended up being my absolute favorite? I'll give you a hint - it's not what you'd expect.",
                    duration_seconds=duration,
                    why_it_works="Guessing games engage viewers to watch till the end",
                    niche_insight=insights['hook_style']
                ),
                GeneratedHook(
                    hook_type="story",
                    script=f"I've tried so many {topic}, and I finally figured out which ones actually stand out. Let me share what I learned.",
                    duration_seconds=duration,
                    why_it_works="Personal experience + promise of curated insights",
                    niche_insight=insights['hook_style']
                ),
                GeneratedHook(
                    hook_type="shock",
                    script=f"My number one pick for {topic} is going to surprise you. It's not the one everyone talks about...",
                    duration_seconds=duration,
                    why_it_works="Subverts expectations, creates curiosity",
                    niche_insight=insights['findings'][0] if insights['findings'] else ""
                ),
                GeneratedHook(
                    hook_type="promise",
                    script=f"By the end of this video, you'll know exactly which {topic} are worth it and which ones to skip.",
                    duration_seconds=duration,
                    why_it_works="Clear value: saves viewer time/money",
                    niche_insight=insights['findings'][0] if insights['findings'] else ""
                ),
                GeneratedHook(
                    hook_type="pattern_interrupt",
                    script=f"*showing the top pick* This is my number one {topic}. Here's exactly why.",
                    duration_seconds=duration,
                    why_it_works="Showing the answer first creates curiosity about the reasoning",
                    niche_insight=insights['hook_style']
                )
            ]
        elif is_tutorial:
            # Tutorial content - USE THE ACTUAL TOPIC
            hooks = [
                GeneratedHook(
                    hook_type="question",
                    script=f"What if I told you that most people learn {topic} completely wrong? There's a better way, and I'm going to show you exactly what it is.",
                    duration_seconds=duration,
                    why_it_works="Promises insider knowledge specific to the topic",
                    niche_insight=insights['hook_style']
                ),
                GeneratedHook(
                    hook_type="story",
                    script=f"When I first started learning {topic}, I wasted months doing it the hard way. Here's what I wish someone had told me from the start.",
                    duration_seconds=duration,
                    why_it_works="Personal experience with the specific topic builds trust",
                    niche_insight=insights['hook_style']
                ),
                GeneratedHook(
                    hook_type="shock",
                    script=f"Most {topic} tutorials teach you things you'll never actually use. I'm going to show you what really matters.",
                    duration_seconds=duration,
                    why_it_works="Challenges existing content, positions as 'the real' tutorial",
                    niche_insight=insights['findings'][0] if insights['findings'] else ""
                ),
                GeneratedHook(
                    hook_type="promise",
                    script=f"By the end of this video, you'll understand {topic} well enough to start building real projects. No fluff, no filler - just the concepts that actually matter.",
                    duration_seconds=duration,
                    why_it_works="Clear outcome promise specific to the skill",
                    niche_insight=insights['findings'][0] if insights['findings'] else ""
                ),
                GeneratedHook(
                    hook_type="pattern_interrupt",
                    script=f"*shows working demo/project* This is what you'll be able to build with {topic}. Let me show you how to get there.",
                    duration_seconds=duration,
                    why_it_works="Showing the end result first proves the tutorial delivers",
                    niche_insight=insights['hook_style']
                )
            ]
        else:
            # Generic but MUST include the topic
            hooks = [
                GeneratedHook(
                    hook_type="question",
                    script=f"What's the one thing about {topic} that most people completely miss? Let me break it down for you.",
                    duration_seconds=duration,
                    why_it_works="Questions about specific topic create targeted curiosity",
                    niche_insight=insights['hook_style']
                ),
                GeneratedHook(
                    hook_type="story",
                    script=f"I've been deep into {topic} for a while now, and I need to share what I've learned with you.",
                    duration_seconds=duration,
                    why_it_works="Personal experience with the topic builds credibility",
                    niche_insight=insights['hook_style']
                ),
                GeneratedHook(
                    hook_type="shock",
                    script=f"Everything you think you know about {topic} might be wrong. Here's what's actually going on.",
                    duration_seconds=duration,
                    why_it_works="Challenges assumptions about the specific topic",
                    niche_insight=insights['findings'][0] if insights['findings'] else ""
                ),
                GeneratedHook(
                    hook_type="promise",
                    script=f"By the end of this video, you'll have a complete understanding of {topic}. Let's dive in.",
                    duration_seconds=duration,
                    why_it_works="Clear promise of comprehensive coverage",
                    niche_insight=insights['findings'][0] if insights['findings'] else ""
                ),
                GeneratedHook(
                    hook_type="pattern_interrupt",
                    script=f"*shows key moment or result* This is what {topic} is all about. Let me show you how we got here.",
                    duration_seconds=duration,
                    why_it_works="Leading with payoff creates curiosity about the journey",
                    niche_insight=insights['hook_style']
                )
            ]
        
        return hooks
    
    def _extract_topic(self, title: str) -> str:
        """Extract the ACTUAL SUBJECT from title, not the whole title."""
        title_lower = title.lower()
        
        # Pattern: "I bought/tried/tested X so you don't have to" → topic is X
        match = re.search(r'i (?:bought|tried|tested|used|got|reviewed|spent \w+ on) (?:the |a |an )?(.+?) (?:so you|for \d|and |to see)', title_lower)
        if match:
            return match.group(1).strip()
        
        # Pattern: "X review" or "reviewing X" → topic is X
        match = re.search(r'(.+?) review|reviewing (.+?)(?:\s|$)', title_lower)
        if match:
            return (match.group(1) or match.group(2)).strip()
        
        # Pattern: "is X worth it" → topic is X
        match = re.search(r'is (?:the |a |an )?(.+?) worth', title_lower)
        if match:
            return match.group(1).strip()
        
        # Pattern: "X vs Y" → topic is "X vs Y"
        match = re.search(r'(.+? vs .+?)(?:\s*[-|:]|$)', title_lower)
        if match:
            return match.group(1).strip()
        
        # Pattern: "how to X" → topic is X
        match = re.search(r'how to (.+?)(?:\s+in\s+\d|$)', title_lower)
        if match:
            return match.group(1).strip()
        
        # Pattern: "learn/learning X" → topic is X
        match = re.search(r'learn(?:ing)? (?:everything about |all about |)?(.+)', title_lower)
        if match:
            return match.group(1).strip()
        
        # Pattern: "my favorite X" or "best X" → topic is X
        match = re.search(r'(?:my |the )?(?:favorite|best|worst|top \d+) (.+)', title_lower)
        if match:
            return match.group(1).strip()
        
        # Fallback: Remove common filler phrases and extract key nouns
        topic = title_lower
        fillers = [
            r'^i (?:just |finally |)',
            r' so you don\'?t have to',
            r' and (?:here\'?s what happened|it was \w+)',
            r' - (?:is it worth it|honest review|full review)',
            r'\|.*$',
            r'\[.*?\]',
            r'\(.*?\)',
            r'#\w+',
        ]
        for filler in fillers:
            topic = re.sub(filler, '', topic)
        
        # Get the main noun phrase (first 3-5 meaningful words)
        words = topic.strip().split()
        stop_words = {'the', 'a', 'an', 'this', 'that', 'my', 'your', 'i', 'we', 'they', 'it', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare', 'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 's', 't', 'just', 'don', 'now'}
        
        key_words = [w for w in words if w not in stop_words and len(w) > 2]
        
        if key_words:
            return ' '.join(key_words[:4])
        
        return title[:30]
    
    def _extract_keywords(self, title: str) -> List[str]:
        """Extract keywords from title."""
        words = re.findall(r'\b[a-zA-Z]{3,}\b', title.lower())
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 
                      'for', 'of', 'with', 'is', 'it', 'this', 'that', 'my', 'i', 'you'}
        return [w for w in words if w not in stop_words]


# ============== CONVENIENCE FUNCTIONS ==============

def generate_description(title: str, category: str = "general", **kwargs) -> GeneratedDescription:
    """Generate a video description using LLM + niche insights."""
    writer = AIWriter()
    return writer.generate_description(title, category, **kwargs)


def generate_tags(title: str, category: str = "general", **kwargs) -> GeneratedTags:
    """Generate video tags using LLM + niche insights."""
    writer = AIWriter()
    return writer.generate_tags(title, category, **kwargs)


def generate_hooks(title: str, category: str = "general", **kwargs) -> GeneratedHooks:
    """Generate hook scripts using LLM + niche insights."""
    writer = AIWriter()
    return writer.generate_hooks(title, category, **kwargs)
