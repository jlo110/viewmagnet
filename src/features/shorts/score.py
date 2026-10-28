"""Scoring, LLM analysis, ranking and boundary refinement.

Pure functions consumed by :class:`src.features.shorts.creator.ShortsCreator`.
All inputs and outputs are plain dicts / dataclasses so the helpers stay easy
to test in isolation.
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import structlog

from src.features.shorts.models import Highlight

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Regex pattern scoring
# ---------------------------------------------------------------------------


def score_segment(text: str, patterns: Dict[str, List[str]]) -> float:
    """Score a transcript segment for viral potential using regex heuristics."""
    text_lower = text.lower()
    score = 0

    for pattern in patterns["hook_phrases"]:
        if re.search(pattern, text_lower):
            score += 25
    for word in patterns["emotion_words"]:
        if word in text_lower:
            score += 10
    for pattern in patterns["story_beats"]:
        if re.search(pattern, text_lower):
            score += 20
    for pattern in patterns["specifics"]:
        if re.search(pattern, text_lower):
            score += 15

    if "?" in text:
        score += 10
    if "!" in text:
        score += 5

    word_count = len(text.split())
    if word_count < 5:
        score *= 0.5
    elif word_count > 100:
        score *= 0.8

    return min(100, score)


def get_highlight_reason(text: str, patterns: Dict[str, List[str]]) -> str:
    """Pick a short label explaining why a segment scored well."""
    text_lower = text.lower()
    for pattern in patterns["hook_phrases"]:
        if re.search(pattern, text_lower):
            return "viral_hook"
    for pattern in patterns["story_beats"]:
        if re.search(pattern, text_lower):
            return "story_beat"
    for pattern in patterns["specifics"]:
        if re.search(pattern, text_lower):
            return "specific_detail"

    emotion_count = sum(1 for w in patterns["emotion_words"] if w in text_lower)
    if emotion_count >= 2:
        return "emotional_peak"
    return "content_density"


def assess_hook_quality(text: str) -> str:
    """Heuristic ``strong``/``medium``/``weak`` label for the opening of a clip."""
    words = text.split()[:15]
    hook = " ".join(words).lower()

    strong_patterns = [
        r"^(here's|what if|nobody|the truth|let me|this is crazy)",
        r"^(you won't|i just|stop|listen|so here's)",
    ]
    for pattern in strong_patterns:
        if re.search(pattern, hook):
            return "strong"
    if "?" in " ".join(words[:10]):
        return "strong"
    if re.search(r"\d+", hook):
        return "medium"
    return "weak"


# ---------------------------------------------------------------------------
# Highlight extraction from a structured transcript
# ---------------------------------------------------------------------------


def analyze_transcript_for_highlights(
    transcript_data: Dict,
    target_duration: int,
    num_clips: int,
    patterns: Dict[str, List[str]],
) -> List[Highlight]:
    """Walk a structured transcript and produce regex-driven highlights."""
    segments = transcript_data.get("segments", [])
    if not segments:
        return []

    highlights: List[Highlight] = []

    scored_segments: List[Dict] = []
    for i, segment in enumerate(segments):
        scored_segments.append(
            {
                "index": i,
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"],
                "score": score_segment(segment["text"], patterns),
            }
        )

    threshold = 30
    MAX_SHORT_DURATION = 60
    MIN_SHORT_DURATION = 15

    i = 0
    while i < len(scored_segments):
        if scored_segments[i]["score"] >= threshold:
            start_idx = i
            end_idx = i
            total_score = scored_segments[i]["score"]

            while end_idx < len(scored_segments) - 1:
                next_seg = scored_segments[end_idx + 1]
                duration = next_seg["end"] - scored_segments[start_idx]["start"]
                if duration > 60:
                    break
                if next_seg["score"] >= threshold / 2:
                    end_idx += 1
                    total_score += next_seg["score"]
                else:
                    break

            start_time = scored_segments[start_idx]["start"]
            end_time = scored_segments[end_idx]["end"]

            min_payoff_buffer = 20
            max_total_duration = 60
            segments_to_check = min(15, len(scored_segments) - end_idx - 1)

            for look_ahead in range(1, segments_to_check + 1):
                if end_idx + look_ahead >= len(scored_segments):
                    break
                next_seg = scored_segments[end_idx + look_ahead]
                next_text = next_seg["text"].strip()
                potential_end = next_seg["end"]
                if potential_end - start_time > max_total_duration:
                    break

                is_natural_ending = (
                    next_text.endswith(".")
                    or next_text.endswith("!")
                    or next_text.endswith("?")
                    or "and that" in next_text.lower()
                    or "so yeah" in next_text.lower()
                    or "anyway" in next_text.lower()
                )

                end_time = potential_end
                if is_natural_ending and (end_time - start_time) >= min_payoff_buffer:
                    break

            duration = end_time - start_time

            if duration > MAX_SHORT_DURATION:
                end_time = start_time + MAX_SHORT_DURATION
                duration = MAX_SHORT_DURATION

            if MIN_SHORT_DURATION <= duration <= MAX_SHORT_DURATION:
                actual_end_idx = start_idx
                for j in range(start_idx, len(scored_segments)):
                    if scored_segments[j]["end"] <= end_time:
                        actual_end_idx = j
                    else:
                        break

                text = " ".join(
                    scored_segments[j]["text"]
                    for j in range(start_idx, actual_end_idx + 1)
                )

                avg_score = total_score / max(1, actual_end_idx - start_idx + 1)
                reason = get_highlight_reason(text, patterns)

                highlights.append(
                    Highlight(
                        start_time=start_time,
                        end_time=end_time,
                        duration=duration,
                        score=min(85, avg_score * 1.2),
                        reason=reason,
                        transcript=text,
                        hook_quality=assess_hook_quality(text),
                        suggested_title="",
                        crop_x=0,
                        crop_width=0,
                        crop_height=0,
                    )
                )

            i = end_idx + 1
        else:
            i += 1

    return highlights[: max(num_clips, len(highlights))]


# ---------------------------------------------------------------------------
# Audio energy
# ---------------------------------------------------------------------------


def analyze_audio_energy(
    audio_path: str, target_duration: int, num_clips: int
) -> List[Highlight]:
    """Detect highlights based on raw audio energy peaks."""
    try:
        import librosa
        from scipy.signal import find_peaks
    except ImportError:
        logger.warning("shorts.score.librosa_missing")
        return []

    try:
        logger.info("shorts.score.audio_energy.start", path=audio_path)
        y, sr = librosa.load(audio_path, sr=22050)

        hop_length = 512
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
        times = librosa.times_like(rms, sr=sr, hop_length=hop_length)

        if rms.max() == rms.min():
            return []
        rms_norm = (rms - rms.min()) / (rms.max() - rms.min())

        min_distance = int(target_duration * sr / hop_length)
        peaks, _ = find_peaks(rms_norm, height=0.6, distance=min_distance)

        highlights: List[Highlight] = []
        for peak in peaks[:num_clips]:
            peak_time = times[peak]
            build_up = 10
            payoff = target_duration + 15
            start = max(0, peak_time - build_up)
            end = peak_time + payoff
            highlights.append(
                Highlight(
                    start_time=start,
                    end_time=end,
                    duration=end - start,
                    score=float(rms_norm[peak] * 80),
                    reason="audio_peak",
                    transcript="",
                    hook_quality="medium",
                    suggested_title="",
                    crop_x=0,
                    crop_width=0,
                    crop_height=0,
                )
            )
        return highlights
    except Exception as exc:
        logger.warning("shorts.score.audio_energy_failed", error=str(exc))
        return []


def merge_highlights(
    text_highlights: List[Highlight],
    audio_highlights: List[Highlight],
    video_duration: float,
) -> List[Highlight]:
    """Combine text & audio highlights, boosting overlap."""
    all_highlights: List[Highlight] = list(text_highlights)

    for audio_h in audio_highlights:
        overlap = False
        for text_h in text_highlights:
            if (
                audio_h.start_time < text_h.end_time
                and audio_h.end_time > text_h.start_time
            ):
                text_h.score = min(100, text_h.score + 20)
                text_h.reason = "text_audio_peak"
                overlap = True
                break
        if not overlap:
            all_highlights.append(audio_h)

    return all_highlights


# ---------------------------------------------------------------------------
# Comment timestamp signals
# ---------------------------------------------------------------------------


def extract_comment_timestamps(comments: List[str]) -> List[Dict]:
    """Extract ``MM:SS`` style timestamps from YouTube comments."""
    timestamp_pattern = r"(\d{1,2}:\d{2}(?::\d{2})?)"
    timestamp_mentions: List[Dict] = []

    for comment in comments:
        for match in re.finditer(timestamp_pattern, comment):
            ts = match.group(1)
            parts = ts.split(":")
            if len(parts) == 2:
                seconds = int(parts[0]) * 60 + int(parts[1])
            else:
                seconds = (
                    int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                )

            start = max(0, match.start() - 50)
            end = min(len(comment), match.end() + 100)
            context = comment[start:end].strip()

            positive_words = [
                "😂", "lol", "lmao", "gold", "best", "amazing", "hilarious",
                "favorite", "dying", "love", "goat", "fire", "🔥", "legend",
                "classic", "perfect",
            ]
            sentiment_score = sum(
                1 for w in positive_words if w.lower() in comment.lower()
            )

            timestamp_mentions.append(
                {
                    "timestamp": ts,
                    "seconds": seconds,
                    "context": context,
                    "sentiment_score": sentiment_score,
                }
            )

    from collections import Counter

    counts = Counter(t["seconds"] for t in timestamp_mentions)

    unique_timestamps: Dict[int, Dict] = {}
    for t in timestamp_mentions:
        sec = t["seconds"]
        existing = unique_timestamps.get(sec)
        if existing is None or t["sentiment_score"] > existing["sentiment_score"]:
            unique_timestamps[sec] = {**t, "mention_count": counts[sec]}

    sorted_timestamps = sorted(
        unique_timestamps.values(),
        key=lambda x: (x["mention_count"] * 2 + x["sentiment_score"]),
        reverse=True,
    )
    logger.info("shorts.score.comment_timestamps", count=len(sorted_timestamps))
    return sorted_timestamps[:10]


# ---------------------------------------------------------------------------
# Boundary refinement & ranking
# ---------------------------------------------------------------------------


def fuzzy_find_text(
    search_text: str, segments: List[Dict], search_from_end: bool = False
) -> Optional[Dict]:
    """Return the segment that loosely matches ``search_text``."""
    if not search_text or not segments:
        return None
    search_lower = search_text.lower().strip()
    search_words = [w for w in search_lower.split() if len(w) > 3][:8]
    if not search_words:
        search_words = search_lower.split()[:5]
    search_phrase = " ".join(search_words)

    iter_list = list(reversed(segments)) if search_from_end else segments
    for seg in iter_list:
        seg_text = seg["text"].lower()
        if search_phrase in seg_text:
            return seg
        matches = sum(1 for w in search_words if w in seg_text)
        if matches >= len(search_words) * 0.6:
            return seg
    return None


def find_natural_end(
    segments: List[Dict],
    start_time: float,
    min_duration: float,
    max_duration: float,
) -> float:
    """Walk forward until we land on a natural sentence boundary."""
    best_end = start_time + min_duration
    for seg in segments:
        if seg["start"] < start_time:
            continue
        duration = seg["end"] - start_time
        if duration > max_duration:
            break
        text = seg["text"].strip()
        is_natural_end = (
            text.endswith(".")
            or text.endswith("!")
            or text.endswith("?")
            or text.endswith("...")
            or "so yeah" in text.lower()
            or "anyway" in text.lower()
            or "you know" in text.lower()
            or "[laughter]" in text.lower()
            or "[applause]" in text.lower()
        )
        if duration >= min_duration and is_natural_end:
            best_end = seg["end"] + 0.5
    return min(best_end, start_time + max_duration)


def refine_clip_boundaries(
    clips: List[Highlight], transcript_data: Dict
) -> List[Highlight]:
    """Snap clip start/end times to sentence boundaries with strong endings."""
    segments = transcript_data.get("segments", [])
    if not segments or not clips:
        return clips

    MAX_DURATION = 60
    MIN_DURATION = 20

    for clip in clips:
        original_start = clip.start_time
        original_end = clip.end_time

        best_start = clip.start_time
        for seg in segments:
            if seg["start"] <= clip.start_time <= seg["end"]:
                seg_duration = seg["end"] - seg["start"]
                into_seg = clip.start_time - seg["start"]
                if into_seg > seg_duration * 0.3:
                    seg_idx = segments.index(seg)
                    if seg_idx + 1 < len(segments):
                        best_start = segments[seg_idx + 1]["start"]
                else:
                    best_start = seg["start"]
                break

        best_end = clip.end_time
        found_good_end = False

        for seg in segments:
            if seg["start"] < best_start:
                continue
            duration_if_end_here = seg["end"] - best_start
            if duration_if_end_here > MAX_DURATION:
                break
            if duration_if_end_here < MIN_DURATION:
                continue
            text = seg["text"].strip()
            end_score = 0
            if text.endswith("!"):
                end_score += 30
            if text.endswith("?"):
                end_score += 20
            if text.endswith("."):
                end_score += 15
            payoff_words = [
                "exactly", "right", "yes", "no", "wow", "oh", "that", "there",
                "done", "boom", "finally", "gotcha", "see",
            ]
            for word in payoff_words:
                if word in text.lower():
                    end_score += 10
                    break
            if "[laughter]" in text.lower() or "haha" in text.lower():
                end_score += 25
            if "[applause]" in text.lower() or "cheering" in text.lower():
                end_score += 20
            ideal_duration = 40
            if abs(duration_if_end_here - ideal_duration) < 10:
                end_score += 15
            if end_score >= 25:
                best_end = seg["end"] + 0.5
                found_good_end = True
                if end_score >= 40:
                    break

        if not found_good_end:
            for seg in reversed(segments):
                if seg["end"] <= clip.end_time and seg["start"] >= best_start:
                    if seg["end"] - best_start >= MIN_DURATION:
                        best_end = seg["end"] + 0.5
                        break

        clip.start_time = best_start
        clip.end_time = min(best_end, best_start + MAX_DURATION)
        clip.duration = clip.end_time - clip.start_time

        if abs(original_start - best_start) > 2 or abs(original_end - best_end) > 2:
            new_transcript = ""
            for seg in segments:
                if (
                    seg["start"] >= clip.start_time - 0.5
                    and seg["end"] <= clip.end_time + 0.5
                ):
                    new_transcript += seg["text"] + " "
            if new_transcript.strip():
                clip.transcript = new_transcript.strip()
            logger.info(
                "shorts.score.refined_clip",
                original=(original_start, original_end),
                refined=(clip.start_time, clip.end_time),
                duration=clip.duration,
            )

    return clips


def select_diverse_clips(
    highlights: List[Highlight],
    video_duration: float,
    num_clips: int,
    min_gap_seconds: float = 60,
) -> List[Highlight]:
    """Pick the top ``num_clips`` highlights spread across the video timeline."""
    if not highlights:
        return []

    sorted_highlights = sorted(highlights, key=lambda h: h.score, reverse=True)
    num_segments = min(num_clips + 1, max(3, int(video_duration / 300)))
    segment_duration = video_duration / max(num_segments, 1)

    selected: List[Highlight] = []
    segments_used = set()

    for h in sorted_highlights:
        segment_idx = int(h.start_time / segment_duration) if segment_duration else 0
        too_close = any(
            abs(h.start_time - s.start_time) < min_gap_seconds for s in selected
        )
        if not too_close and (
            segment_idx not in segments_used or len(selected) < num_clips // 2
        ):
            selected.append(h)
            segments_used.add(segment_idx)
            if len(selected) >= num_clips:
                break

    if len(selected) < num_clips:
        for h in sorted_highlights:
            if h in selected:
                continue
            too_close = any(
                abs(h.start_time - s.start_time) < min_gap_seconds / 2
                for s in selected
            )
            if not too_close:
                selected.append(h)
                if len(selected) >= num_clips:
                    break

    selected.sort(key=lambda h: h.start_time)
    return selected


def calculate_objective_quality(clip: Highlight) -> Dict:
    """Score a clip on hook / payoff / emotion / clarity."""
    transcript = clip.transcript.lower()
    words = transcript.split()

    quality: Dict = {
        "hook_score": 0,
        "payoff_score": 0,
        "emotion_score": 0,
        "clarity_score": 0,
        "total": 0,
        "passes": False,
        "issues": [],
    }

    hook = " ".join(words[:15]) if len(words) >= 15 else transcript
    strong_hooks = [
        r"here's (the|what)", r"what if", r"nobody (talks|knows|told)",
        r"the (truth|secret|thing) is", r"let me (tell|show)",
        r"this is (crazy|insane|wild)", r"you won't believe",
        r"i (just|can't)", r"stop everything", r"listen",
        r"oh my (god|gosh)", r"watch this", r"look at (this|that)",
        r"wait", r"so basically", r"the problem is",
    ]
    for pattern in strong_hooks:
        if re.search(pattern, hook):
            quality["hook_score"] += 25
            break
    if "?" in " ".join(words[:20]):
        quality["hook_score"] += 15
    if re.search(r"\d+", hook):
        quality["hook_score"] += 10
    if quality["hook_score"] == 0:
        quality["issues"].append("Weak hook - no attention grabber in first words")

    payoff_start = int(len(words) * 0.7)
    payoff = " ".join(words[payoff_start:])
    payoff_indicators = [
        r"(exactly|right|yes|no way|wow|oh|whoa)",
        r"(that's|there|done|boom|bang|finally)",
        r"(haha|lol|lmao|\[laughter\]|\[applause\])",
        r"(insane|crazy|incredible|unbelievable)",
        r"(!{2,})",
        r"(and that's|so yeah|that's why|the point is)",
    ]
    for pattern in payoff_indicators:
        if re.search(pattern, payoff):
            quality["payoff_score"] += 15

    last_words = " ".join(words[-5:]) if len(words) >= 5 else payoff
    if "!" in last_words:
        quality["payoff_score"] += 10
    elif "?" in last_words:
        quality["payoff_score"] += 5
    elif "." in last_words:
        quality["payoff_score"] += 3
    if quality["payoff_score"] == 0:
        quality["issues"].append("No clear payoff - clip may feel incomplete")

    emotion_words = [
        "amazing", "insane", "crazy", "unbelievable", "shocking",
        "hilarious", "funny", "wild", "incredible", "mind-blowing",
        "love", "hate", "angry", "scared", "excited", "surprised",
        "best", "worst", "never", "always", "first", "only",
    ]
    emotion_count = sum(1 for w in emotion_words if w in transcript)
    quality["emotion_score"] = min(25, emotion_count * 8)
    if quality["emotion_score"] == 0:
        quality["issues"].append("Low emotional content")

    word_count = len(words)
    sentence_endings = (
        transcript.count(".") + transcript.count("!") + transcript.count("?")
    )
    if sentence_endings >= 2:
        quality["clarity_score"] += 15
    if 60 <= word_count <= 120:
        quality["clarity_score"] += 15
    elif 45 <= word_count < 60 or 120 < word_count <= 150:
        quality["clarity_score"] += 10
    else:
        quality["issues"].append(f"Duration may be off ({word_count} words)")

    quality["total"] = (
        quality["hook_score"]
        + quality["payoff_score"]
        + quality["emotion_score"]
        + quality["clarity_score"]
    )
    quality["passes"] = (
        quality["hook_score"] >= 10
        and quality["payoff_score"] >= 5
        and quality["total"] >= 30
    )
    return quality


def normalize_scores(clips: List[Highlight]) -> List[Highlight]:
    """Re-score clips using a blend of LLM score and objective quality."""
    if not clips:
        return clips

    scored: List = []
    for clip in clips:
        quality = calculate_objective_quality(clip)
        llm_weight = 0.3
        objective_weight = 0.7
        objective_score = min(100, quality["total"] * 1.2)
        combined_score = clip.score * llm_weight + objective_score * objective_weight
        if not quality["passes"]:
            combined_score *= 0.7
        clip.score = min(95, round(combined_score))
        if quality["hook_score"] >= 20:
            clip.hook_quality = "strong"
        elif quality["hook_score"] >= 10:
            clip.hook_quality = "medium"
        else:
            clip.hook_quality = "weak"
        scored.append((clip, quality["total"], quality["passes"]))

    clips = [c[0] for c in sorted(scored, key=lambda x: x[0].score, reverse=True)]
    return clips


# ---------------------------------------------------------------------------
# LLM-driven analysis
# ---------------------------------------------------------------------------


_VIRAL_CLIP_SYSTEM_PROMPT = """You are a ruthless viral clip editor. Your reputation depends on finding ONLY genuinely viral-worthy moments.

