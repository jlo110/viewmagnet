"""Loop Designer: /loop/analyze, /loop/generate-endings."""
from __future__ import annotations

import os
import shutil
import tempfile
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["loop"])


class LoopAnalyzeRequest(BaseModel):
    transcript: Optional[str] = None
    video_url: Optional[str] = None  # Optional URL to download for visual/audio analysis


class LoopGenerateEndingsRequest(BaseModel):
    opening: str
    topic: str
    count: int = 5
    style: str = "natural"  # natural | callback | question | cliffhanger


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class LoopAnalysisResponse(BaseModel):
    """Loop-quality report. Mirrors LoopAnalysis.to_dict() in features/loop_designer.py."""

    overall_score: float = Field(..., ge=0, le=100, description="Combined 0-100 score")
    text_score: float = Field(..., ge=0, le=100, description="end-text → start-text similarity")
    visual_score: float = Field(..., ge=0, le=100, description="last-frame → first-frame similarity")
    audio_score: float = Field(..., ge=0, le=100, description="audio continuity at the loop boundary")
    has_stop_signals: bool = Field(
        ...,
        description="True if the ending contains 'thanks for watching' style cues that break the loop",
    )
    stop_signals_found: list[str]
    first_words: str = Field(..., description="First few words of the transcript")
    last_words: str = Field(..., description="Last few words of the transcript")
    issues: list[str]
    recommendations: list[str]
    text_method: str = Field(..., description="embedding | lexical | none")
    visual_method: str = Field(..., description="ssim | histogram | none")
    audio_method: str = Field(..., description="rms | none")


class LoopEndingsResponse(BaseModel):
    endings: list[str] = Field(
        ..., description="Candidate endings that loop back to the opening, ordered by LLM confidence"
    )


@router.post("/loop/analyze", response_model=LoopAnalysisResponse)
@limiter.limit(Tier.MEDIA_HEAVY)
async def analyze_loop_endpoint(
    request: Request,
    body: LoopAnalyzeRequest,
    current_user: User = Depends(get_current_user),
) -> LoopAnalysisResponse:
    """Analyze loop quality from a transcript + downloaded video (auth required)."""
    try:
        from src.features.loop_designer import get_loop_designer

        if not body.transcript and not body.video_url:
            raise HTTPException(
                status_code=400,
                detail="Provide at least one of: transcript, video_url",
            )

        local_video_path: Optional[str] = None
        cleanup_path: Optional[str] = None

        if body.video_url:
            try:
                import yt_dlp

                tmpdir = tempfile.mkdtemp(prefix="loop_")
                cleanup_path = tmpdir
                video_template = os.path.join(tmpdir, "video.%(ext)s")

                ydl_opts = {
                    "format": "best[height<=360]/best",
                    "outtmpl": video_template,
                    "quiet": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([body.video_url])

                for f in os.listdir(tmpdir):
                    if f.startswith("video."):
                        local_video_path = os.path.join(tmpdir, f)
                        break
            except Exception as e:
                logger.warning(f"Failed to download video for loop analysis: {e}")
                local_video_path = None

        try:
            analysis = get_loop_designer().analyze_loop(
                transcript=body.transcript,
                video_path=local_video_path,
            )
            return LoopAnalysisResponse(**analysis.to_dict())
        finally:
            if cleanup_path and os.path.exists(cleanup_path):
                shutil.rmtree(cleanup_path, ignore_errors=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Loop analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/loop/generate-endings", response_model=LoopEndingsResponse)
@limiter.limit(Tier.LLM_HEAVY)
async def generate_loop_endings_endpoint(
    request: Request,
    body: LoopGenerateEndingsRequest,
    current_user: User = Depends(get_current_user),
) -> LoopEndingsResponse:
    """Generate N possible endings that loop back to an opening (auth required)."""
    try:
        from src.features.loop_designer import get_loop_designer
        designer = get_loop_designer()
        designer.set_budget_context(current_user.id, current_user.plan or "free")
        endings = designer.generate_loop_endings(
            opening=body.opening,
            topic=body.topic,
            count=body.count,
            style=body.style,
        )
        return LoopEndingsResponse(endings=endings)
    except Exception as e:
        logger.error(f"Loop ending generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
