"""POST /ai-writer/generate: description + tags + hooks pipeline."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["ai-writer"])


class AIWriterRequest(BaseModel):
    title: str
    category: str = "general"
    tone: str = "professional"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
# Defined inline (rather than in src/api/schemas/) because the AI-writer
# response is shaped by what AIWriter happens to return today — pulling
# the model into shared schemas would imply it's a stable public
# contract that other services should mirror, and that isn't true yet.


class AIWriterDescription(BaseModel):
    text: str = Field(..., description="Generated description body")
    word_count: int = Field(..., ge=0, description="Word count of the body")
    has_cta: bool = Field(..., description="Whether the description ends with a CTA")
    has_timestamps: bool = Field(
        ..., description="Whether the description includes chapter timestamps"
    )


class AIWriterTags(BaseModel):
    tags: list[str] = Field(..., description="Full ordered tag list")
    primary_tags: list[str] = Field(
        ..., description="Highest-intent tags, surfaced first in YouTube Studio"
    )
    secondary_tags: list[str] = Field(
        ..., description="Long-tail tags for discovery"
    )


class AIWriterHook(BaseModel):
    text: str = Field(..., description="The hook script (first 3-5 seconds)")
    type: str = Field(
        ..., description="Hook archetype — see /hooks/types for the catalog"
    )
    why_it_works: str = Field(
        ..., description="One-line rationale for why this hook is effective"
    )
    duration: float = Field(
        ..., ge=0, description="Estimated read-aloud duration in seconds"
    )


class AIWriterResponse(BaseModel):
    """Full description + tags + hooks generation result."""

    description: AIWriterDescription
    tags: AIWriterTags
    hooks: list[AIWriterHook] = Field(
        ..., description="5 hook variations the user can pick from"
    )


@router.post("/ai-writer/generate", response_model=AIWriterResponse)
@limiter.limit(Tier.LLM_HEAVY)
async def generate_ai_content(
    request: Request,
    body: AIWriterRequest,
    current_user: User = Depends(get_current_user),
) -> AIWriterResponse:
    """Generate description, tags, and hooks using AIWriter (auth required)."""
    try:
        from src.features.ai_writer import AIWriter

        writer = AIWriter()
        # Attribute every LLM call below to this user so budget enforcement
        # works (was previously uncapped — see llm_client safety-net audit).
        writer.set_budget_context(current_user.id, current_user.plan or "free")

        description = writer.generate_description(
            title=body.title,
            category=body.category,
            video_summary=f"Tone: {body.tone}",
        )
        tags = writer.generate_tags(
            title=body.title,
            category=body.category,
        )
        hooks = writer.generate_hooks(
            title=body.title,
            category=body.category,
            num_options=5,
        )

        return AIWriterResponse(
            description=AIWriterDescription(
                text=description.description,
                word_count=description.word_count,
                has_cta=description.has_cta,
                has_timestamps=description.has_timestamps,
            ),
            tags=AIWriterTags(
                tags=tags.tags,
                primary_tags=tags.primary_tags,
                secondary_tags=tags.secondary_tags,
            ),
            hooks=[
                AIWriterHook(
                    text=h.script,
                    type=h.hook_type,
                    why_it_works=h.why_it_works,
                    duration=h.duration_seconds,
                )
                for h in hooks.hooks
            ],
        )
    except Exception as e:
        logger.error(f"AI writer failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
