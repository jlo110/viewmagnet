"""POST /thumbnails/generate, GET /thumbnails/templates, POST /thumbnails/generate-with-template."""
from __future__ import annotations

import base64
import uuid
from io import BytesIO
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["thumbnails"])


class ThumbnailGenerateRequest(BaseModel):
    title: str
    style_description: Optional[str] = None  # AI prompt for style
    prompt: Optional[str] = None  # Alias for style_description
    template: Optional[str] = None  # mrbeast, minimal, gaming, tech, bold, education
    category: str = "default"
    primary_color: str = "#00D4FF"
    text_color: str = "#FFFFFF"  # Text overlay color
    include_face: bool = False
    face_position: str = "right"
    text_position: str = "bottom-center"
    face_image_base64: Optional[str] = None  # Base64 encoded face image
    background_image_base64: Optional[str] = None  # Base64 encoded background image
    variations: int = 4


class ThumbnailVariation(BaseModel):
    id: int
    style: str
    image_url: str
    score: float
    tips: list[str]


class ThumbnailGenerateResponse(BaseModel):
    success: bool
    variations: list[ThumbnailVariation]
    generation_id: str
    credits_used: int
    template_used: Optional[str] = None


@router.post("/thumbnails/generate", response_model=ThumbnailGenerateResponse)
@limiter.limit(Tier.LLM_HEAVY)
async def generate_thumbnails(
    request: Request,
    body: ThumbnailGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate AI thumbnails (auth required)."""
    try:
        from src.features.thumbnail_generator import ThumbnailConfig, ThumbnailGenerator
    except ImportError as e:
        logger.error(f"Failed to import ThumbnailGenerator: {e}")
        raise HTTPException(status_code=500, detail="Thumbnail generator not available")

    generation_id = str(uuid.uuid4())[:8]

    template_map = {
        "Face Reaction": "mrbeast",
        "Money Maker": "bold",
        "VS Battle": "bold",
        "Shocking Hook": "bold",
        "Tech Dark": "tech",
        "Numbered List": "minimal",
        "Achievement": "bold",
        "Speed Run": "gaming",
    }
    backend_template = (
        template_map.get(body.template, body.template) if body.template else "auto"
    )

    try:
        generator = ThumbnailGenerator()
        generator.set_budget_context(current_user.id, current_user.plan or "free")
        config = ThumbnailConfig(
            title=body.title,
            category=body.category,
            template=backend_template,
            include_face=body.include_face,
            face_position=body.face_position,
            text_position=body.text_position,
            text_color=body.text_color,
        )

        face_image_bytes = None
        base_image_bytes = None

        if body.face_image_base64:
            try:
                face_image_bytes = base64.b64decode(body.face_image_base64)
            except Exception as e:
                logger.warning(f"Failed to decode face image: {e}")

        if body.background_image_base64:
            try:
                base_image_bytes = base64.b64decode(body.background_image_base64)
            except Exception as e:
                logger.warning(f"Failed to decode background image: {e}")

        result = generator.generate(
            config, base_image=base_image_bytes, face_image=face_image_bytes
        )

        variations: list[ThumbnailVariation] = []

        buffer = BytesIO()
        result.image.save(buffer, format="PNG")
        main_image_b64 = base64.b64encode(buffer.getvalue()).decode()

        if body.include_face:
            layout_names = ["Original Layout", "Face Left", "Face Right + Top Text", "Face Center"]
        else:
            layout_names = ["Original Layout", "Top Text", "Center Text", "Bottom Left Text"]

        variations.append(ThumbnailVariation(
            id=1,
            style=layout_names[0],
            image_url=f"data:image/png;base64,{main_image_b64}",
            score=result.score,
            tips=result.tips[:3],
        ))

        for i, var_img in enumerate(result.variations[: body.variations - 1], start=2):
            buffer = BytesIO()
            var_img.save(buffer, format="PNG")
            var_b64 = base64.b64encode(buffer.getvalue()).decode()
            layout_name = layout_names[i] if i < len(layout_names) else f"Layout {i}"
            variations.append(ThumbnailVariation(
                id=i,
                style=layout_name,
                image_url=f"data:image/png;base64,{var_b64}",
                score=result.score * (0.98 if i == 2 else 0.95),
                tips=result.tips[:2],
            ))

        logger.info(
            f"Generated {len(variations)} thumbnails",
            generation_id=generation_id,
            template=backend_template,
        )

        return ThumbnailGenerateResponse(
            success=True,
            variations=variations,
            generation_id=generation_id,
            credits_used=len(variations),
            template_used=backend_template,
        )

    except Exception as e:
        logger.error(f"Thumbnail generation failed: {e}")
        variations = []
        layouts = ["Original", "Face Left", "Top Text", "Center Text"][: body.variations]
        for i, layout in enumerate(layouts):
            color = body.primary_color.replace("#", "") if body.primary_color else "333333"
            placeholder_url = (
                f"https://placehold.co/1280x720/{color}/white?text="
                f"{layout.replace(' ', '+')}+Layout"
            )
            variations.append(ThumbnailVariation(
                id=i + 1,
                style=layout,
                image_url=placeholder_url,
                score=75.0,
                tips=["AI generation unavailable, using placeholder"],
            ))

        return ThumbnailGenerateResponse(
            success=False,
            variations=variations,
            generation_id=generation_id,
            credits_used=0,
            template_used=None,
        )


class ThumbnailTemplateInfo(BaseModel):
    id: str = Field(..., description="Template key — pass back via ThumbnailGenerateRequest.template")
    name: str = Field(..., description="Display name (e.g. 'MrBeast Style')")
    description: str
    text_color: Optional[str] = Field(default=None, description="Hex color for text overlay")
    gradient_colors: list[str] = Field(default_factory=list)


class ThumbnailTemplateListResponse(BaseModel):
    templates: list[ThumbnailTemplateInfo]


_FALLBACK_TEMPLATES = [
    ThumbnailTemplateInfo(id="mrbeast", name="MrBeast Style", description="Bold, high-energy, face on right"),
    ThumbnailTemplateInfo(id="minimal", name="Minimal Clean", description="Clean, professional, subtle"),
    ThumbnailTemplateInfo(id="gaming", name="Gaming/Esports", description="Neon, cyberpunk, high energy"),
    ThumbnailTemplateInfo(id="tech", name="Tech Review", description="Sleek, modern, professional"),
    ThumbnailTemplateInfo(id="bold", name="Bold Impact", description="Maximum attention, huge text"),
    ThumbnailTemplateInfo(id="education", name="Educational", description="Trust-building, clear, professional"),
]


@router.get("/thumbnails/templates", response_model=ThumbnailTemplateListResponse)
async def get_thumbnail_templates() -> ThumbnailTemplateListResponse:
    """Get available thumbnail templates from the ThumbnailGenerator."""
    try:
        from src.features.thumbnail_generator import ThumbnailGenerator

        generator = ThumbnailGenerator()
        templates = generator.get_templates()

        return ThumbnailTemplateListResponse(
            templates=[
                ThumbnailTemplateInfo(
                    id=key,
                    name=val.get("name", key),
                    description=val.get("description", ""),
                    text_color=val.get("text_color", "#FFFFFF"),
                    gradient_colors=val.get("gradient_colors", []),
                )
                for key, val in templates.items()
            ]
        )
    except Exception as e:
        logger.error(f"Failed to get templates: {e}")
        # Static fallback — keep the docs example useful even when the
        # backend generator can't import (e.g. missing optional deps).
        return ThumbnailTemplateListResponse(templates=_FALLBACK_TEMPLATES)


@router.post(
    "/thumbnails/generate-with-template", response_model=ThumbnailGenerateResponse
)
@limiter.limit(Tier.LLM_HEAVY)
async def generate_thumbnails_from_template(
    request: Request,
    title: str = Query(..., max_length=300),
    template: str = Query(..., max_length=64),
    category: str = Query(default="default", max_length=50),
    include_face: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
) -> ThumbnailGenerateResponse:
    """Template-style thumbnail generation wrapper (auth required)."""
    request.state.current_user = current_user
    body = ThumbnailGenerateRequest(
        title=title,
        template=template,
        category=category,
        include_face=include_face,
        variations=4,
    )
    return await generate_thumbnails(request, body, current_user)
