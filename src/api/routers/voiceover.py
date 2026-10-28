"""Voiceover generation (ElevenLabs): /voiceover/voices, /generate, /estimate."""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["voiceover"])


class VoiceoverRequest(BaseModel):
    """Request for voiceover generation."""
    text: str
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel by default
    stability: float = 0.5
    similarity_boost: float = 0.75


class VoiceInfo(BaseModel):
    """Voice information."""
    voice_id: str
    name: str
    category: str
    description: Optional[str] = None


class VoiceListResponse(BaseModel):
    voices: list[VoiceInfo]


class VoiceoverCostEstimate(BaseModel):
    character_count: int = Field(..., ge=0)
    estimated_cost_usd: float = Field(..., ge=0)
    estimated_duration_seconds: float = Field(..., ge=0)


_BINARY_AUDIO_RESPONSES: dict[int | str, dict] = {
    200: {
        "description": "MP3 voiceover stream (downloadable via Content-Disposition).",
        "content": {"audio/mpeg": {"schema": {"type": "string", "format": "binary"}}},
        "headers": {
            "X-Character-Count": {
                "schema": {"type": "string"},
                "description": "Total characters billed against the ElevenLabs quota for this generation",
            }
        },
    },
}


@router.get("/voiceover/voices", response_model=VoiceListResponse)
async def list_voiceover_voices() -> VoiceListResponse:
    """Get all available voices for voiceover generation."""
    try:
        from src.features.voiceover import ElevenLabsClient

        client = ElevenLabsClient()
        voices = client.list_voices()

        return VoiceListResponse(
            voices=[
                VoiceInfo(
                    voice_id=v.voice_id,
                    name=v.name,
                    category=v.category,
                    description=v.description,
                )
                for v in voices
            ]
        )
    except Exception as e:
        logger.error(f"Failed to list voices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/voiceover/generate",
    response_class=Response,
    responses=_BINARY_AUDIO_RESPONSES,
)
@limiter.limit(Tier.MEDIA_HEAVY)
async def generate_voiceover(
    request: Request,
    body: VoiceoverRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate voiceover audio from text (auth required).

    Returns the audio file as a downloadable MP3.
    """
    try:
        from src.features.voiceover import ElevenLabsClient

        client = ElevenLabsClient()
        result = client.generate_voiceover(
            text=body.text,
            voice_id=body.voice_id,
            stability=body.stability,
            similarity_boost=body.similarity_boost,
        )

        return Response(
            content=result.audio_data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "attachment; filename=voiceover.mp3",
                "X-Character-Count": str(result.character_count),
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to generate voiceover: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/voiceover/estimate", response_model=VoiceoverCostEstimate)
@limiter.limit(Tier.READ)
async def estimate_voiceover_cost(
    request: Request,
    text: str = Form(...),
    current_user: User = Depends(get_current_user),
) -> VoiceoverCostEstimate:
    """Estimate the cost of generating voiceover for given text (auth required)."""
    try:
        from src.features.voiceover import ElevenLabsClient

        client = ElevenLabsClient()
        return VoiceoverCostEstimate(**client.estimate_cost(text))
    except Exception as e:
        logger.error(f"Failed to estimate cost: {e}")
        raise HTTPException(status_code=500, detail=str(e))
