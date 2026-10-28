"""LLM-driven emoji suggester for the Studio caption pipeline (Week 6).

Given a transcript, this module:

1. Groups the words into phrases using the same `force_break_after` +
   `group_max_words` rules as `ass_renderer._group_events`, so the emojis
   align with what the user sees as a single rendered line.
2. Asks the LLM to pick ONE sentiment-appropriate emoji per phrase
   (skip when nothing fits — better empty than wrong).
3. Returns a copy of the transcript with the emoji attached to the LAST
   word of each chosen phrase (so it renders as the trailing glyph).

Storage policy: the emoji lives on `TranscriptWord.emoji`. Toggling
`captions.emoji_enabled` off/on doesn't re-run the LLM — the suggestions
persist in the spec until the user clears them.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.features.llm_client import LLMBudgetExceeded, get_llm_client
from src.features.studio.spec import TranscriptWord

logger = structlog.get_logger(__name__)

# Hard cap so we don't blow the LLM context budget on long clips. The
# Studio target is ~30-60s of clip so this is plenty in practice.
MAX_PHRASES_PER_CALL = 60
DEFAULT_GROUP_MAX_WORDS = 6


def _group_phrases(
    words: List[TranscriptWord],
    group_max_words: int = DEFAULT_GROUP_MAX_WORDS,
) -> List[List[int]]:
    """Mirror of ``ass_renderer._group_events`` that returns phrase
    boundaries as lists of word indices (so we can attach the emoji to
    the LAST index later).
    """
    if not words:
        return []
    phrases: List[List[int]] = []
    bucket: List[int] = []
    for i, w in enumerate(words):
        bucket.append(i)
        force = w.force_break_after
        if force is True:
            phrases.append(bucket)
            bucket = []
            continue
        if force is False:
            continue
        if len(bucket) >= group_max_words:
            phrases.append(bucket)
            bucket = []
    if bucket:
        phrases.append(bucket)
    return phrases


def _phrase_text(words: List[TranscriptWord], indices: List[int]) -> str:
    """Reconstruct the phrase text exactly as the user sees it."""
    return " ".join(words[i].text for i in indices).strip()


SYSTEM_PROMPT = """You are a caption-emoji picker for short-form vertical video.
For each phrase you receive, pick ONE single emoji that captures the dominant
sentiment, emotion, or topic. Prefer common, broadly-recognizable emojis. If
nothing fits naturally, return an empty string for that phrase — it's better
to leave a phrase un-decorated than to slap a weak emoji on it.

You must return a strict JSON array with the shape:
  [{"phrase_idx": 0, "emoji": "🔥"}, {"phrase_idx": 1, "emoji": ""}, ...]

Rules:
- Exactly ONE emoji per entry (or empty string to skip).
- No words, no punctuation, no markdown — just the emoji character.
- Cover every input phrase in order (one entry per phrase_idx).
"""


def _build_user_prompt(phrases: List[str]) -> str:
    lines = ["Phrases to decorate (one per line, numbered):"]
    for i, p in enumerate(phrases):
        lines.append(f"{i}: {p}")
    lines.append("")
    lines.append(
        'Return JSON: [{"phrase_idx": 0, "emoji": "..."}, ...].'
        " One entry per phrase. Empty string = skip."
    )
    return "\n".join(lines)


def _parse_response(payload: Any, n_phrases: int) -> Dict[int, str]:
    """Pull (phrase_idx → emoji) out of the LLM's JSON. Tolerant of the
    common deviations (top-level dict-with-array, missing entries, extra
    fields) so a slightly off-prompt response still produces useful output.
    """
    items: List[Any] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("emojis", "results", "suggestions", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break

    out: Dict[int, str] = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("phrase_idx")
        emoji = entry.get("emoji", "")
        try:
            idx_int = int(idx)
        except (TypeError, ValueError):
            continue
        if not isinstance(emoji, str):
            continue
        emoji = emoji.strip()
        # Filter "no emoji" sentinels the model occasionally returns.
        if emoji in ("", "none", "None", "-", "n/a", "N/A"):
            continue
        if 0 <= idx_int < n_phrases:
            out[idx_int] = emoji[:12]  # respect the schema's max_length
    return out


def suggest_emojis_for_transcript(
    words: List[TranscriptWord],
    *,
    user_id: Optional[int] = None,
    plan: str = "free",
    group_max_words: int = DEFAULT_GROUP_MAX_WORDS,
) -> Tuple[List[TranscriptWord], int]:
    """Run the suggester and return ``(updated_words, n_suggestions)``.

    Always returns a fresh list so the caller can swap it into the spec
    safely. When the LLM fails / returns nothing, the original transcript
    is returned untouched (along with ``n_suggestions=0``).

    Raises :class:`LLMBudgetExceeded` from the underlying client so the
    API layer can translate to HTTP 429 / show the upgrade modal.
    """
    if not words:
        return list(words), 0

    phrases = _group_phrases(words, group_max_words=group_max_words)
    if not phrases:
        return list(words), 0

    # Trim to MAX_PHRASES_PER_CALL — every clip we care about fits but
    # the cap stops a pathological 5-minute clip from running unbounded.
    if len(phrases) > MAX_PHRASES_PER_CALL:
        logger.info(
            "studio.emoji_suggester.truncating_phrases",
            total=len(phrases),
            kept=MAX_PHRASES_PER_CALL,
        )
        phrases = phrases[:MAX_PHRASES_PER_CALL]

    phrase_texts = [_phrase_text(words, p) for p in phrases]

    client = get_llm_client()
    try:
        payload = client.generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(phrase_texts),
            max_tokens=400,
            temperature=0.4,
            user_id=user_id,
            feature="studio_emoji_suggester",
            plan=plan,
        )
    except LLMBudgetExceeded:
        raise
    except Exception as exc:
        logger.warning("studio.emoji_suggester.llm_failed", error=str(exc))
        return list(words), 0

    if not payload:
        return list(words), 0

    parsed = _parse_response(payload, n_phrases=len(phrases))
    if not parsed:
        return list(words), 0

    # Apply: attach the emoji to the LAST word of each phrase so it
    # renders as the trailing glyph. Clones every word so we never
    # mutate the caller's input list.
    updated: List[TranscriptWord] = [w.model_copy() for w in words]
    n_set = 0
    for phrase_idx, indices in enumerate(phrases):
        emoji = parsed.get(phrase_idx)
        if not emoji or not indices:
            continue
        last_idx = indices[-1]
        if 0 <= last_idx < len(updated):
            updated[last_idx].emoji = emoji
            n_set += 1
    return updated, n_set


def clear_emojis(words: List[TranscriptWord]) -> List[TranscriptWord]:
    """Return a copy of ``words`` with every ``emoji`` set to None."""
    out: List[TranscriptWord] = []
    for w in words:
        copy = w.model_copy()
        copy.emoji = None
        out.append(copy)
    return out


__all__ = [
    "clear_emojis",
    "suggest_emojis_for_transcript",
]
