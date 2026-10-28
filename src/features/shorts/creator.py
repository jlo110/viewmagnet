"""High-level :class:`ShortsCreator` orchestrator.

Glues together :mod:`fetch`, :mod:`transcribe`, :mod:`score` and :mod:`clip`
into the public ``ShortsCreator`` API that the rest of the codebase consumes.
The split keeps the previously 2.5k LOC :mod:`src.features.shorts_creator`
module short, testable and easy to extend.
"""
from __future__ import annotations

from typing import List, Optional

import structlog

from src.features.shorts import clip as clip_mod
from src.features.shorts import fetch as fetch_mod
from src.features.shorts import score as score_mod
from src.features.shorts import transcribe as transcribe_mod
from src.features.shorts.models import (
    Highlight,
    ShortsAnalysis,
    TranscriptUnavailable,
)

logger = structlog.get_logger(__name__)


def _load_heatmap_points(video_id: str) -> Optional[list]:
    """The video's stored most-replayed curve, if we've captured it (older videos
    only). Lets clip selection rank by what viewers actually re-watched. Fails soft."""
    try:
        import json

        from sqlalchemy import select

        from src.database.connection import get_session
        from src.database.models import VideoHeatmap
        with get_session() as s:
            row = s.execute(
                select(VideoHeatmap.points).where(
                    VideoHeatmap.video_id == video_id, VideoHeatmap.has_heatmap.is_(True))
            ).scalar_one_or_none()
        return json.loads(row) if row else None
    except Exception as e:  # noqa: BLE001
        logger.debug("shorts.heatmap_lookup_failed", video_id=video_id, error=str(e)[:80])
        return None


MAX_CLIP_DURATION = 60
MIN_CLIP_DURATION = 15