REJECT mediocre content. Only select moments that would ACTUALLY perform on TikTok/Shorts.

A VIRAL CLIP MUST HAVE ALL THREE:
1. HOOK (first 3 sec) - Makes viewer stop scrolling. Examples:
   - "Here's what nobody tells you..."
   - "I can't believe this actually happened"
   - Shocking statement or visual
   - Direct challenge to viewer

2. TENSION/BUILD - Creates anticipation:
   - Story escalation
   - Suspense before reveal
   - "Wait for it" energy

3. PAYOFF - Satisfying conclusion:
   - Punchline lands
   - Reveal happens
   - Reaction is captured
   - Clear ending (not cut mid-sentence)

RED FLAGS - Skip moments with:
- No clear hook (viewer would scroll past)
- Cuts off before payoff
- Requires context from earlier
- Just talking with no energy change
- Generic commentary without substance

DURATION: 25-45 seconds ideal (60-110 words)

BE HARSH WITH SCORING:
- 85-95: Would actually go viral (rare - maybe 1 per video)
- 70-84: Strong clip, good engagement
- 55-69: Decent, but not special
- Below 55: Don't bother suggesting

If a chunk has no good clips, return fewer or empty array. Quality over quantity.

For each clip provide:
- start_sentence: EXACT first 10+ words (must be findable in transcript)
- end_sentence: EXACT last 10+ words AFTER the payoff (must be findable)
- score: 1-100 viral potential
- reason: Why this complete moment works
- hook_quality: "strong"/"medium"/"weak"
- suggested_title: Catchy title (curiosity gap)
- approximate_position: "early"/"middle"/"late" in this chunk

