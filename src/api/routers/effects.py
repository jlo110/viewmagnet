"""AI Video Effects: /effects/analyze, /effects/apply."""
from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from typing import Optional

import structlog
import shutil
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["effects"])


class VideoEffectsAnalyzeRequest(BaseModel):
    """Request to analyze video for effects."""
    transcript: str
    duration: float
    fps: int = 30
    width: int = 1080
    height: int = 1920
    intensity: str = "medium"  # subtle, medium, dramatic


class EffectSegment(BaseModel):
    """One effect window in the timeline. The exact set of fields per
    segment varies by effect (zoom segments have ``zoom_factor``, shake
    segments have ``amplitude``, etc.) so we accept additional
    properties — the canonical fields below are always present."""

    start_time: float = Field(..., ge=0, description="When the effect starts (seconds)")
    end_time: float = Field(..., ge=0, description="When the effect ends (seconds)")
    effect_type: str = Field(
        ..., description="zoom | shake | flash | speed_ramp | colour_grade | …"
    )

    model_config = {"extra": "allow"}


class VideoEffectsAnalyzeResponse(BaseModel):
    segments: list[EffectSegment] = Field(..., description="Effect windows along the timeline")
    filter_string: str = Field(
        ..., description="FFmpeg -vf filter graph ready to apply via /effects/apply"
    )
    intensity: str = Field(..., description="subtle | medium | dramatic")
    segment_count: int = Field(..., ge=0)


_BINARY_EFFECT_VIDEO_RESPONSES: dict[int | str, dict] = {
    200: {
        "description": "MP4 with effects applied.",
        "content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}},
    },
}


@router.post("/effects/analyze", response_model=VideoEffectsAnalyzeResponse)
@limiter.limit(Tier.LLM_HEAVY)
async def analyze_video_effects(
    request: Request,
    body: VideoEffectsAnalyzeRequest,
    current_user: User = Depends(get_current_user),
) -> VideoEffectsAnalyzeResponse:
    """Analyze video transcript and generate AI-powered effects configuration.

    Returns effect segments + FFmpeg filter string for enhanced engagement.
    """
    try:
        from src.features.ai_video_effects import EffectIntensity, VideoEffectsGenerator

        generator = VideoEffectsGenerator()
        # Budget attribution + LLM_HEAVY rate-limit (was previously
        # uncapped and unrate-limited — see budget audit).
        generator.set_budget_context(current_user.id, current_user.plan or "free")
        intensity = EffectIntensity(body.intensity)
        config = generator.analyze_and_generate_effects(
            transcript=body.transcript,
            duration=body.duration,
            fps=body.fps,
            width=body.width,
            height=body.height,
            intensity=intensity,
        )

        return VideoEffectsAnalyzeResponse(
            segments=[EffectSegment(**seg) for seg in config.to_dict()["segments"]],
            filter_string=config.filter_string,
            intensity=config.intensity.value,
            segment_count=len(config.segments),
        )
    except Exception as e:
        logger.error(f"Effects analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/effects/apply",
    response_class=FileResponse,
    responses=_BINARY_EFFECT_VIDEO_RESPONSES,
)
@limiter.limit(Tier.MEDIA_HEAVY)
async def apply_video_effects(
    request: Request,
    background_tasks: BackgroundTasks,
    filter_string: str = Form(...),
    video_url: Optional[str] = Form(default=None),
    video_file: Optional[UploadFile] = File(default=None),
    current_user: User = Depends(get_current_user),
):
    """Apply an FFmpeg effects filter to a video (auth required)."""
    tmpdir = None
    try:
        from src.features.ai_video_effects import VideoEffectsGenerator

        # Create temp dir manually so it persists until FileResponse streams
        tmpdir = tempfile.mkdtemp(prefix="effects_")
        job_id = str(uuid.uuid4())[:8]

        if video_file:
            input_path = os.path.join(tmpdir, f"{job_id}_input.mp4")
            with open(input_path, "wb") as f:
                content = await video_file.read()
                f.write(content)
        elif video_url:
            input_path = os.path.join(tmpdir, f"{job_id}_input.mp4")
            cmd = [
                "yt-dlp", "-f", "best[height<=720]",
                "-o", input_path,
                "--no-playlist",
                video_url,
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        else:
            raise HTTPException(
                status_code=400, detail="Either video_url or video_file required"
            )

        output_path = os.path.join(tmpdir, f"{job_id}_effects.mp4")
        sanitized_filter = VideoEffectsGenerator.sanitize_filter_string(filter_string)

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", sanitized_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "copy",
            output_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)

        # Schedule cleanup after response is sent
        background_tasks.add_task(shutil.rmtree, tmpdir, ignore_errors=True)

        return FileResponse(
            output_path,
            media_type="video/mp4",
            filename="video_with_effects.mp4",
        )
    except subprocess.TimeoutExpired:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=504, detail="Video processing timed out")
    except HTTPException:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except Exception as e:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        logger.error(f"Effects apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