class ShortsCreator:
    """AI-powered shorts creator that finds the best clips in long videos.

    Composes:

    * :mod:`fetch` for IDs / comments / transcripts
    * :mod:`transcribe` for Whisper providers
    * :mod:`score` for regex + LLM + audio ranking
    * :mod:`clip` for ffmpeg extraction & exports
    """

    def __init__(self, use_llm: bool = True, use_whisper: bool = True):
        self.use_llm = use_llm
        self.use_whisper = use_whisper
        self._viral_patterns = fetch_mod.load_viral_patterns()
        self._whisper_state = transcribe_mod.WhisperState(enabled=use_whisper)
        # See HookLab.set_budget_context. The router calls this once
        # so the LLM-based highlight miner attributes spend correctly.
        self._budget_user_id: Optional[int] = None
        self._budget_plan: str = "free"

    def set_budget_context(self, user_id: Optional[int], plan: str = "free") -> None:
        self._budget_user_id = user_id
        self._budget_plan = plan

    # ------------------------------------------------------------------ Fetching
    def extract_video_id(self, url: str) -> Optional[str]:
        return fetch_mod.extract_video_id(url)

    def fetch_youtube_comments(
        self, video_id: str, max_comments: int = 100
    ) -> List[str]:
        return fetch_mod.fetch_youtube_comments(video_id, max_comments=max_comments)

    # ------------------------------------------------------------------ Analyse
    def analyze_video(
        self,
        video_path: Optional[str] = None,
        audio_path: Optional[str] = None,
        transcript: Optional[str] = None,
        video_duration: Optional[float] = None,
        video_title: str = "Untitled",
        target_clip_duration: int = 45,
        num_clips: int = 5,
        heatmap_points: Optional[list] = None,
    ) -> ShortsAnalysis:
        """Analyse a local video/audio/transcript and return ranked highlights.

        ``heatmap_points`` (VideoHeatmap re-watch curve, optional) re-ranks clips by
        what viewers actually re-watched — the real signal vs the keyword heuristic.
        """
        logger.info("shorts.creator.analyze_video", title=video_title)

        if transcript:
            transcript_data = fetch_mod.parse_transcript(transcript)
        elif audio_path:
            transcript_data = transcribe_mod.transcribe_audio_file(
                audio_path, self._whisper_state
            )
        elif video_path:
            transcript_data = transcribe_mod.transcribe_video_file(
                video_path, self._whisper_state
            )
        else:
            raise ValueError("Must provide video_path, audio_path, or transcript")

        text_highlights = score_mod.analyze_transcript_for_highlights(
            transcript_data,
            target_clip_duration,
            num_clips * 2,
            self._viral_patterns,
        )

        audio_highlights: List[Highlight] = []
        audio_file = audio_path or video_path
        if audio_file:
            audio_highlights = score_mod.analyze_audio_energy(
                audio_file, target_clip_duration, num_clips
            )

        merged = score_mod.merge_highlights(
            text_highlights,
            audio_highlights,
            video_duration or transcript_data.get("duration", 600),
        )

        # Real re-watch signal (when available) beats the keyword guess.
        if heatmap_points:
            merged = score_mod.apply_heatmap_boost(merged, heatmap_points, video_duration)

        top_clips = sorted(merged, key=lambda h: h.score, reverse=True)[:num_clips]
        enhanced_clips = clip_mod.enhance_clips(top_clips, video_title)
        srt_content = clip_mod.generate_srt(transcript_data)

        return ShortsAnalysis(
            video_title=video_title,
            video_duration=video_duration or transcript_data.get("duration", 0),
            highlights=enhanced_clips,
            transcript_full=transcript_data.get("text", ""),
            captions_srt=srt_content,
        )

    def analyze_from_text(
        self,
        transcript_text: str,
        video_title: str = "Untitled",
        video_duration: float = 600,
        target_clip_duration: int = 45,
        num_clips: int = 5,
    ) -> ShortsAnalysis:
        """Run the pipeline on a plain transcript (no timestamps)."""
        logger.info("shorts.creator.analyze_text", title=video_title)

        sentences = fetch_mod.split_into_sentences(transcript_text)

        words_per_second = 2.5
        total_words = len(transcript_text.split())
        estimated_duration = total_words / words_per_second
        if video_duration:
            words_per_second = total_words / video_duration or words_per_second

        transcript_data = {
            "segments": [],
            "text": transcript_text,
            "duration": video_duration or estimated_duration,
        }
        current_time = 0.0
        for sentence in sentences:
            word_count = len(sentence.split())
            duration = word_count / max(words_per_second, 0.1)
            transcript_data["segments"].append(
                {
                    "start": current_time,
                    "end": current_time + duration,
                    "text": sentence,
                }
            )
            current_time += duration

        highlights = score_mod.analyze_transcript_for_highlights(
            transcript_data,
            target_clip_duration,
            num_clips * 3,
            self._viral_patterns,
        )

        if self.use_llm:
            llm_clips = score_mod.analyze_with_llm(
                transcript_text,
                video_title,
                user_id=self._budget_user_id,
                plan=self._budget_plan,
            )
            highlights = score_mod.merge_llm_highlights(
                highlights, llm_clips, transcript_data, target_clip_duration
            )

        for h in highlights:
            if h.duration > MAX_CLIP_DURATION:
                h.end_time = h.start_time + MAX_CLIP_DURATION
                h.duration = MAX_CLIP_DURATION
            if h.duration < MIN_CLIP_DURATION:
                h.end_time = h.start_time + MIN_CLIP_DURATION
                h.duration = MIN_CLIP_DURATION

        top_clips = score_mod.select_diverse_clips(
            highlights, video_duration, num_clips, min_gap_seconds=60
        )
        refined_clips = score_mod.refine_clip_boundaries(top_clips, transcript_data)
        normalized_clips = score_mod.normalize_scores(refined_clips)
        enhanced_clips = clip_mod.enhance_clips(normalized_clips, video_title)
        srt_content = clip_mod.generate_srt(transcript_data)

        return ShortsAnalysis(
            video_title=video_title,
            video_duration=video_duration,
            highlights=enhanced_clips,
            transcript_full=transcript_text,
            captions_srt=srt_content,
        )

    def analyze_with_comments(
        self,
        transcript: str,
        comments: List[str],
        video_title: str,
        video_duration: float,
        num_clips: int = 5,
    ) -> ShortsAnalysis:
        """Analyse a transcript and boost using YouTube comment timestamps."""
        logger.info("shorts.creator.analyze_with_comments", comments=len(comments))

        analysis = self.analyze_from_text(
            transcript_text=transcript,
            video_title=video_title,
            video_duration=video_duration,
            num_clips=num_clips * 2,
        )

        comment_timestamps = score_mod.extract_comment_timestamps(comments)
        analysis.highlights = score_mod.apply_comment_signal(
            analysis.highlights, comment_timestamps, video_duration
        )

        analysis.highlights = sorted(
            analysis.highlights, key=lambda h: h.score, reverse=True
        )[:num_clips]
        return analysis

    def analyze_youtube_video(
        self,
        youtube_url: str,
        num_clips: int = 5,
        fetch_comments: bool = True,
    ) -> ShortsAnalysis:
        """Full pipeline starting from a YouTube URL."""
        video_id = self.extract_video_id(youtube_url)
        if not video_id:
            raise ValueError(
                "That doesn't look like a valid YouTube link. Paste a full URL "
                "like https://www.youtube.com/watch?v=... or https://youtu.be/..."
            )

        logger.info("shorts.creator.analyze_youtube", video_id=video_id)

        video_title = f"Video {video_id}"
        video_duration: float = 600

        transcript = ""
        ts_data = fetch_mod.fetch_youtube_transcript(video_id)
        if ts_data:
            transcript = ts_data["text"]
            video_duration = ts_data["duration"] or video_duration

        comments: List[str] = []
        if fetch_comments:
            comments = self.fetch_youtube_comments(video_id, max_comments=200)

        if transcript:
            if comments:
                return self.analyze_with_comments(
                    transcript=transcript,
                    comments=comments,
                    video_title=video_title,
                    video_duration=video_duration,
                    num_clips=num_clips,
                )
            return self.analyze_from_text(
                transcript_text=transcript,
                video_title=video_title,
                video_duration=video_duration,
                num_clips=num_clips,
            )

        logger.info("shorts.creator.no_captions_fallback_whisper")
        try:
            whisper_transcript = transcribe_mod.transcribe_youtube_with_whisper(
                youtube_url, self._whisper_state
            )
        except Exception as exc:  # noqa: BLE001 - degrade to a clear message
            logger.warning("shorts.creator.whisper_failed", error=str(exc))
            whisper_transcript = None

        if whisper_transcript:
            return self.analyze_from_text(
                transcript_text=whisper_transcript,
                video_title=video_title,
                video_duration=video_duration or 600,
                num_clips=num_clips,
            )

        raise TranscriptUnavailable(
            "We couldn't pull a transcript for this video. This usually happens "
            "when the video has captions turned off, or when YouTube blocks "
            "automated transcript requests from servers. The quickest fix: open "
            "the video's transcript on YouTube (\u2026 menu \u2192 \u201cShow transcript\u201d), "
            "copy it, and paste it into the \u201cPaste transcript\u201d box instead."
        )

    # ------------------------------------------------------------------ Extract
    def extract_clips(
        self,
        video_path: str,
        analysis: ShortsAnalysis,
        output_dir: str,
        create_vertical: bool = True,
        use_smart_tracking: bool = False,
    ) -> ShortsAnalysis:
        return clip_mod.extract_clips(
            video_path,
            analysis,
            output_dir,
            create_vertical=create_vertical,
            use_smart_tracking=use_smart_tracking,
        )

    def extract_clips_from_url(
        self,
        youtube_url: str,
        output_dir: str,
        num_clips: int = 5,
    ) -> ShortsAnalysis:
        """Download a YouTube video, analyse it, and extract clips."""
        video_path = clip_mod.download_youtube_video(youtube_url, output_dir)
        video_id = self.extract_video_id(youtube_url) or youtube_url.split("=")[-1]
        analysis = self.analyze_video(
            video_path=video_path, video_title=video_id, num_clips=num_clips,
            heatmap_points=_load_heatmap_points(video_id),
        )
        logger.info("shorts.creator.extract_from_url.done")
        return self.extract_clips(video_path, analysis, output_dir)

    def export_clips_info(self, analysis: ShortsAnalysis, output_dir: str):
        return clip_mod.export_clips_info(analysis, output_dir)


def find_shorts(
    transcript: str,
    video_title: str = "Untitled",
    video_duration: float = 600,
    num_clips: int = 5,
) -> ShortsAnalysis:
    """Convenience wrapper that builds a fresh :class:`ShortsCreator`."""
    creator = ShortsCreator()
    return creator.analyze_from_text(
        transcript_text=transcript,
        video_title=video_title,
        video_duration=video_duration,
        num_clips=num_clips,
    )
