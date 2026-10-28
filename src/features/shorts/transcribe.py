"""Audio/video transcription backends for the shorts pipeline.

Provides a thin :class:`WhisperState` holder so callers can cache the local
Whisper model across many transcripts, plus stateless helpers for the
hosted Groq and OpenAI Whisper APIs.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class WhisperState:
    """Holds the cached local Whisper model (lazy-loaded once per process)."""

    model: Any = None
    enabled: bool = True

    def reset(self) -> None:
        self.model = None


def _load_local_whisper(state: WhisperState, name: str = "base") -> Any:
    if state.model is not None:
        return state.model
    try:
        import whisper
    except ImportError:
        logger.warning("shorts.transcribe.whisper_missing")
        return None
    logger.info("shorts.transcribe.load_local_model", name=name)
    state.model = whisper.load_model(name)
    return state.model


def transcribe_with_groq(audio_file: str, api_key: str) -> Optional[str]:
    """Transcribe a local audio file with Groq's hosted Whisper API."""
    try:
        from groq import Groq
    except ImportError:
        logger.warning("shorts.transcribe.groq_missing")
        return None

    try:
        logger.info("shorts.transcribe.groq_start")
        client = Groq(api_key=api_key)
        with open(audio_file, "rb") as f:
            transcription = client.audio.transcriptions.create(
                file=(audio_file, f.read()),
                model="whisper-large-v3",
                response_format="text",
            )
        transcript = (
            transcription if isinstance(transcription, str) else transcription.text
        )
        logger.info("shorts.transcribe.groq_done", chars=len(transcript))
        return transcript
    except Exception as exc:
        logger.warning("shorts.transcribe.groq_failed", error=str(exc))
        return None


def transcribe_with_openai(audio_file: str, api_key: str) -> Optional[str]:
    """Transcribe a local audio file with OpenAI's hosted Whisper API."""
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("shorts.transcribe.openai_missing")
        return None

    try:
        logger.info("shorts.transcribe.openai_start")
        client = OpenAI(api_key=api_key)
        with open(audio_file, "rb") as f:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )
        transcript = transcription.text
        logger.info("shorts.transcribe.openai_done", chars=len(transcript))
        return transcript
    except Exception as exc:
        logger.warning("shorts.transcribe.openai_failed", error=str(exc))
        return None


def transcribe_youtube_with_whisper(
    video_url: str, state: WhisperState
) -> Optional[str]:
    """Download audio for ``video_url`` and transcribe using the best backend.

    Tries Groq -> OpenAI -> local Whisper, in that order. Returns ``None`` if
    every backend fails or whisper is disabled.
    """
    if not state.enabled:
        return None

    try:
        import yt_dlp
    except ImportError:
        logger.warning("shorts.transcribe.yt_dlp_missing")
        return None

    try:
        logger.info("shorts.transcribe.download_audio", url=video_url)
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "audio.mp3")
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": audio_path.replace(".mp3", ".%(ext)s"),
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "128",
                    }
                ],
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            audio_file: Optional[str] = None
            for name in os.listdir(tmpdir):
                if name.endswith(".mp3"):
                    audio_file = os.path.join(tmpdir, name)
                    break

            if not audio_file or not os.path.exists(audio_file):
                logger.error("shorts.transcribe.audio_missing")
                return None

            groq_key = os.getenv("GROQ_API_KEY")
            if groq_key:
                transcript = transcribe_with_groq(audio_file, groq_key)
                if transcript:
                    return transcript

            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key and openai_key != "placeholder":
                transcript = transcribe_with_openai(audio_file, openai_key)
                if transcript:
                    return transcript

            model = _load_local_whisper(state)
            if model is None:
                logger.warning("shorts.transcribe.no_backend")
                return None

            result = model.transcribe(audio_file)
            transcript = result.get("text", "")
            logger.info(
                "shorts.transcribe.local_done", chars=len(transcript)
            )
            return transcript
    except Exception as exc:
        logger.error("shorts.transcribe.failed", error=str(exc))
        return None


def transcribe_audio_file(audio_path: str, state: WhisperState) -> Dict:
    """Transcribe a local audio file using local Whisper, returning segments."""
    model = _load_local_whisper(state)
    if model is None:
        return {"segments": [], "text": "", "duration": 0}

    logger.info("shorts.transcribe.audio_file", path=audio_path)
    result = model.transcribe(audio_path)
    segments = result.get("segments", []) or []
    duration = segments[-1]["end"] if segments else 0
    return {"segments": segments, "text": result.get("text", ""), "duration": duration}


def transcribe_video_file(video_path: str, state: WhisperState) -> Dict:
    """Transcribe a local video file (Whisper handles audio extraction)."""
    return transcribe_audio_file(video_path, state)
