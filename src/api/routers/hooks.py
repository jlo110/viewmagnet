"""Hook Lab + Hook Overlay routes.

- ``/hooks/score`` / ``/hooks/rewrite`` / ``/hooks/types``: Competence-gap
  analysis (Hook Lab feature).
- ``/hooks/preview`` / ``/hooks/apply``: PNG/MP4 text-overlay generation
  (Hook Overlay feature) -- co-located here because they share the URL prefix.
"""
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
router = APIRouter(tags=["hooks"])


class HookScoreRequest(BaseModel):
    hook: str


class HookRewriteRequest(BaseModel):
    hook: str
    topic: str
    target_type: Optional[str] = None  # HookType value or None for mixed
    count: int = 5


class HookScoreResponse(BaseModel):
    hook: str
    overall_score: float
    detected_type: str
    type_description: str
    belief_challenge: float
    mistake_callout: float
    urgency: float
    specificity: float
    weakest_dimension: str
    strongest_dimension: str
    is_summary_pattern: bool
    rationale: str


class HookPreviewRequest(BaseModel):
    """Request to preview a hook overlay."""
    text: str
    position: str = "top"  # top, center, bottom
    font_scale: float = 1.0
    target_width: int = 1080


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HookRewriteResponse(BaseModel):
    """Result of ``/hooks/rewrite``: N stronger variants of a weak hook.

    The variants are plain strings — the caller can pipe each one
    back into ``/hooks/score`` to compare strength deltas. We
    deliberately don't bundle scores into this response because
    scoring is a separate LLM call that the agent might not need
    (and shouldn't be charged for) if it's just sampling rewrites.
    """

    rewrites: list[str] = Field(
        ..., description="Stronger hook variants ordered by the LLM's confidence"
    )


class HookTypeInfo(BaseModel):
    value: str = Field(..., description="HookType enum value (use this when calling /hooks/rewrite)")
    description: str = Field(..., description="One-line explanation of how the type works")
    is_strong: bool = Field(
        ...,
        description="False for `summary` (the weak baseline); True for every gap-engineered type",
    )


class HookTypeListResponse(BaseModel):
    types: list[HookTypeInfo]


@router.post("/hooks/score", response_model=HookScoreResponse)
@limiter.limit(Tier.LLM_HEAVY)
async def score_hook_endpoint(
    request: Request,
    body: HookScoreRequest,
    current_user: User = Depends(get_current_user),
):
    """Score a video hook on its competence-gap strength (auth required)."""
    try:
        from src.features.hook_lab import get_hook_lab
        lab = get_hook_lab()
        lab.set_budget_context(current_user.id, current_user.plan or "free")
        analysis = lab.score_gap(body.hook)
        return HookScoreResponse(
            hook=analysis.hook,
            overall_score=analysis.overall_score,
            detected_type=analysis.detected_type.value,
            type_description=analysis.type_description,
            belief_challenge=analysis.belief_challenge,
            mistake_callout=analysis.mistake_callout,
            urgency=analysis.urgency,
            specificity=analysis.specificity,
            weakest_dimension=analysis.weakest_dimension,
            strongest_dimension=analysis.strongest_dimension,
            is_summary_pattern=analysis.is_summary_pattern,
            rationale=analysis.rationale,
        )
    except Exception as e:
        logger.error(f"Hook scoring failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/hooks/rewrite", response_model=HookRewriteResponse)
@limiter.limit(Tier.LLM_HEAVY)
async def rewrite_hook_endpoint(
    request: Request,
    body: HookRewriteRequest,
    current_user: User = Depends(get_current_user),
) -> HookRewriteResponse:
    """Rewrite a weak hook into N gap-engineered alternatives (auth required)."""
    try:
        from src.features.hook_lab import HookType, get_hook_lab

        target_type = None
        if body.target_type:
            try:
                target_type = HookType(body.target_type)
            except ValueError:
                pass  # invalid type -> use mixed

        lab = get_hook_lab()
        lab.set_budget_context(current_user.id, current_user.plan or "free")
        rewrites = lab.rewrite_for_gap(
            weak_hook=body.hook,
            video_topic=body.topic,
            target_type=target_type,
            count=body.count,
        )
        return HookRewriteResponse(rewrites=rewrites)
    except Exception as e:
        logger.error(f"Hook rewrite failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hooks/types", response_model=HookTypeListResponse)