Return as JSON array."""


def get_viral_clip_system_prompt() -> str:
    return _VIRAL_CLIP_SYSTEM_PROMPT


def get_viral_clip_user_prompt(
    video_title: str, chunk_idx: int, total_chunks: int, transcript_chunk: str
) -> str:
    return f"""Video Title: "{video_title}"
Chunk {chunk_idx + 1}/{total_chunks} of transcript:

{transcript_chunk}

Find ONLY genuinely viral clips. It's OK to return fewer than 3 if quality isn't there.

For each clip, the start_sentence MUST be an attention-grabbing hook. The end_sentence MUST be AFTER the payoff.

Return as JSON array (or empty [] if no good clips):
[
  {{
    "start_sentence": "exact hook phrase (first 10+ words)...",
    "end_sentence": "exact text AFTER the payoff lands...",
    "score": 75,
    "reason": "Hook: [what grabs attention] | Payoff: [what delivers]",
    "hook_quality": "strong",
    "suggested_title": "Curiosity-gap title",
    "approximate_position": "early"
  }}
]"""


def parse_llm_response(
    response_text: str, chunk_idx: int, chunk_start_pct: float
) -> List[Dict]:
    """Parse an LLM viral-clip JSON response."""
    try:
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        chunk_clips = json.loads(response_text.strip())
        for clip in chunk_clips:
            clip["_chunk_idx"] = chunk_idx
            clip["_chunk_start_pct"] = chunk_start_pct
        return chunk_clips
    except Exception as exc:
        logger.warning("shorts.score.parse_llm_failed", error=str(exc))
        return []


def _chunk_transcript(transcript: str, chunk_size: int = 6000, overlap: int = 500):
    chunks = []
    if not transcript:
        return chunks
    step = max(1, chunk_size - overlap)
    for i in range(0, len(transcript), step):
        chunk = transcript[i : i + chunk_size]
        chunk_start_pct = i / len(transcript)
        chunks.append((chunk, chunk_start_pct, i))
    return chunks


def analyze_with_anthropic(transcript: str, video_title: str) -> List[Dict]:
    """Use Anthropic Claude to mine viral clips from a transcript."""
    try:
        import anthropic

        from src.config import get_settings

        settings = get_settings()
        if not settings.anthropic_api_key:
            logger.warning("shorts.score.no_anthropic_key")
            return []
    except Exception as exc:
        logger.warning("shorts.score.anthropic_unavailable", error=str(exc))
        return []

    chunks = _chunk_transcript(transcript)
    if not chunks:
        return []

    system_prompt = get_viral_clip_system_prompt()
    logger.info(
        "shorts.score.anthropic_chunks", count=len(chunks), chars=len(transcript)
    )

    def analyze_chunk(args):
        chunk_idx, transcript_chunk, chunk_start_pct = args
        try:
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": get_viral_clip_user_prompt(
                            video_title,
                            chunk_idx,
                            len(chunks),
                            transcript_chunk,
                        ),
                    }
                ],
            )
            return parse_llm_response(
                response.content[0].text, chunk_idx, chunk_start_pct
            )
        except Exception as exc:
            logger.warning(
                "shorts.score.anthropic_chunk_failed",
                chunk=chunk_idx + 1,
                error=str(exc),
            )
            return None

    chunk_args = [
        (idx, chunk, start_pct)
        for idx, (chunk, start_pct, _) in enumerate(chunks)
    ]
    all_clips: List[Dict] = []
    any_failed = False
    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as executor:
        futures = {executor.submit(analyze_chunk, args): args[0] for args in chunk_args}
        for future in as_completed(futures):
            result = future.result()
            if result is None:
                any_failed = True
            elif result:
                all_clips.extend(result)

    if any_failed and not all_clips:
        return []
    return all_clips


def analyze_with_groq_llm(transcript: str, video_title: str) -> List[Dict]:
    """Use Groq's free LLM as a fallback for viral clip mining."""
    try:
        from groq import Groq
    except ImportError:
        logger.warning("shorts.score.groq_missing")
        return []

    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        logger.warning("shorts.score.no_groq_key")
        return []

    chunks = _chunk_transcript(transcript)
    if not chunks:
        return []
    system_prompt = get_viral_clip_system_prompt()

    def analyze_chunk(args):
        chunk_idx, transcript_chunk, chunk_start_pct = args
        try:
            client = Groq(api_key=groq_key)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=1500,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": get_viral_clip_user_prompt(
                            video_title,
                            chunk_idx,
                            len(chunks),
                            transcript_chunk,
                        ),
                    },
                ],
            )
            return parse_llm_response(
                response.choices[0].message.content, chunk_idx, chunk_start_pct
            )
        except Exception as exc:
            logger.warning(
                "shorts.score.groq_chunk_failed",
                chunk=chunk_idx + 1,
                error=str(exc),
            )
            return []

    chunk_args = [
        (idx, chunk, start_pct)
        for idx, (chunk, start_pct, _) in enumerate(chunks)
    ]
    all_clips: List[Dict] = []
    with ThreadPoolExecutor(max_workers=min(2, len(chunks))) as executor:
        futures = {executor.submit(analyze_chunk, args): args[0] for args in chunk_args}
        for future in as_completed(futures):
            clips = future.result()
            if clips:
                all_clips.extend(clips)
    return all_clips


