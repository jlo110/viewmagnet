"""Voice Dubbing: /dubbing/languages, /translate, /status, /download."""
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
router = APIRouter(tags=["dubbing"])


class DubbingStartRequest(BaseModel):
    """Request to start a dubbing job."""
    video_url: Optional[str] = None
    target_language: str
    source_language: Optional[str] = None


class DubbingStatusResponse(BaseModel):
    """Response with dubbing job status."""
    dubbing_id: str
    status: str
    target_language: str
    source_language: Optional[str] = None
    expected_duration_sec: Optional[float] = None
    error: Optional[str] = None


class DubbingLanguageInfo(BaseModel):
    code: str = Field(..., description="ISO-style language code (e.g. 'es', 'pt-BR')")
    name: str = Field(..., description="Display name (e.g. 'Spanish')")


class DubbingLanguagesResponse(BaseModel):
    languages: list[DubbingLanguageInfo]
    count: int = Field(..., ge=0)


_BINARY_DUBBED_RESPONSES: dict[int | str, dict] = {
    200: {
        "description": "Dubbed MP4 stream (target language audio).",
        "content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}},
    },
}


@router.get("/dubbing/languages", response_model=DubbingLanguagesResponse)
async def get_dubbing_languages() -> DubbingLanguagesResponse:
    """Get list of supported languages for voice dubbing."""
    from src.features.voice_dubbing import get_supported_languages

    languages = get_supported_languages()
    return DubbingLanguagesResponse(
        languages=[
            DubbingLanguageInfo(code=code, name=name) for code, name in languages.items()
        ],
        count=len(languages),
    )


@router.post("/dubbing/translate", response_model=DubbingStatusResponse)
@limiter.limit(Tier.MEDIA_HEAVY)
async def start_dubbing_job_endpoint(
    request: Request,
    target_language: str = Form(...),
    source_language: Optional[str] = Form(default=None),
    video_url: Optional[str] = Form(default=None),
    video_file: Optional[UploadFile] = File(default=None),
    current_user: User = Depends(get_current_user),
):
    """Start a voice dubbing/translation job.

    Uploads the video to ElevenLabs and kicks off the dubbing process.
    Returns a job ID for status polling.
    """
    try:
        from src.features.voice_dubbing import (
            get_supported_languages,
            start_dubbing_job,
        )

        if target_language not in get_supported_languages():
            raise HTTPException(
                status_code=400, detail=f"Unsupported language: {target_language}"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
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

            job = start_dubbing_job(
                video_path=input_path,
                target_language=target_language,
                source_language=source_language,
            )

            return DubbingStatusResponse(
                dubbing_id=job.dubbing_id,
                status=job.status.value,
                target_language=job.target_language,
                source_language=job.source_language,
                expected_duration_sec=job.expected_duration_sec,
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Video download timed out")
    except Exception as e:
        logger.error(f"Dubbing start failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dubbing/status/{dubbing_id}", response_model=DubbingStatusResponse)
async def get_dubbing_status_endpoint(
    dubbing_id: str,
    current_user: User = Depends(get_current_user),
):
    """Check the status of a dubbing job. Poll until ``dubbed``/``failed``."""
    try:
        from src.features.voice_dubbing import check_dubbing_status

        job = check_dubbing_status(dubbing_id)
        return DubbingStatusResponse(
            dubbing_id=job.dubbing_id,
            status=job.status.value,
            target_language=job.target_language,
            source_language=job.source_language,
            expected_duration_sec=job.expected_duration_sec,
            error=job.error,
        )
    except Exception as e:
        logger.error(f"Dubbing status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/dubbing/download/{dubbing_id}",
    response_class=FileResponse,
    responses=_BINARY_DUBBED_RESPONSES,
)
async def download_dubbed_video(
    dubbing_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Download a completed dubbed video. Only works once status is ``dubbed``."""
    tmpdir = None
    try:
        from src.features.voice_dubbing import (
            check_dubbing_status,
            download_dubbed_result,
        )

        job = check_dubbing_status(dubbing_id)
        if job.status.value != "dubbed":
            raise HTTPException(
                status_code=400, detail=f"Job not complete. Status: {job.status.value}"
            )

        # Create temp dir manually so it persists until FileResponse streams
        tmpdir = tempfile.mkdtemp(prefix="dubbed_")
        output_path = os.path.join(tmpdir, f"dubbed_{dubbing_id}.mp4")
        download_dubbed_result(dubbing_id=dubbing_id, output_path=output_path)

        # Schedule cleanup after response is sent
        background_tasks.add_task(shutil.rmtree, tmpdir, ignore_errors=True)

        return FileResponse(
            output_path,
            media_type="video/mp4",
            filename=f"dubbed_{job.target_language}.mp4",
        )
    except HTTPException:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except Exception as e:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        logger.error(f"Dubbing download failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