async def get_hook_types() -> HookTypeListResponse:
    """Get the list of available hook types with descriptions."""
    from src.features.hook_lab import HOOK_TYPE_DESCRIPTIONS, HookType

    return HookTypeListResponse(
        types=[
            HookTypeInfo(
                value=t.value,
                description=HOOK_TYPE_DESCRIPTIONS[t],
                is_strong=t != HookType.SUMMARY,
            )
            for t in HookType
        ]
    )


# ``/hooks/preview`` and ``/hooks/apply`` stream binary files
# (PNG / MP4). FastAPI doesn't know that from the function signature,
# so we explicitly mark the success response with the right media
# type — otherwise OpenAPI claims they return ``application/json``
# with a null body, and Scalar's "Try it" panel happily tries to
# parse the PNG as JSON.
_BINARY_FILE_RESPONSES: dict[int | str, dict] = {
    200: {
        "description": "Binary file stream (image or video).",
        "content": {
            "image/png": {"schema": {"type": "string", "format": "binary"}},
            "video/mp4": {"schema": {"type": "string", "format": "binary"}},
        },
    },
}


@router.post(
    "/hooks/preview",
    response_class=FileResponse,
    responses=_BINARY_FILE_RESPONSES,
)
@limiter.limit(Tier.LLM_HEAVY)
async def preview_hook_overlay(
    request: Request,
    body: HookPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate a hook overlay PNG preview (auth required)."""
    try:
        from src.features.hook_overlays import HookPosition, HookStyle, create_hook_image

        style = HookStyle(
            position=HookPosition(body.position),
            font_scale=body.font_scale,
        )

        image_path, _, _ = create_hook_image(
            text=body.text,
            target_width=body.target_width,
            style=style,
        )

        return FileResponse(
            image_path,
            media_type="image/png",
            filename="hook_preview.png",
        )
    except Exception as e:
        logger.error(f"Hook preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/hooks/apply",
    response_class=FileResponse,
    responses=_BINARY_FILE_RESPONSES,
)
@limiter.limit(Tier.MEDIA_HEAVY)
async def apply_hook_to_video_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    text: str = Form(...),
    position: str = Form(default="top"),
    font_scale: float = Form(default=1.0),
    video_url: Optional[str] = Form(default=None),
    video_file: Optional[UploadFile] = File(default=None),
    duration: Optional[float] = Form(default=None),
    current_user: User = Depends(get_current_user),
):
    """Apply a hook text overlay to a video (auth required).

    Accepts either ``video_url`` (YouTube) or an uploaded ``video_file``.
    """
    tmpdir = None
    try:
        from src.features.hook_overlays import add_hook_to_video

        # Create temp dir manually so it persists until FileResponse streams
        tmpdir = tempfile.mkdtemp(prefix="hook_")
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

        output_path = os.path.join(tmpdir, f"{job_id}_hooked.mp4")

        add_hook_to_video(
            video_path=input_path,
            text=text,
            output_path=output_path,
            position=position,
            font_scale=font_scale,
            duration=duration,
        )

        # Schedule cleanup after response is sent
        background_tasks.add_task(shutil.rmtree, tmpdir, ignore_errors=True)

        return FileResponse(
            output_path,
            media_type="video/mp4",
            filename="video_with_hook.mp4",
        )
    except subprocess.TimeoutExpired:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=504, detail="Video download timed out")
    except HTTPException:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except Exception as e:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        logger.error(f"Hook apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
