"""Shorts Creator: /shorts/detect-highlights, /shorts/extract-clip."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["shorts"])


class ShortsDetectRequest(BaseModel):
    video_url: Optional[str] = None
    transcript: Optional[str] = None
    max_highlights: int = 5


class ClipExtractRequest(BaseModel):
    video_url: str
    start_time: float
    end_time: float
    format: str = "mp4"  # mp4 or vertical


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ShortHighlight(BaseModel):
    start_time: float = Field(..., ge=0, description="Clip start in seconds (source video)")
    end_time: float = Field(..., ge=0, description="Clip end in seconds (source video)")
    duration: float = Field(..., ge=0, description="Clip duration in seconds")
    text: str = Field(..., description="Transcript of the highlighted segment")
    score: float = Field(
        ..., ge=0.0, le=100.0, description="0-100 virality / hook-worthiness score"
    )
    reason: str = Field(..., description="One-line explanation for why this moment was picked")
    hook_type: Optional[str] = Field(
        default=None,
        description="Detected hook archetype if the clip leads with a strong hook",
    )
    suggested_title: str = Field(..., description="Auto-generated Short title for the clip")


class ShortsDetectResponse(BaseModel):
    highlights: list[ShortHighlight]
    total_found: int = Field(..., ge=0, description="Number of highlights returned")
    best_moment: Optional[str] = Field(
        default=None, description="Transcript of the single highest-scoring moment"
    )
    video_title: Optional[str] = None
    video_duration: Optional[float] = Field(default=None, ge=0)
    transcript_length: int = Field(
        default=0, ge=0, description="Total transcript length in characters"
    )
    message: Optional[str] = Field(
        default=None,
        description=(
            "Non-error explanatory message (e.g. 'no spoken hooks detected — likely "
            "a music video'). Null on success."
        ),
    )


_BINARY_VIDEO_RESPONSES: dict[int | str, dict] = {
    200: {
        "description": "MP4 clip stream (downloadable via Content-Disposition).",
        "content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}},
    },
}


@router.post("/shorts/detect-highlights", response_model=ShortsDetectResponse)
@limiter.limit(Tier.MEDIA_HEAVY)
async def detect_shorts_highlights(
    request: Request,
    body: ShortsDetectRequest,
    current_user: User = Depends(get_current_user),
) -> ShortsDetectResponse:
    """Detect viral-worthy highlights for Shorts (auth required)."""
    try:
        from src.features.shorts_creator import ShortsCreator
        from src.features.shorts.models import TranscriptUnavailable

        creator = ShortsCreator()
        # Attribute the (potentially expensive multi-chunk) LLM-based
        # highlight miner to this user so it counts against their budget.
        creator.set_budget_context(current_user.id, current_user.plan or "free")

        if body.video_url:
            try:
                analysis = creator.analyze_youtube_video(
                    youtube_url=body.video_url,
                    num_clips=body.max_highlights,
                )
            except ValueError as ve:
                # Bad input (e.g. malformed YouTube URL): user can fix it.
                logger.warning("shorts.detect.bad_input", error=str(ve))
                raise HTTPException(status_code=400, detail=str(ve))
            except TranscriptUnavailable as tu:
                # Transcript genuinely couldn't be obtained. 422 (not 500) with
                # an actionable message; the user can paste a transcript instead.
                logger.info("shorts.detect.transcript_unavailable", url=body.video_url)
                raise HTTPException(status_code=422, detail=str(tu))
        elif body.transcript:
            word_count = len(body.transcript.split())
            if word_count < 12:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "That transcript is too short to find highlights. Paste at "
                        "least a few sentences of spoken content (aim for 30+ words)."
                    ),
                )
            estimated_duration = max(60, min(600, (word_count / 150) * 60))

            analysis = creator.analyze_from_text(
                transcript_text=body.transcript,
                video_title="User Provided",
                video_duration=estimated_duration,
                num_clips=body.max_highlights,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Add a YouTube URL or paste a transcript to detect highlights.",
            )

        highlights_data = [
            ShortHighlight(
                start_time=h.start_time,
                end_time=h.end_time,
                duration=h.duration,
                text=h.transcript,
                score=max(0.0, min(100.0, float(h.score))),
                reason=h.reason,
                hook_type=h.hook_quality,
                suggested_title=h.suggested_title,
            )
            for h in analysis.highlights
        ]

        return ShortsDetectResponse(
            highlights=highlights_data,
            total_found=len(highlights_data),
            best_moment=analysis.highlights[0].transcript if analysis.highlights else None,
            video_title=analysis.video_title,
            video_duration=analysis.video_duration,
            transcript_length=len(analysis.transcript_full) if analysis.transcript_full else 0,
            message=(
                None if highlights_data else
                "No viral moments detected. This video may be a song/music video, or "
                "lacks spoken hook phrases. Try a video with more narration/dialogue."
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Shorts detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/shorts/extract-clip",
    response_class=FileResponse,
    responses=_BINARY_VIDEO_RESPONSES,
)
@limiter.limit(Tier.MEDIA_HEAVY)
async def extract_clip(
    request: Request,
    body: ClipExtractRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Extract a clip from a YouTube video and return it for download (auth required).

    Uses ``yt-dlp --download-sections`` so only the requested segment is fetched.
    """
    video_id_match = re.search(
        r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", body.video_url
    )
    if not video_id_match:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    video_id = video_id_match.group(1)
    duration = body.end_time - body.start_time

    if duration <= 0 or duration > 120:
        raise HTTPException(
            status_code=400, detail="Clip duration must be between 1-120 seconds"
        )

    job_id = str(uuid.uuid4())[:8]
    temp_dir = tempfile.mkdtemp(prefix=f"clip_{job_id}_")
    output_file = os.path.join(temp_dir, f"clip_{video_id}_{int(body.start_time)}s.mp4")

    try:
        logger.info(
            f"Extracting clip: {video_id} from {body.start_time}s "
            f"to {body.end_time}s"
        )

        if not shutil.which("yt-dlp"):
            raise HTTPException(
                status_code=500,
                detail="yt-dlp not installed on server. Please install: pip install yt-dlp",
            )

        cmd = [
            "yt-dlp",
            "--download-sections", f"*{body.start_time}-{body.end_time}",
            "-f", (
                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                "best[height<=720][ext=mp4]/best"
            ),
            "--merge-output-format", "mp4",
            "-o", output_file,
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            f"https://youtube.com/watch?v={video_id}",
        ]
        logger.info(f"Running: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            logger.error(f"yt-dlp failed: {result.stderr}")
            cmd_simple = [
                "yt-dlp",
                "--download-sections", f"*{body.start_time}-{body.end_time}",
                "-f", "best",
                "-o", output_file,
                "--no-playlist",
                f"https://youtube.com/watch?v={video_id}",
            ]
            result = subprocess.run(cmd_simple, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to extract clip: {result.stderr[:200]}",
                )

        if not os.path.exists(output_file):
            for f in os.listdir(temp_dir):
                if f.endswith(".mp4"):
                    output_file = os.path.join(temp_dir, f)
                    break
            else:
                raise HTTPException(
                    status_code=500, detail="Clip extraction failed - no output file"
                )

        file_size = os.path.getsize(output_file)
        logger.info(f"Clip extracted: {output_file} ({file_size} bytes)")

        if body.format == "vertical":
            vertical_file = output_file.replace(".mp4", "_vertical.mp4")
            if shutil.which("ffmpeg"):
                crop_cmd = [
                    "ffmpeg", "-y",
                    "-i", output_file,
                    "-vf", "crop=ih*9/16:ih",
                    "-c:a", "copy",
                    vertical_file,
                ]
                subprocess.run(crop_cmd, capture_output=True, timeout=60)
                if os.path.exists(vertical_file):
                    output_file = vertical_file

        def cleanup():
            time.sleep(60)  # Keep file for 1 minute after response.
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(
                    "shorts.clip_cleanup_failed", temp_dir=temp_dir, error=str(e)
                )

        background_tasks.add_task(cleanup)

        filename = (
            f"clip_{video_id}_{int(body.start_time)}-"
            f"{int(body.end_time)}s.mp4"
        )

        return FileResponse(
            output_file,
            media_type="video/mp4",
            filename=filename,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=504, detail="Clip extraction timed out")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Clip extraction failed: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))
