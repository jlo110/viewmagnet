"""Hook analyzer API (Phase 8.6) — score a clip's opening seconds.

Upload a clip (or just paste the opening transcript + title) and get an
explainable hook report: measured visual energy (motion / cuts / brightness
from the first ~8s of frames) + an LLM rubric (instant clarity, curiosity or
stakes, visual energy, payoff promise) with the single highest-impact fix and
rewritten opening lines. The packaging-rubric pattern, applied to the opening.
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User
from src.features.hook_analyzer import analyze_clip_file, analyze_hook

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["hook-analyzer"])

_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100MB — short clips, not full videos
_ALLOWED_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}


@router.post("/hook/analyze")
@limiter.limit(Tier.LLM_HEAVY)
async def hook_analyze(
    request: Request,  # noqa: ARG001 — required by slowapi limiter
    file: Optional[UploadFile] = File(default=None),
    transcript: Optional[str] = Form(default=None),
    title: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_user),
):
    """Score a hook. Provide a clip file, an opening transcript, or both.

    With a file, visual metrics are measured from the first ~8s of frames and
    fed into the rubric; transcript/title sharpen the verbal judgment.
    """
    if file is None and not (transcript or "").strip() and not (title or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide a clip file, a transcript, or a title.",
        )

    plan = getattr(current_user, "plan", None) or "free"

    if file is None:
        report = analyze_hook(
            transcript=transcript, title=title,
            user_id=current_user.id, plan=plan,
        )
    else:
        suffix = os.path.splitext(file.filename or "")[1].lower()
        if suffix not in _ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported file type '{suffix}'. Use one of: "
                f"{', '.join(sorted(_ALLOWED_SUFFIXES))}",
            )
        data = await file.read()
        if len(data) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Clip too large (max 100MB). Trim to the opening seconds.",
            )
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            report = analyze_clip_file(
                tmp_path, transcript=transcript, title=title,
                user_id=current_user.id, plan=plan,
            )
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    if report.get("error") == "llm_unavailable" and not report.get("visual_metrics"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hook analysis is temporarily unavailable.",
        )
    return report
