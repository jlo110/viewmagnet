"""Input acquisition helpers for the shorts pipeline.

Responsibilities:

* Extract YouTube video IDs from URLs.
* Fetch YouTube comments via the Data API (used to mine timestamp signals).
* Parse pre-existing transcripts (SRT / VTT / JSON) into structured segments.
* Provide the viral pattern dictionary used by the scoring layer.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


def extract_video_id(url: str) -> Optional[str]:
    """Extract a YouTube video id from common URL shapes (or a raw id)."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _resolve_youtube_api_key() -> Optional[str]:
    try:
        from src.config import get_settings

        settings = get_settings()
        api_keys = settings.youtube_api_keys
        if api_keys:
            return api_keys[0]
    except Exception:
        pass

    return (
        os.getenv("YOUTUBE1")
        or os.getenv("YOUTUBE2")
        or os.getenv("YOUTUBE_API_KEY_1")
        or os.getenv("YOUTUBE_API_KEY")
    )


def fetch_youtube_comments(video_id: str, max_comments: int = 100) -> List[str]:
    """Fetch comments for a YouTube video.

    Returns an empty list if no API key is available or the request fails so
    callers can degrade gracefully.
    """
    api_key = _resolve_youtube_api_key()
    if not api_key:
        logger.warning(
            "shorts.fetch.no_youtube_key",
            message="Set YOUTUBE1 or YOUTUBE_API_KEY_1 in .env",
        )
        return []

    try:
        import requests
    except ImportError:
        logger.warning("shorts.fetch.requests_missing")
        return []

    comments: List[str] = []
    next_page_token: Optional[str] = None

    try:
        while len(comments) < max_comments:
            params = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": min(100, max_comments - len(comments)),
                "order": "relevance",
                "key": api_key,
            }
            if next_page_token:
                params["pageToken"] = next_page_token

            response = requests.get(
                "https://www.googleapis.com/youtube/v3/commentThreads",
                params=params,
                timeout=15,
            )
            if response.status_code != 200:
                logger.warning(
                    "shorts.fetch.youtube_error", status=response.status_code
                )
                break

            data = response.json()
            for item in data.get("items", []):
                comment_text = item["snippet"]["topLevelComment"]["snippet"][
                    "textDisplay"
                ]
                comments.append(comment_text)

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break
    except Exception as exc:
        logger.warning("shorts.fetch.comments_failed", error=str(exc))
        return comments

    logger.info("shorts.fetch.comments_loaded", count=len(comments))
    return comments


def parse_timestamp(ts: str) -> float:
    """Parse SRT/VTT timestamps (``HH:MM:SS,mmm``) to seconds."""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def parse_transcript(transcript: str) -> Dict:
    """Parse a transcript blob (JSON, SRT, or VTT) into structured segments."""
    try:
        return json.loads(transcript)
    except Exception:
        pass

    segments: List[Dict] = []
    lines = transcript.strip().split("\n")
    current_segment: Dict = {"start": 0, "end": 0, "text": ""}

    timestamp_re = re.compile(
        r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})"
    )

    for line in lines:
        timestamp_match = timestamp_re.match(line)
        if timestamp_match:
            if current_segment["text"]:
                segments.append(current_segment.copy())
            current_segment = {
                "start": parse_timestamp(timestamp_match.group(1)),
                "end": parse_timestamp(timestamp_match.group(2)),
                "text": "",
            }
        elif line.strip() and not line.strip().isdigit():
            if current_segment["text"]:
                current_segment["text"] += " "
            current_segment["text"] += line.strip()

    if current_segment["text"]:
        segments.append(current_segment)

    full_text = " ".join(s["text"] for s in segments)
    duration = segments[-1]["end"] if segments else 0
    return {"segments": segments, "text": full_text, "duration": duration}