def analyze_with_synthetic(transcript: str, video_title: str) -> List[Dict]:
    """Use Synthetic (OpenAI-compatible OSS models) as an LLM fallback.

    Synthetic hosts open-weight models like Llama 3.3 70B, Qwen3 Coder, GLM,
    and Kimi under a single subscription. Useful when Anthropic credits are
    exhausted or Groq is rate-limited.
    """
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("shorts.score.synthetic_missing")
        return []

    from src.config import get_settings

    settings = get_settings()
    if not settings.synthetic_api_key:
        logger.warning("shorts.score.no_synthetic_key")
        return []

    chunks = _chunk_transcript(transcript)
    if not chunks:
        return []
    system_prompt = get_viral_clip_system_prompt()
    logger.info(
        "shorts.score.synthetic_chunks",
        count=len(chunks),
        chars=len(transcript),
        model=settings.synthetic_model,
    )

    def analyze_chunk(args):
        chunk_idx, transcript_chunk, chunk_start_pct = args
        try:
            client = OpenAI(
                api_key=settings.synthetic_api_key,
                base_url=settings.synthetic_base_url,
            )
            response = client.chat.completions.create(
                model=settings.synthetic_model,
                max_tokens=1500,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": get_viral_clip_user_prompt(
                            video_title,
                            chunk_idx,
                            len(chunks),
                            transcript_chunk,
                        ),
                    },
                ],
            )
            return parse_llm_response(
                response.choices[0].message.content or "",
                chunk_idx,
                chunk_start_pct,
            )
        except Exception as exc:
            logger.warning(
                "shorts.score.synthetic_chunk_failed",
                chunk=chunk_idx + 1,
                error=str(exc),
            )
            return []

    chunk_args = [
        (idx, chunk, start_pct)
        for idx, (chunk, start_pct, _) in enumerate(chunks)
    ]
    all_clips: List[Dict] = []
    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as executor:
        futures = {executor.submit(analyze_chunk, args): args[0] for args in chunk_args}
        for future in as_completed(futures):
            clips = future.result()
            if clips:
                all_clips.extend(clips)
    return all_clips


