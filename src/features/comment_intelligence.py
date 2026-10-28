"""Phase 7.4: Comment Intelligence.

Turns the comments captured by the tracker (``video_comments``) into actionable
signal for a creator: overall sentiment, the most-asked viewer questions,
concrete next-video ideas, an FAQ → suggested pinned comment, and praise /
criticism themes. Grounded strictly in the supplied comments (no generic
advice). LLM-powered via the shared budget-tracked client.
"""
from __future__ import annotations

from typing import Any, Iterable

import structlog

from src.features.llm_client import get_llm_client

logger = structlog.get_logger(__name__)

_SYSTEM = (
    "You are a YouTube strategist. You read a video's comments and extract "
    "actionable signal for the creator: what viewers asked, what to make next, "
    "how to engage. Be specific and ground EVERYTHING strictly in the comments "
    "provided — never give generic YouTube advice."
)


def _row(c) -> tuple[int, str] | None:
    if isinstance(c, dict):
        text, likes = c.get("text"), c.get("like_count", 0)
    else:
        text, likes = getattr(c, "text", None), getattr(c, "like_count", 0)
    if not text:
        return None
    return (int(likes or 0), str(text).strip().replace("\n", " "))


def analyze_comments(
    comments: Iterable[Any],
    *,
    user_id: int | None = None,
    plan: str = "free",
    max_comments: int = 60,
) -> dict:
    """Analyze a video's comments. ``comments`` items expose ``text`` +
    ``like_count`` (objects or dicts). Returns the insight dict (+ comment_count)."""
    rows = [r for r in (_row(c) for c in comments) if r is not None]
    if not rows:
        return {"error": "no_comments", "comment_count": 0}

    rows.sort(reverse=True)  # most-liked first
    sample = rows[:max_comments]
    joined = "\n".join(f"[{likes} likes] {text[:300]}" for likes, text in sample)

    user_prompt = f"""Top {len(sample)} comments on a YouTube video (by likes):

{joined}

Respond with ONLY valid JSON:
{{
  "summary": "1-2 sentence read of the overall viewer reaction",
  "sentiment": {{"positive": <0-100>, "neutral": <0-100>, "negative": <0-100>}},
  "top_questions": ["the most-asked viewer questions"],
  "next_video_ideas": ["concrete next-video topics viewers are asking for, ranked"],
  "faq": [{{"question": "...", "suggested_pinned_answer": "..."}}],
  "praise_themes": ["what viewers loved"],
  "criticism_themes": ["recurring complaints / requests"]
}}
Base everything ONLY on these comments. Use empty arrays when nothing applies."""

    result = get_llm_client().generate_json(
        _SYSTEM, user_prompt, max_tokens=1200, temperature=0.4,
        user_id=user_id, plan=plan, feature="comment_intelligence",
    )
    if not result:
        logger.warning("comment_intelligence.empty_llm")
        result = {"summary": "", "error": "llm_unavailable"}
    result["comment_count"] = len(rows)
    return result