def split_into_sentences(text: str) -> List[str]:
    """Split a transcript blob into sentences (very naive)."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def load_viral_patterns() -> Dict[str, List[str]]:
    """Return the static viral-pattern dictionary used by scoring."""
    return {
        "hook_phrases": [
            r"here's the thing",
            r"what if i told you",
            r"nobody talks about",
            r"the truth is",
            r"let me tell you",
            r"this is crazy",
            r"you won't believe",
            r"i just realized",
            r"stop everything",
            r"listen to this",
            r"here's what happened",
            r"so basically",
            r"the secret is",
            r"most people don't know",
            r"this changed everything",
            r"oh my (god|goodness|gosh)",
            r"look at (this|that)",
            r"watch this",
            r"did you see that",
            r"he('s| is) on fire",
            r"from (downtown|deep|way downtown)",
            r"bang!*",
            r"boom!*",
            r"and (one|1)!*",
            r"count it",
            r"(game|match|set) point",
            r"clutch",
            r"dagger",
            r"what a (play|shot|move|goal|save)",
            r"(unbelievable|incredible|amazing) (play|shot|move)",
        ],
        "emotion_words": [
            "amazing", "insane", "crazy", "unbelievable", "shocking",
            "incredible", "mind-blowing", "game-changer", "secret",
            "mistake", "wrong", "actually", "literally", "seriously",
            "clutch", "dagger", "buzzer", "three", "slam", "dunk",
            "goat", "mvp", "highlight", "legendary", "historic",
            "record", "broken", "winner", "champion", "finals",
            "overtime", "comeback", "upset", "dominate", "unstoppable",
        ],
        "story_beats": [
            r"and then",
            r"but here's the twist",
            r"that's when",
            r"suddenly",
            r"out of nowhere",
            r"i couldn't believe",
            r"everything changed",
            r"with \d+ seconds (left|remaining)",
            r"in the (final|last|closing)",
            r"down by \d+",
            r"tie game",
            r"for the (win|lead)",
            r"at the buzzer",
            r"off the (backboard|glass|rim)",
            r"swish",
        ],
        "specifics": [
            r"\d+\s*(percent|%)",
            r"\$\d+",
            r"\d+-\d+",
            r"\d+ (points?|rebounds?|assists?|steals?|blocks?)",
            r"(triple|double)[ -]double",
            r"\d+[ -]point(er)?",
            r"\d+\s*(million|billion|thousand)",
            r"(first|second|third|one|two|three)\s+thing",
            r"step\s+(one|two|three|\d+)",
        ],
    }


def fetch_youtube_transcript(video_id: str) -> Optional[Dict]:
    """Fetch a YouTube transcript via :mod:`youtube_transcript_api`.

    Returns a dict with ``text``, ``segments`` and ``duration`` or ``None`` if
    no transcript is available.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        logger.warning("shorts.fetch.transcript_api_missing")
        return None

    try:
        ytt = YouTubeTranscriptApi()
        available = ytt.list(video_id)

        transcript_data = None
        for lang in ("en", "en-US", "en-GB"):
            try:
                transcript_data = ytt.fetch(video_id, languages=[lang])
                break
            except Exception:
                continue

        if not transcript_data:
            try:
                for t in available:
                    transcript_data = ytt.fetch(
                        video_id, languages=[t.language_code]
                    )
                    logger.info(
                        "shorts.fetch.transcript_fallback", language=t.language
                    )
                    break
            except Exception:
                pass

        if not transcript_data:
            return None

        segments = []
        for snippet in transcript_data.snippets:
            segments.append(
                {
                    "text": snippet.text,
                    "start": snippet.start,
                    "duration": snippet.duration,
                }
            )

        text = " ".join(s["text"] for s in segments)
        duration = segments[-1]["start"] + segments[-1]["duration"] if segments else 0
        return {"text": text, "segments": segments, "duration": duration}
    except Exception as exc:
        logger.warning("shorts.fetch.transcript_failed", error=str(exc))
        return None
