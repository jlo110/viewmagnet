"""
YouTube Description Generator

Auto-generates SEO-optimized YouTube descriptions with chapter timestamps
from video transcripts using Claude AI with Groq fallback.
"""

import os
import re
from typing import List, Dict, Optional
from dataclasses import dataclass, field

import structlog

from src.features.llm_client import get_llm_client

logger = structlog.get_logger()


@dataclass
class Chapter:
    """A chapter/timestamp in the video."""
    timestamp: str  # "0:00" format
    title: str
    start_seconds: float = 0.0


@dataclass
class GeneratedDescription:
    """Result of description generation."""
    description: str
    chapters: List[Chapter] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    summary: str = ""
    language: str = "en"
    
    def to_dict(self) -> Dict:
        return {
            "description": self.description,
            "chapters": [
                {"timestamp": c.timestamp, "title": c.title, "start_seconds": c.start_seconds}
                for c in self.chapters
            ],
            "hashtags": self.hashtags,
            "summary": self.summary,
            "language": self.language,
        }


def seconds_to_timestamp(seconds: float) -> str:
    """Convert seconds to YouTube timestamp format (M:SS or H:MM:SS)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def extract_chapters_from_segments(
    segments: List[Dict],
    min_chapter_duration: float = 30.0,
    max_chapters: int = 12
) -> List[Chapter]:
    """
    Extract chapter markers from transcript segments.
    
    Groups segments into logical chapters based on timing and content.
    
    Args:
        segments: List of transcript segments with 'start', 'end', 'text'
        min_chapter_duration: Minimum seconds between chapters
        max_chapters: Maximum number of chapters to create
    
    Returns:
        List of Chapter objects
    """
    if not segments:
        return [Chapter(timestamp="0:00", title="Intro", start_seconds=0)]
    
    chapters = []
    last_chapter_time = 0.0
    
    # Always start with intro
    chapters.append(Chapter(timestamp="0:00", title="Intro", start_seconds=0))
    
    for i, segment in enumerate(segments):
        start = segment.get("start", 0)
        text = segment.get("text", "").strip()
        
        # Check if enough time has passed for a new chapter
        if start - last_chapter_time >= min_chapter_duration:
            # Look for natural chapter break indicators
            lower_text = text.lower()
            
            # Keywords that might indicate a new section
            chapter_keywords = [
                "first", "second", "third", "next", "finally", "now",
                "let's talk", "moving on", "another", "the key",
                "step", "tip", "point", "reason", "way",
            ]
            
            is_chapter_break = any(kw in lower_text for kw in chapter_keywords)
            
            # Also create chapters at regular intervals if we haven't hit max
            should_create = is_chapter_break or (
                len(chapters) < max_chapters // 2 and 
                start - last_chapter_time >= min_chapter_duration * 2
            )
            
            if should_create and len(chapters) < max_chapters:
                # Generate chapter title from first few words
                words = text.split()[:6]
                title = " ".join(words)
                if len(title) > 40:
                    title = title[:37] + "..."
                
                chapters.append(Chapter(
                    timestamp=seconds_to_timestamp(start),
                    title=title.capitalize(),
                    start_seconds=start
                ))
                last_chapter_time = start
    
    return chapters


class DescriptionGenerator:
    """
    Generates YouTube descriptions using Claude AI with Groq fallback.
    
    Creates SEO-optimized descriptions with hooks, CTAs,
    chapter timestamps, and hashtags.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the description generator.
        
        Args:
            api_key: Anthropic API key (optional, will use shared LLM client)
        """
        self.llm_client = get_llm_client()
        # Keep legacy api_key for compatibility
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            logger.warning("No LLM API key configured (ANTHROPIC_API_KEY or GROQ_API_KEY)")
        # See HookLab.set_budget_context.
        self._budget_user_id: Optional[int] = None
        self._budget_plan: str = "free"

    def set_budget_context(self, user_id: Optional[int], plan: str = "free") -> None:
        self._budget_user_id = user_id
        self._budget_plan = plan
    
    def generate(
        self,
        title: str,
        transcript: Optional[str] = None,
        transcript_segments: Optional[List[Dict]] = None,
        language: str = "en",
        video_duration: Optional[float] = None,
        include_chapters: bool = True,
        include_hashtags: bool = True,
    ) -> GeneratedDescription:
        """
        Generate a YouTube description from video content.
        
        Args:
            title: Video title
            transcript: Full transcript text
            transcript_segments: Segments with timestamps
            language: Content language code
            video_duration: Video duration in seconds
            include_chapters: Whether to generate chapters
            include_hashtags: Whether to include hashtags
        
        Returns:
            GeneratedDescription with all components
        """
        # Extract chapters from segments if available
        chapters = []
        if include_chapters and transcript_segments:
            chapters = extract_chapters_from_segments(
                transcript_segments,
                min_chapter_duration=30.0 if video_duration and video_duration < 300 else 60.0
            )
        
        # Get video duration from segments if not provided
        if video_duration is None and transcript_segments:
            last_seg = transcript_segments[-1]
            video_duration = last_seg.get("end", last_seg.get("start", 0))
        
        if not self.api_key:
            logger.warning("No API key, generating basic description")
            return self._generate_basic_description(
                title, transcript, chapters, language
            )
        
        try:
            # Prepare transcript excerpt
            transcript_text = transcript or ""
            if transcript_segments:
                transcript_text = " ".join(
                    seg.get("text", "") for seg in transcript_segments[:50]
                )
            transcript_excerpt = transcript_text[:3000]
            
            # Format chapters for prompt
            chapters_text = ""
            if chapters:
                chapters_text = "\n".join(
                    f"{c.timestamp} {c.title}" for c in chapters
                )
            
            # Duration string
            duration_str = ""
            if video_duration:
                mins = int(video_duration // 60)
                secs = int(video_duration % 60)
                duration_str = f"{mins}:{secs:02d}"
            
            system_prompt = "You are a YouTube SEO expert who creates engaging, optimized video descriptions."
            
            user_prompt = f"""Generate a complete YouTube video description that will maximize engagement and SEO.

