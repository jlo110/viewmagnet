"""POST /pacing/analyze: visual pacing + dead-air detection."""
from __future__ import annotations

import os
import shutil
import tempfile

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["pacing"])


class PacingAnalyzeRequest(BaseModel):
    video_url: str  # YouTube URL or direct video URL


# ---------------------------------------------------------------------------
# Response models — mirror src.features.pacing_analyzer.PacingReport.to_dict()
# ---------------------------------------------------------------------------


class DeadAirSegmentInfo(BaseModel):
    start_sec: float = Field(..., ge=0)
    end_sec: float = Field(..., ge=0)
    duration_sec: float = Field(..., ge=0)


class CutSuggestionInfo(BaseModel):
    timestamp_sec: float = Field(..., ge=0, description="When in the video the issue starts")
    issue: str = Field(
        ...,
        description="Issue category: long_silence | no_visual_change | slow_pace",
    )
    duration_sec: float = Field(..., ge=0, description="How long the problem persists")
    recommendation: str = Field(
        ..., description="Concrete edit suggestion (e.g. 'Cut 8s of silence at 1:23')"
    )


class PacingAnalysisResponse(BaseModel):
    """Pacing report — overall grade + per-dimension scores + cut list."""

    total_duration_sec: float = Field(..., ge=0)
    cut_count: int = Field(..., ge=0, description="Total scene cuts detected")
    avg_cut_interval_sec: float = Field(..., ge=0, description="Average seconds between cuts")
    longest_no_cut_sec: float = Field(
        ..., ge=0, description="Longest single shot duration without a cut"
    )
    dead_air_segments: list[DeadAirSegmentInfo] = Field(
        ..., description="Silent segments ≥ the dead-air threshold"
    )
    total_dead_air_sec: float = Field(..., ge=0)
    dead_air_percent: float = Field(..., ge=0, le=100)
    visual_pacing_score: float = Field(..., ge=0, le=100)
    dead_air_score: float = Field(..., ge=0, le=100)
    overall_score: float = Field(..., ge=0, le=100)
    grade: str = Field(..., description="Letter grade: A | B | C | D | F")
    cut_suggestions: list[CutSuggestionInfo]
    issues: list[str] = Field(..., description="Human-readable issue summaries")


@router.post("/pacing/analyze", response_model=PacingAnalysisResponse)
@limiter.limit(Tier.MEDIA_HEAVY)
async def analyze_pacing_endpoint(
    request: Request,
    body: PacingAnalyzeRequest,
    current_user: User = Depends(get_current_user),
) -> PacingAnalysisResponse:
    """Analyze a video's pacing -- scene cuts and dead-air segments (auth required).

    Downloads the video, runs ffmpeg scene-detection + silencedetect, and returns:
    - Overall pacing grade (A-F)
    - Visual pacing + dead-air sub-scores
    - Specific cut suggestions with timestamps
    """
    try:
        from src.features.pacing_analyzer import get_pacing_analyzer

        if not body.video_url:
            raise HTTPException(status_code=400, detail="video_url is required")

        try:
            import yt_dlp
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="yt-dlp not installed - cannot download video for pacing analysis",
            )

        tmpdir = tempfile.mkdtemp(prefix="pacing_")
        try:
            video_template = os.path.join(tmpdir, "video.%(ext)s")
            ydl_opts = {
                "format": "best[height<=720]/best",
                "outtmpl": video_template,
                "quiet": True,
                "no_warnings": True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([body.video_url])

            local_video_path = None
            for f in os.listdir(tmpdir):
                if f.startswith("video."):
                    local_video_path = os.path.join(tmpdir, f)
                    break

            if not local_video_path:
                raise HTTPException(status_code=500, detail="Failed to download video")

            report = get_pacing_analyzer().analyze(local_video_path)
            return PacingAnalysisResponse(**report.to_dict())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Pacing analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