def analyze_with_llm(
    transcript: str,
    video_title: str,
    # Budget attribution. The shorts highlight miner historically bypassed
    # ``LLMClient`` entirely, so its parallel multi-chunk Anthropic calls
    # were unbounded. We now pre-check the user's daily $ cap against
    # the worst-case fan-out, and record each successful chunk afterwards
    # so the spend actually shows up on their meter.
    user_id: Optional[int] = None,
    plan: str = "free",
) -> List[Dict]:
    """Try Anthropic → Synthetic → Groq, with WARNING-level fallback logs.

    Fallback engagement is logged at WARNING so it's visible even when the
    root log level is WARNING (the default). A final success log tells you
    which provider actually produced clips — grep ``shorts.score.llm_used``.
    """
    # Pre-check: estimate worst-case spend (Anthropic Sonnet @ 1500
    # max_tokens × N chunks) and refuse if it would blow the budget.
    # This is conservative — if Anthropic is unavailable we fall back
    # to free providers and never actually spend.
    try:
        from src.features.llm_client import (
            _check_budget,
            _effective_user_id,
            _estimate_cost,
            _record_usage,
        )

        chunks_est = max(1, (len(transcript) // 14000) + 1)
        per_chunk_cost = _estimate_cost(
            "claude-sonnet-4-20250514",
            input_tokens=4000,  # rough — system prompt + chunk
            output_tokens=1500,
        )
        worst_case = per_chunk_cost * chunks_est

        effective_uid = _effective_user_id(user_id)
        within, spent, limit = _check_budget(effective_uid, plan)
        if not within or (limit > 0 and spent + worst_case > limit):
            logger.warning(
                "shorts.score.budget_block",
                user_id=user_id,
                spent_usd=spent,
                projected_usd=round(worst_case, 4),
                limit_usd=limit,
                chunks=chunks_est,
            )
            # Skip LLM-based mining entirely; caller will rely on
            # regex-derived highlights. We don't raise because the
            # shorts feature is *augmented* by LLM, not gated on it.
            return []
    except Exception as exc:
        # Pre-check is best-effort. If the LLM module isn't importable
        # for some reason, we fall through and the existing path runs.
        logger.warning("shorts.score.budget_precheck_failed", error=str(exc))
        effective_uid = None  # disable post-record below
        per_chunk_cost = 0.0

    clips = analyze_with_anthropic(transcript, video_title)
    if clips:
        logger.warning("shorts.score.llm_used", provider="anthropic", clips=len(clips))
        # Best-effort post-record so the spend accumulates on the meter.
        try:
            if effective_uid is not None:
                _record_usage(
                    effective_uid, "anthropic", "claude-sonnet-4-20250514",
                    "shorts.score", 0, 0, per_chunk_cost * max(1, len(clips)),
                    success=True,
                )
        except Exception:
            pass
        return clips

    logger.warning("shorts.score.llm_fallback", from_="anthropic", to="synthetic")
    clips = analyze_with_synthetic(transcript, video_title)
    if clips:
        logger.warning("shorts.score.llm_used", provider="synthetic", clips=len(clips))
        return clips

    logger.warning("shorts.score.llm_fallback", from_="synthetic", to="groq")
    clips = analyze_with_groq_llm(transcript, video_title)
    if clips:
        logger.warning("shorts.score.llm_used", provider="groq", clips=len(clips))
        return clips

    logger.warning("shorts.score.llm_all_failed")
    return []


def merge_llm_highlights(
    regex_highlights: List[Highlight],
    llm_clips: List[Dict],
    transcript_data: Dict,
    target_duration: int,
) -> List[Highlight]:
    """Merge LLM-found clips into a list of regex-derived highlights."""
    if not llm_clips:
        return regex_highlights

    segments = transcript_data.get("segments", [])
    video_duration = transcript_data.get("duration", 600)

    MAX_CLIP_DURATION = 60
    MIN_CLIP_DURATION = 20
    IDEAL_DURATION = 35

    for clip in llm_clips:
        try:
            start_text = clip.get("start_sentence", "")
            end_text = clip.get("end_sentence", "")

            start_seg = fuzzy_find_text(start_text, segments, search_from_end=False)
            if start_seg:
                start_time = max(0, start_seg["start"] - 1.5)
            else:
                chunk_pct = clip.get("_chunk_start_pct", 0)
                position = clip.get("approximate_position", "middle")
                base_time = chunk_pct * video_duration
                divisor = max(len(llm_clips), 1)
                if position == "early":
                    start_time = base_time
                elif position == "late":
                    start_time = base_time + (video_duration / divisor) * 0.7
                else:
                    start_time = base_time + (video_duration / divisor) * 0.35

            end_seg = fuzzy_find_text(end_text, segments, search_from_end=True)
            if end_seg:
                base_end = end_seg["end"]
                end_time = find_natural_end(
                    segments,
                    start_time,
                    min_duration=MIN_CLIP_DURATION,
                    max_duration=MAX_CLIP_DURATION,
                )
                if end_time < base_end + 5:
                    end_time = min(base_end + 15, start_time + MAX_CLIP_DURATION)
            else:
                end_time = find_natural_end(
                    segments,
                    start_time,
                    min_duration=MIN_CLIP_DURATION,
                    max_duration=IDEAL_DURATION + 10,
                )

            duration = end_time - start_time
            if duration > MAX_CLIP_DURATION:
                end_time = start_time + MAX_CLIP_DURATION
                duration = MAX_CLIP_DURATION
            elif duration < MIN_CLIP_DURATION:
                end_time = start_time + IDEAL_DURATION
                duration = IDEAL_DURATION

            clip_transcript = ""
            for seg in segments:
                if seg["start"] >= start_time - 1 and seg["end"] <= end_time + 1:
                    clip_transcript += seg["text"] + " "

            already_exists = any(
                abs(h.start_time - start_time) < 20 for h in regex_highlights
            )
            if already_exists:
                for h in regex_highlights:
                    if abs(h.start_time - start_time) < 20:
                        h.score = min(95, h.score + 10)
                        h.reason = "llm_validated"
                        if duration > h.duration and duration <= MAX_CLIP_DURATION:
                            h.end_time = end_time
                            h.duration = duration
                        if clip.get("suggested_title"):
                            h.suggested_title = clip["suggested_title"]
                        break
            else:
                regex_highlights.append(
                    Highlight(
                        start_time=start_time,
                        end_time=end_time,
                        duration=duration,
                        score=clip.get("score", 75),
                        reason="llm_detected",
                        transcript=clip_transcript.strip() or start_text,
                        hook_quality=clip.get("hook_quality", "medium"),
                        suggested_title=clip.get("suggested_title", ""),
                        crop_x=656,
                        crop_width=607,
                        crop_height=1080,
                    )
                )
        except Exception as exc:
            logger.warning("shorts.score.merge_llm_failed", error=str(exc))
            continue

    return regex_highlights


def apply_comment_signal(
    highlights: List[Highlight],
    comment_timestamps: List[Dict],
    video_duration: float,
) -> List[Highlight]:
    """Boost highlights near comment timestamps and seed new ones for hot mentions."""
    for highlight in highlights:
        for ct in comment_timestamps:
            if abs(highlight.start_time - ct["seconds"]) < 30:
                boost = min(15, ct["mention_count"] * 3 + ct["sentiment_score"] * 2)
                highlight.score = min(95, highlight.score + boost)
                highlight.reason = "comment_validated"

    for ct in comment_timestamps:
        already_covered = any(
            abs(h.start_time - ct["seconds"]) < 30 for h in highlights
        )
        if not already_covered and ct["mention_count"] >= 2:
            highlights.append(
                Highlight(
                    start_time=max(0, ct["seconds"] - 15),
                    end_time=min(video_duration, ct["seconds"] + 30),
                    duration=45,
                    score=50
                    + ct["mention_count"] * 10
                    + ct["sentiment_score"] * 5,
                    reason="comment_timestamp",
                    transcript=f"[From comments: {ct['context']}]",
                    hook_quality="medium",
                    suggested_title=f"The moment at {ct['timestamp']}",
                    crop_x=656,
                    crop_width=607,
                    crop_height=1080,
                )
            )

    return highlights


def heatmap_intensity(points: List[dict], start: float, end: float) -> Optional[float]:
    """Average 'most-replayed' value over [start, end] (overlap-weighted).

    ``points`` are ``[{start_time, end_time, value}]`` from VideoHeatmap — the
    public re-watch curve. Returns None when there's no overlap/data.
    """
    if not points or end <= start:
        return None
    total = weight = 0.0
    for p in points:
        ps, pe = float(p.get("start_time", 0)), float(p.get("end_time", 0))
        overlap = max(0.0, min(end, pe) - max(start, ps))
        if overlap > 0:
            total += float(p.get("value", 0)) * overlap
            weight += overlap
    return (total / weight) if weight else None


def apply_heatmap_boost(highlights: List[Highlight], points: List[dict],
                        video_duration: Optional[float] = None) -> List[Highlight]:
    """Re-rank clips by what viewers ACTUALLY re-watched (most-replayed heatmap).

    The keyword scorer only guesses at hooky language; the heatmap is real
    retention signal, so where it exists it dominates the ranking. No-op when the
    video has no heatmap (e.g. <~2 weeks old). Returns highlights sorted by the
    boosted score.
    """
    if not points or not highlights:
        return highlights
    vals = [float(p.get("value", 0)) for p in points]
    mean_v = (sum(vals) / len(vals)) if vals else 0.0
    if mean_v <= 0:
        return highlights
    for h in highlights:
        inten = heatmap_intensity(points, h.start_time, h.end_time)
        if inten is None:
            continue
        rel = inten / mean_v  # >1 = re-watched more than the video's average moment
        h.score = round(min(100.0, h.score * (0.4 + min(1.6, rel))), 1)
        if rel >= 1.25:
            h.reason = f"Viewers re-watched this {rel:.1f}× the video's average"
    highlights.sort(key=lambda h: h.score, reverse=True)
    return highlights