VIDEO TITLE: "{title}"
VIDEO LANGUAGE: {language}
VIDEO DURATION: {duration_str}

TRANSCRIPT EXCERPT:
{transcript_excerpt}

{"SUGGESTED CHAPTERS:" if chapters_text else ""}
{chapters_text}

REQUIREMENTS:
1. Write the description in {language.upper()}
2. Start with a compelling 2-3 sentence hook/summary
3. Add relevant CTAs (subscribe, like, comment, share)
4. {"Include the chapter timestamps in their own section" if chapters else "Do not include chapters"}
5. {"Add 5-10 relevant hashtags at the end" if include_hashtags else "Do not include hashtags"}
6. Keep total description under 5000 characters
7. Make it SEO-friendly with relevant keywords
8. Include a brief "About" section if appropriate

FORMAT:
- Hook/summary paragraph
- Main content overview
- CTAs
{"- Chapters section" if chapters else ""}
{"- Hashtags" if include_hashtags else ""}

Return ONLY the description text, ready to paste directly into YouTube. No JSON or markdown wrappers."""

            # Use unified LLM client with fallback
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=2000,
                temperature=0.7,
                user_id=self._budget_user_id,
                plan=self._budget_plan,
                feature="description_generator.generate",
            )

            if not response.success:
                logger.warning(f"LLM generation failed: {response.error}")
                return self._generate_basic_description(
                    title, transcript, chapters, language
                )
            
            logger.info(f"Description generated using {response.provider}/{response.model}")
            description = response.text.strip()
            
            # Clean up any accidental markdown
            if description.startswith("```"):
                lines = description.split("\n")
                description = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            
            # Extract hashtags from description
            hashtags = []
            if include_hashtags:
                hashtag_matches = re.findall(r'#(\w+)', description)
                hashtags = hashtag_matches[:10]
            
            # Generate summary
            summary = description.split('\n')[0][:200]
            
            return GeneratedDescription(
                description=description,
                chapters=chapters,
                hashtags=hashtags,
                summary=summary,
                language=language,
            )
            
        except Exception as e:
            logger.error(f"AI description generation failed: {e}")
            return self._generate_basic_description(
                title, transcript, chapters, language
            )
    
    def _generate_basic_description(
        self,
        title: str,
        transcript: Optional[str],
        chapters: List[Chapter],
        language: str
    ) -> GeneratedDescription:
        """Generate a basic description without AI."""
        # Create a simple description
        summary = f"Watch this video about: {title}"
        
        description_parts = [
            summary,
            "",
            "Don't forget to LIKE, COMMENT, and SUBSCRIBE for more content!",
            "",
        ]
        
        if chapters:
            description_parts.append("CHAPTERS:")
            for chapter in chapters:
                description_parts.append(f"{chapter.timestamp} {chapter.title}")
            description_parts.append("")
        
        description_parts.extend([
            "#YouTube #Video #Content"
        ])
        
        return GeneratedDescription(
            description="\n".join(description_parts),
            chapters=chapters,
            hashtags=["YouTube", "Video", "Content"],
            summary=summary,
            language=language,
        )


def generate_youtube_description(
    title: str,
    transcript: Optional[str] = None,
    transcript_segments: Optional[List[Dict]] = None,
    language: str = "en",
    video_duration: Optional[float] = None,
    api_key: Optional[str] = None,
) -> GeneratedDescription:
    """
    Convenience function to generate a YouTube description.
    
    Args:
        title: Video title
        transcript: Full transcript text
        transcript_segments: Segments with timestamps [{start, end, text}]
        language: Content language code
        video_duration: Video duration in seconds
        api_key: Anthropic API key
    
    Returns:
        GeneratedDescription with all components
    """
    generator = DescriptionGenerator(api_key)
    return generator.generate(
        title=title,
        transcript=transcript,
        transcript_segments=transcript_segments,
        language=language,
        video_duration=video_duration,
    )
