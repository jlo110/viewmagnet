"""Faceless video generator: /faceless/parse-script, /generate, /voices."""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["faceless"])


# ── Pydantic models ──────────────────────────────────────────────────────────

class ScriptSectionOut(BaseModel):
    name: str
    content: str
    duration_seconds: float
    start_time: float
    end_time: float


class ParseScriptRequest(BaseModel):
    script: str = Field(..., min_length=10, description="Full video script text.")


class ParseScriptResponse(BaseModel):
    sections: list[ScriptSectionOut]
    estimated_total_seconds: float
    word_count: int


class GenerateFacelessRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    script: str = Field(..., min_length=10)
    voice_id: str = Field(
        default="21m00Tcm4TlvDq8ikWAM",
        description="ElevenLabs voice ID. Use GET /voiceover/voices to list options.",
    )
    caption_style: str = Field(
        default="capcut",
        description="Caption animation style: capcut, subtitles, dynamic.",
    )
    include_broll: bool = Field(
        default=True,
        description="Whether to find and include B-roll footage from Pexels.",
    )


class FacelessProjectOut(BaseModel):
    project_id: str
    title: str
    status: str
    sections: list[ScriptSectionOut]
    estimated_duration_seconds: float
    voice_id: str
    caption_style: str
    output_path: Optional[str] = None


class BRollSuggestion(BaseModel):
    section: str
    clips: list[dict]


class BRollResponse(BaseModel):
    suggestions: list[BRollSuggestion]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/faceless/parse-script", response_model=ParseScriptResponse)
@limiter.limit(Tier.READ)
async def parse_script(
    request: Request,
    body: ParseScriptRequest,
    current_user: User = Depends(get_current_user),
) -> ParseScriptResponse:
    """Parse a script into sections with timing estimates.

    Use this before generating to preview how the script will be divided
    and to get total duration estimates.
    """
    try:
        from src.features.faceless_generator import ScriptParser

        sections = await asyncio.to_thread(ScriptParser.parse_script, body.script)
        total = sum(s.duration_seconds for s in sections)

        return ParseScriptResponse(
            sections=[
                ScriptSectionOut(
                    name=s.name,
                    content=s.content,
                    duration_seconds=s.duration_seconds,
                    start_time=s.start_time,
                    end_time=s.end_time,
                )
                for s in sections
            ],
            estimated_total_seconds=total,
            word_count=len(body.script.split()),
        )
    except Exception as e:
        logger.error("faceless.parse_script.error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/faceless/broll-suggestions", response_model=BRollResponse)
@limiter.limit(Tier.WRITE)
async def get_broll_suggestions(
    request: Request,
    body: ParseScriptRequest,
    current_user: User = Depends(get_current_user),
) -> BRollResponse:
    """Get B-roll clip suggestions for each script section.

    Searches Pexels for relevant clips without downloading them.
    Use the returned preview URLs to let users review selections before generating.
    """
    try:
        from src.features.faceless_generator import ScriptParser, FacelessVideoGenerator

        sections = await asyncio.to_thread(ScriptParser.parse_script, body.script)

        def _find() -> list[dict]:
            gen = FacelessVideoGenerator()
            # Build a dummy project to call find_broll
            from src.features.faceless_generator import FacelessVideoProject
            project = FacelessVideoProject(
                project_id="preview",
                title="preview",
                script=body.script,
                sections=sections,
            )
            return gen.find_broll(project, clips_per_section=3)

        suggestions_raw = await asyncio.to_thread(_find)

        return BRollResponse(
            suggestions=[
                BRollSuggestion(section=s["section"], clips=s["clips"])
                for s in suggestions_raw
            ]
        )
    except Exception as e:
        logger.error("faceless.broll_suggestions.error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/faceless/generate", response_model=FacelessProjectOut)
@limiter.limit(Tier.MEDIA_HEAVY)
async def generate_faceless_video(
    request: Request,
    body: GenerateFacelessRequest,
    current_user: User = Depends(get_current_user),
) -> FacelessProjectOut:
    """Generate a full faceless video.

    Orchestrates the complete pipeline: ElevenLabs voiceover → B-roll download
    → animated captions → FFmpeg render. This is a heavy synchronous operation
    that can take several minutes depending on script length.

    Returns the project object including the output file path when complete.
    """
    if body.caption_style not in {"capcut", "subtitles", "dynamic"}:
        raise HTTPException(
            status_code=422,
            detail="caption_style must be one of: capcut, subtitles, dynamic",
        )

    try:
        from src.features.faceless_generator import FacelessVideoGenerator

        def _generate():
            gen = FacelessVideoGenerator()
            return gen.generate_full_video(
                title=body.title,
                script=body.script,
                voice_id=body.voice_id,
                caption_style=body.caption_style,
                include_broll=body.include_broll,
            )

        project = await asyncio.to_thread(_generate)

        logger.info(
            "faceless.generate.complete",
            user_id=current_user.id,
            project_id=project.project_id,
            status=project.status,
        )

        return FacelessProjectOut(
            project_id=project.project_id,
            title=project.title,
            status=project.status,
            sections=[
                ScriptSectionOut(
                    name=s.name,
                    content=s.content,
                    duration_seconds=s.duration_seconds,
                    start_time=s.start_time,
                    end_time=s.end_time,
                )
                for s in project.sections
            ],
            estimated_duration_seconds=sum(s.duration_seconds for s in project.sections),
            voice_id=project.voice_id,
            caption_style=project.caption_style,
            output_path=project.output_path,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("faceless.generate.error", user_id=current_user.id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
