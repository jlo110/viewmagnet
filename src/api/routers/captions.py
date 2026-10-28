"""Animated captions: /captions/generate, /captions/export-video."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["captions"])


class CaptionGenerateRequest(BaseModel):
    video_url: Optional[str] = None
    transcript: Optional[str] = None
    style: str = "karaoke"  # karaoke, word_by_word, bounce, typewriter
    font: str = "montserrat"
    position: str = "bottom"
    primary_color: str = "#FFFFFF"  # Main text color
    secondary_color: str = "#00D4FF"  # Emphasized words color


def _format_srt_time(t: float) -> str:
    return (
        f"{int(t // 3600):02d}:{int((t % 3600) // 60):02d}:"
        f"{int(t % 60):02d},{int((t * 1000) % 1000):03d}"
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CaptionWord(BaseModel):
    text: str
    start: float = Field(..., ge=0, description="Start time in seconds")
    end: float = Field(..., ge=0, description="End time in seconds")


class CaptionSegment(BaseModel):
    start: float = Field(..., ge=0)
    end: float = Field(..., ge=0)
    text: str
    words: list[CaptionWord] = Field(
        ..., description="Per-word timing (empty list when only segment-level timing is available)"
    )


class CaptionGenerateResponse(BaseModel):
    """Animated-caption bundle: ready-to-burn ASS, a karaoke-style HTML
    preview, and the underlying segments for any custom renderer."""

    srt_content: str = Field(..., description="Raw SRT subtitle file content")
    ass_content: str = Field(..., description="Advanced SubStation Alpha (libass) content")
    html_preview: str = Field(
        ..., description="HTML snippet rendering the captions for a live preview"
    )
    segments: list[CaptionSegment]
    word_count: int = Field(..., ge=0)
    style_used: str = Field(..., description="Style key actually applied (e.g. 'capcut')")


_BINARY_CAPTIONED_VIDEO_RESPONSES: dict[int | str, dict] = {
    200: {
        "description": "MP4 with captions burned in.",
        "content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}},
    },
}


@router.post("/captions/generate", response_model=CaptionGenerateResponse)
@limiter.limit(Tier.MEDIA_HEAVY)
async def generate_captions(
    request: Request,
    body: CaptionGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate animated captions (auth required).

    Supports either a direct transcript string or a YouTube URL (which is
    transcribed via the public captions API, falling back to Whisper).
    """
    try:
        from src.features.animated_captions import AnimatedCaptionGenerator, CaptionStyle

        style_map = {
            "capcut": CaptionStyle.CAPCUT,
            "mrbeast": CaptionStyle.MRBEAST,
            "hormozi": CaptionStyle.HORMOZI,
            "tiktok": CaptionStyle.TIKTOK,
            "gaming": CaptionStyle.GAMING,
            "minimal": CaptionStyle.MINIMAL,
            "educational": CaptionStyle.EDUCATIONAL,
        }

        color_map = {
            "cyan": "#00FFFF",
            "yellow": "#FFFF00",
            "green": "#00FF00",
            "red": "#FF0000",
            "white": "#FFFFFF",
            "pink": "#FF69B4",
            "orange": "#FF8C00",
            "purple": "#9B59B6",
        }

        transcript_text: Optional[str] = None
        word_timing: list = []

        # 1) Caller supplied transcript directly.
        if body.transcript and body.transcript.strip():
            transcript_text = body.transcript.strip()
            logger.info("Using provided transcript for captions")

        # 2) Transcribe from a YouTube URL.
        elif body.video_url and body.video_url.strip():
            logger.info(f"Transcribing video for captions: {body.video_url}")
            try:
                import re

                from youtube_transcript_api import YouTubeTranscriptApi

                video_url = body.video_url.strip()
                video_id_match = re.search(
                    r"(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})", video_url
                )
                if not video_id_match:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid YouTube URL. Please provide a valid YouTube video URL.",
                    )

                video_id = video_id_match.group(1)
                try:
                    transcript_list = YouTubeTranscriptApi.get_transcript(video_id)

                    srt_lines: list[str] = []
                    for idx, entry in enumerate(transcript_list, 1):
                        start = entry["start"]
                        duration = entry.get("duration", 2.0)
                        end = start + duration
                        text = entry["text"].replace("\n", " ")

                        srt_lines.extend([
                            f"{idx}",
                            f"{_format_srt_time(start)} --> {_format_srt_time(end)}",
                            text,
                            "",
                        ])

                    srt_content = "\n".join(srt_lines)
                    logger.info(f"Got YouTube captions with {len(transcript_list)} segments")

                    caption_style = style_map.get(body.style, CaptionStyle.CAPCUT)
                    generator = AnimatedCaptionGenerator(style=caption_style)

                    primary = color_map.get(body.primary_color, body.primary_color)
                    secondary = color_map.get(body.secondary_color, body.secondary_color)
                    if primary.startswith("#"):
                        generator.style_config.primary_color = primary
                    if secondary.startswith("#"):
                        generator.style_config.secondary_color = secondary
                    generator.style_config.emphasize_key_words = True

                    segments = generator.parse_srt(srt_content)
                    ass_content = generator.generate_ass(segments)
                    html_preview = generator.generate_html_preview(segments)

                    return CaptionGenerateResponse(
                        srt_content=srt_content,
                        ass_content=ass_content,
                        html_preview=html_preview,
                        segments=[
                            CaptionSegment(
                                start=seg.start_time,
                                end=seg.end_time,
                                text=seg.text,
                                words=[
                                    CaptionWord(text=w.text, start=w.start_time, end=w.end_time)
                                    for w in (
                                        seg.words if hasattr(seg, "words") and seg.words else []
                                    )
                                ],
                            )
                            for seg in segments
                        ],
                        word_count=sum(len(seg.text.split()) for seg in segments),
                        style_used=body.style,
                    )
                except Exception as yt_error:
                    logger.warning(
                        f"YouTube captions not available: {yt_error}, falling back to Whisper"
                    )

                    try:
                        import whisper
                        import yt_dlp
                    except ImportError as ie:
                        raise HTTPException(
                            status_code=500,
                            detail=f"Missing dependencies for transcription: {ie}",
                        )

                    with tempfile.TemporaryDirectory() as tmpdir:
                        audio_path = os.path.join(tmpdir, "audio.mp3")
                        ydl_opts = {
                            "format": "bestaudio/best",
                            "outtmpl": audio_path.replace(".mp3", ".%(ext)s"),
                            "postprocessors": [{
                                "key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3",
                                "preferredquality": "128",
                            }],
                            "quiet": True,
                            "no_warnings": True,
                        }

                        logger.info("Downloading audio for transcription...")
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([video_url])

                        audio_file = None
                        for f in os.listdir(tmpdir):
                            if f.endswith(".mp3"):
                                audio_file = os.path.join(tmpdir, f)
                                break

                        if not audio_file:
                            raise HTTPException(
                                status_code=400, detail="Failed to download video audio"
                            )

                        logger.info("Transcribing with Whisper (small model for accuracy)...")
                        model = whisper.load_model("small")

                        initial_prompt = (
                            "This is a YouTube video transcript. Common terms include: "
                            "NFL, NBA, touchdown, end zone, quarterback, Jameis Winston, "
                            "Patrick Mahomes, LeBron James, Stephen Curry, Tom Brady, "
                            "Travis Kelce, Tyreek Hill, Josh Allen, Lamar Jackson."
                        )

                        result = model.transcribe(
                            audio_file,
                            language="en",
                            initial_prompt=initial_prompt,
                        )
                        transcript_text = result.get("text", "")
                        word_timing = result.get("segments", [])

                        if not transcript_text:
                            raise HTTPException(
                                status_code=400,
                                detail="Could not transcribe video audio",
                            )

                        # Post-process common transcription errors.
                        corrections = {
                            "m zone": "end zone",
                            "M zone": "end zone",
                            "Jamis": "Jameis",
                            "James Winston": "Jameis Winston",
                            "Jaymis": "Jameis",
                            "Mahommes": "Mahomes",
                            "Mahoms": "Mahomes",
                            "Lebron": "LeBron",
                            "Le Bron": "LeBron",
                            "Steph Curry": "Stephen Curry",
                            "Travis Kelsey": "Travis Kelce",
                            "Tyreek Hill": "Tyreek Hill",
                            "Tire reek": "Tyreek",
                            "Josh Alan": "Josh Allen",
                            "Lamarr": "Lamar",
                        }
                        for wrong, correct in corrections.items():
                            transcript_text = transcript_text.replace(wrong, correct)
                            for seg in word_timing:
                                if "text" in seg:
                                    seg["text"] = seg["text"].replace(wrong, correct)

                        logger.info(
                            "Whisper transcription complete: "
                            f"{len(transcript_text)} chars, {len(word_timing)} segments"
                        )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Video transcription failed: {e}")
                raise HTTPException(
                    status_code=400, detail=f"Failed to transcribe video: {str(e)}"
                )

        else:
            raise HTTPException(
                status_code=400,
                detail="Please provide either a video URL or transcript text.",
            )

        # Build SRT from transcript_text (+ optional word_timing).
        if word_timing:
            srt_lines = []
            for idx, segment in enumerate(word_timing, 1):
                start = segment.get("start", idx * 2)
                end = segment.get("end", start + 2)
                text = segment.get("text", "").strip()
                if not text:
                    continue
                srt_lines.extend([
                    f"{idx}",
                    f"{_format_srt_time(start)} --> {_format_srt_time(end)}",
                    text,
                    "",
                ])
            srt_content = "\n".join(srt_lines)
        else:
            words = (transcript_text or "").split()
            srt_lines = []
            chunk_size = 5
            time_per_word = 0.3

            for i in range(0, len(words), chunk_size):
                chunk = words[i:i + chunk_size]
                start_time = i * time_per_word
                end_time = (i + len(chunk)) * time_per_word
                srt_lines.extend([
                    f"{i // chunk_size + 1}",
                    f"{_format_srt_time(start_time)} --> {_format_srt_time(end_time)}",
                    " ".join(chunk),
                    "",
                ])

            srt_content = "\n".join(srt_lines)

        caption_style = style_map.get(body.style, CaptionStyle.CAPCUT)
        generator = AnimatedCaptionGenerator(style=caption_style)

        primary = color_map.get(body.primary_color, body.primary_color)
        secondary = color_map.get(body.secondary_color, body.secondary_color)
        if primary.startswith("#"):
            generator.style_config.primary_color = primary
        if secondary.startswith("#"):
            generator.style_config.secondary_color = secondary
        generator.style_config.emphasize_key_words = True

        segments = generator.parse_srt(srt_content)
        ass_content = generator.generate_ass(segments)
        html_preview = generator.generate_html_preview(segments)

        return CaptionGenerateResponse(
            srt_content=srt_content,
            ass_content=ass_content,
            html_preview=html_preview,
            segments=[
                CaptionSegment(
                    start=seg.start_time,
                    end=seg.end_time,
                    text=seg.text,
                    words=[
                        CaptionWord(text=w.text, start=w.start_time, end=w.end_time)
                        for w in (seg.words if hasattr(seg, "words") and seg.words else [])
                    ],
                )
                for seg in segments
            ],
            word_count=sum(len(seg.text.split()) for seg in segments),
            style_used=body.style,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Caption generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/captions/export-video",
    response_class=FileResponse,
    responses=_BINARY_CAPTIONED_VIDEO_RESPONSES,
)
@limiter.limit(Tier.MEDIA_HEAVY)
async def export_captioned_video(
    request: Request,
    ass_content: str = Form(...),
    video_url: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_user),
    video_file: Optional[UploadFile] = File(default=None),
):
    """Export a video with captions burned in via FFmpeg.

    Accepts either a ``video_url`` (YouTube) or an uploaded ``video_file``.
    Returns an MP4 file with the captions embedded.
    """
    if not video_url and not video_file:
        raise HTTPException(
            status_code=400, detail="Either video_url or video_file must be provided"
        )

    job_id = str(uuid.uuid4())[:8]
    temp_dir = tempfile.mkdtemp(prefix=f"caption_export_{job_id}_")

    try:
        input_video_path = None
        output_video_path = os.path.join(temp_dir, f"captioned_{job_id}.mp4")
        ass_path = os.path.join(temp_dir, f"captions_{job_id}.ass")

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        if video_url:
            logger.info(f"Downloading video for caption export: {video_url}")
            try:
                import yt_dlp
            except ImportError:
                raise HTTPException(
                    status_code=500,
                    detail="yt-dlp not installed. Please install: pip install yt-dlp",
                )

            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                info = ydl.extract_info(video_url, download=False)
                video_title = info.get("title", "video")
                duration = info.get("duration", 0)
                if duration > 900:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Video too long ({duration // 60}m {duration % 60}s). "
                            "Maximum length is 15 minutes for MP4 export."
                        ),
                    )

            input_video_path = os.path.join(temp_dir, f"input_{job_id}.mp4")
            ydl_opts = {
                "format": (
                    "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                    "best[height<=720][ext=mp4]/best"
                ),
                "outtmpl": input_video_path.replace(".mp4", ".%(ext)s"),
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
            }
            logger.info(f"Downloading video ({duration}s) for caption export...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            for f in os.listdir(temp_dir):
                if f.startswith(f"input_{job_id}") and f.endswith((".mp4", ".webm", ".mkv")):
                    input_video_path = os.path.join(temp_dir, f)
                    break

            if not input_video_path or not os.path.exists(input_video_path):
                raise HTTPException(status_code=500, detail="Failed to download video")
        else:
            logger.info(f"Processing uploaded video for caption export: {video_file.filename}")
            input_video_path = os.path.join(
                temp_dir, f"input_{job_id}{os.path.splitext(video_file.filename)[1]}"
            )
            with open(input_video_path, "wb") as f:
                content = await video_file.read()
                f.write(content)

            file_size = os.path.getsize(input_video_path)
            if file_size > 500 * 1024 * 1024:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Video file too large ({file_size / (1024 * 1024):.1f}MB). "
                        "Maximum size is 500MB."
                    ),
                )
            video_title = os.path.splitext(video_file.filename)[0]

        logger.info("Burning captions into video with FFmpeg...")

        input_filename = os.path.basename(input_video_path)
        output_filename = os.path.basename(output_video_path)
        ass_filename = os.path.basename(ass_path)

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", input_filename,
            "-vf", f"ass={ass_filename}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            output_filename,
        ]
        logger.info(f"FFmpeg command (in {temp_dir}): {' '.join(ffmpeg_cmd)}")
        result = subprocess.run(
            ffmpeg_cmd,
            capture_output=True,
            text=True,
            cwd=temp_dir,
            timeout=300,
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise HTTPException(
                status_code=500,
                detail=f"FFmpeg failed to process video: {result.stderr[:500]}",
            )

        if not os.path.exists(output_video_path):
            raise HTTPException(status_code=500, detail="FFmpeg did not produce output file")

        logger.info(f"Caption export complete: {output_video_path}")
        return FileResponse(
            path=output_video_path,
            media_type="video/mp4",
            filename=f"{video_title}_captioned.mp4",
            background=None,
        )

    except HTTPException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500, detail="Video processing timed out. Try a shorter video."
        )
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.error(f"Caption export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
