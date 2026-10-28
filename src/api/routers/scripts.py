"""Script generation: /scripts/generate, /scripts/frameworks, /scripts/generate-framework.

Also exposes ``POST /scripts/to-project`` (Week 9 Connected Tools)
which scaffolds a multi-clip Studio Project from a generated script
— one clip per section, so the creator can film + edit each piece
in the same Project that already encodes their structure.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_async_session
from src.database.models import (
    EditSession,
    StudioProject,
    StudioProjectClip,
    User,
)
from src.features.studio.project_spec import ProjectSpec
from src.features.studio.spec import AspectRatio

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["scripts"])


# ---------------------------------------------------------------------------
# Script → Project scaffolding (Week 9 Connected Tools)
# ---------------------------------------------------------------------------

# Sentinel URL scheme used when we don't yet have real footage for a
# script section. The Studio editor detects this scheme client-side
# (``isPlaceholderSource`` in frontend/studio/sourceUrl.ts) and shows a
# "replace with your footage" empty state instead of a broken
# ``<video>`` element. Keeping the scheme stable lets us also surface
# placeholder clips differently in lists ("needs footage") later.
SCRIPT_PLACEHOLDER_SCHEME = "placeholder"

_MAX_SECTIONS_PER_PROJECT = 20
_DEFAULT_SECTION_SECONDS = 30.0
_MIN_SECTION_SECONDS = 1.0
_MAX_SECTION_SECONDS = 600.0


def _placeholder_source_url(slug: str) -> str:
    """Build a stable placeholder source URL for a script section.

    Slugs are kept short, lowercased, and uuid-suffixed so two
    sections with the same name don't collide on the
    ``(user_id, clip_key)`` unique index.
    """
    safe = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")[:48] or "section"
    return f"{SCRIPT_PLACEHOLDER_SCHEME}://script-section/{safe}-{uuid.uuid4().hex[:8]}"


def _derive_clip_key(source_url: str, position: int) -> str:
    """Match the client's ``computeClipKey`` (sha256 of
    ``url|index|start|end``) so a refresh of the Studio editor
    resumes the same session row instead of inserting a duplicate.
    Start/end are always ``0`` and ``estimated_duration`` here, but
    we still include them so the hash stays stable per section. """
    payload = f"{source_url}|{position}|0|0".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ScriptSectionInput(BaseModel):
    """One ordered section in the source script.

    All fields default-friendly so the caller can be sloppy about
    durations on shorter (framework) scripts — the endpoint clamps
    to ``[1, 600]`` seconds per section and fills a sane default
    when missing. """

    name: str = Field(..., min_length=1, max_length=120)
    content: str = Field(default="", max_length=10_000)
    duration_seconds: float = Field(
        default=_DEFAULT_SECTION_SECONDS,
        ge=_MIN_SECTION_SECONDS,
        le=_MAX_SECTION_SECONDS,
    )


class ScriptToProjectRequest(BaseModel):
    """Create a StudioProject seeded with one placeholder clip per
    script section.

    The user is expected to follow up by opening each placeholder
    clip in Studio and either uploading footage or pointing it at a
    YouTube URL — we *don't* try to auto-source video. The point of
    this scaffold is to capture the script structure (and notes) in
    the same data model the user will be editing in.
    """

    title: str = Field(..., min_length=1, max_length=500)
    sections: List[ScriptSectionInput] = Field(..., min_length=1)
    default_aspect: AspectRatio = AspectRatio.PORTRAIT_9_16
    # Optional provenance — handy for debugging / analytics joins
    # ("which framework generated this scaffold?").
    framework: Optional[str] = Field(default=None, max_length=64)
    source_script_id: Optional[str] = Field(default=None, max_length=64)


@router.post(
    "/scripts/to-project",
    response_model=ProjectSpec,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(Tier.WRITE)
async def script_to_project_endpoint(
    request: Request,
    body: ScriptToProjectRequest,
    current_user: User = Depends(get_current_user),
):
    """Turn a generated script into a ready-to-edit StudioProject.

    For each section we create:

      * An ``EditSession`` with a ``placeholder://`` source URL and
        the section's text stashed in ``spec.notes`` so it shows up
        as a teleprompter in the Studio editor.
      * A ``StudioProjectClip`` linking that session into the new
        project at its ordered position.

    Returns the full ``ProjectSpec`` so the frontend can navigate
    straight to ``/dashboard/studio/project/{id}`` and see the rail
    already populated.
    """
    if len(body.sections) > _MAX_SECTIONS_PER_PROJECT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Too many sections ({len(body.sections)}); cap is "
                f"{_MAX_SECTIONS_PER_PROJECT}. Split your script first."
            ),
        )

    # Seed the project description from a compact rendering of the
    # script so the Distribution Hub handoff has something useful to
    # show before the creator edits it. We use the first 280 chars
    # of each section's content joined by "\n\n" — feels like a
    # post body, not a transcript dump.
    description_parts: List[str] = []
    for section in body.sections:
        snippet = (section.content or "").strip()
        if not snippet:
            continue
        if len(snippet) > 280:
            snippet = snippet[:277].rstrip() + "..."
        description_parts.append(f"{section.name}\n{snippet}")
    seed_description = "\n\n".join(description_parts) or None

    async with get_async_session() as db:
        project = StudioProject(
            user_id=current_user.id,
            title=body.title,
            description=seed_description,
            default_aspect=body.default_aspect.value,
        )
        db.add(project)
        await db.flush()  # need project.id before we link clips

        for position, section in enumerate(body.sections):
            source_url = _placeholder_source_url(section.name)
            clip_key = _derive_clip_key(source_url, position)
            duration = max(
                _MIN_SECTION_SECONDS,
                min(_MAX_SECTION_SECONDS, float(section.duration_seconds)),
            )

            # Minimal spec — captions enabled by default, source clip
            # window matches the estimated duration, section script
            # surfaced as creator notes. We deliberately keep this
            # spartan so the user can configure aspect / brand once
            # via the project-level settings instead of N times.
            spec_payload = {
                "version": 1,
                "clip": {
                    "source_url": source_url,
                    "source_clip_path": None,
                    "start_time": 0.0,
                    "end_time": duration,
                    "transcript": [],
                    "suggested_title": section.name,
                },
                "aspect_ratio": body.default_aspect.value,
                "captions": {"enabled": True},
                "notes": section.content or None,
                "script_section_meta": {
                    "section_index": position,
                    "section_name": section.name,
                    "estimated_duration_seconds": duration,
                    "framework": body.framework,
                    "source_script_id": body.source_script_id,
                },
            }

            edit_session = EditSession(
                user_id=current_user.id,
                clip_key=clip_key,
                source_video_url=source_url,
                source_clip_index=0,
                source_start_time=0.0,
                source_end_time=duration,
                title=section.name,
                spec=json.dumps(spec_payload),
            )
            db.add(edit_session)
            await db.flush()  # need edit_session.id

            clip = StudioProjectClip(
                project_id=project.id,
                edit_session_id=edit_session.id,
                position=position,
            )
            db.add(clip)

        project.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(project)

        logger.info(
            "script.to_project.created",
            project_id=project.id,
            user_id=current_user.id,
            section_count=len(body.sections),
            framework=body.framework,
        )

        # Import locally to avoid a circular import between the
        # scripts router and the projects router (they share
        # _project_to_spec but the projects module also imports
        # from features.billing which doesn't need to be pulled in
        # for every script-writer request).
        from src.api.routers.projects import _project_to_spec

        return await _project_to_spec(db, project)


class ScriptGenerateRequest(BaseModel):
    title: str
    style: str = "educational"  # educational, storytelling, tutorial, entertainment
    target_length_minutes: int = 10
    key_points: Optional[list[str]] = None
    tone: str = "professional"


class FrameworkScriptRequest(BaseModel):
    topic: str
    framework: str  # ScriptFramework value
    target_duration: int = 60
    additional_context: Optional[str] = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ScriptSection(BaseModel):
    name: str = Field(..., description="Display name for the section (e.g. 'Hook', 'Body', 'CTA')")
    duration: float = Field(..., ge=0, description="Estimated read-aloud duration in seconds")
    content: str = Field(..., description="The section's scripted text")
    notes: Optional[str] = Field(default=None, description="Director's notes / B-roll cues for this section")


class GeneratedScriptResponse(BaseModel):
    title: str
    estimated_duration: float = Field(..., ge=0, description="Total read-aloud duration in seconds")
    word_count: int = Field(..., ge=0)
    hook: str = Field(..., description="First 3-5 seconds — the most-watched part of the video")
    intro: str
    sections: list[ScriptSection]
    cta: str = Field(..., description="Call to action surfaced before the outro")
    outro: str


class FrameworkSectionTemplate(BaseModel):
    """One slot in a framework template — defines what the section is
    called and how long it's expected to be before any LLM call."""

    key: str = Field(..., description="Stable section key (e.g. 'hook', 'reveal')")
    label: str = Field(..., description="Human-readable label")
    duration: float = Field(..., ge=0, description="Target section duration in seconds")


class FrameworkInfo(BaseModel):
    """Metadata about one of the 4 viral script frameworks."""

    id: str = Field(..., description="ScriptFramework enum value (e.g. 'authority_myth_buster')")
    name: str = Field(..., description="Display name")
    primary_goal: str = Field(..., description="One-line goal of the framework")
    goal_description: str = Field(..., description="Longer-form explanation")
    sections: list[FrameworkSectionTemplate] = Field(
        ..., description="Ordered section templates the framework produces"
    )


class FrameworkListResponse(BaseModel):
    frameworks: list[FrameworkInfo]


class FrameworkScriptSection(BaseModel):
    key: str = Field(..., description="Section key (e.g. 'hook', 'reveal', 'proof')")
    label: str = Field(..., description="Display label")
    content: str
    duration: float = Field(..., ge=0)


class FrameworkScriptResponse(BaseModel):
    framework: str = Field(..., description="ScriptFramework enum value")
    framework_name: str
    primary_goal: str
    goal_description: str
    topic: str
    estimated_duration_sec: float = Field(..., ge=0)
    word_count: int = Field(..., ge=0)
    sections: list[FrameworkScriptSection]
    full_script: str = Field(..., description="All sections concatenated as one read-aloud script")


@router.post("/scripts/generate", response_model=GeneratedScriptResponse)
@limiter.limit(Tier.LLM_HEAVY)
async def generate_script_endpoint(
    request: Request,
    body: ScriptGenerateRequest,
    current_user: User = Depends(get_current_user),
) -> GeneratedScriptResponse:
    """Generate a video script using the ScriptWriter module (auth required)."""
    try:
        from src.features.script_writer import ScriptStyle, ScriptWriter

        style_map = {
            "educational": ScriptStyle.EDUCATIONAL,
            "storytelling": ScriptStyle.STORYTELLING,
            "tutorial": ScriptStyle.EDUCATIONAL,
            "entertainment": ScriptStyle.ENERGETIC,
            "casual": ScriptStyle.CASUAL,
            "professional": ScriptStyle.PROFESSIONAL,
            "energetic": ScriptStyle.ENERGETIC,
        }

        writer = ScriptWriter()

        if body.key_points:
            additional_context = (
                f"Key points to cover: {', '.join(body.key_points)}. "
                f"Tone: {body.tone}"
            )
        else:
            additional_context = f"Tone: {body.tone}"

        script = writer.generate_script(
            topic=body.title,
            category="general",
            target_duration=body.target_length_minutes * 60,
            style=style_map.get(body.style, ScriptStyle.EDUCATIONAL),
            additional_context=additional_context,
            # Plumb the auth context so the LLM call meters against the
            # right user's daily $ cap (was previously uncapped).
            user_id=current_user.id,
            plan=current_user.plan or "free",
        )

        return GeneratedScriptResponse(
            title=script.title,
            estimated_duration=script.total_duration,
            word_count=script.word_count,
            hook=script.hook,
            intro=script.intro,
            sections=[
                ScriptSection(
                    name=s.title,
                    duration=s.duration_estimate,
                    content=s.content,
                    notes=s.notes,
                )
                for s in script.sections
            ],
            cta=script.cta,
            outro=script.outro,
        )
    except Exception as e:
        logger.error(f"Script generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scripts/frameworks", response_model=FrameworkListResponse)
async def list_frameworks() -> FrameworkListResponse:
    """List the 4 viral frameworks with metadata."""
    try:
        from src.features.script_writer import get_framework_info
        raw = get_framework_info()
        # ``get_framework_info()`` returns a list of dicts; coerce to
        # the typed model so the docs example matches the real shape.
        return FrameworkListResponse(
            frameworks=[FrameworkInfo(**fw) for fw in raw]
        )
    except Exception as e:
        logger.error(f"Failed to list frameworks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/scripts/generate-framework", response_model=FrameworkScriptResponse
)
@limiter.limit(Tier.LLM_HEAVY)
async def generate_framework_script_endpoint(
    request: Request,
    body: FrameworkScriptRequest,
    current_user: User = Depends(get_current_user),
) -> FrameworkScriptResponse:
    """Generate a script using one of the 4 viral frameworks (auth required).

    Frameworks: Authority Myth-Buster, Delta Shift, Progressive Debunking, Lead Magnet.
    """
    try:
        from src.features.script_writer import (
            ScriptFramework,
            generate_framework_script,
        )

        try:
            framework = ScriptFramework(body.framework)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid framework. Must be one of: {[f.value for f in ScriptFramework]}",
            )

        script = generate_framework_script(
            topic=body.topic,
            framework=framework,
            target_duration=body.target_duration,
            additional_context=body.additional_context or "",
            user_id=current_user.id,
            plan=current_user.plan or "free",
        )

        return FrameworkScriptResponse(
            framework=script.framework.value,
            framework_name=script.framework_name,
            primary_goal=script.primary_goal,
            goal_description=script.goal_description,
            topic=script.topic,
            estimated_duration_sec=script.estimated_duration_sec,
            word_count=script.word_count,
            sections=[
                FrameworkScriptSection(
                    key=s.key,
                    label=s.label,
                    content=s.content,
                    duration=s.duration,
                )
                for s in script.sections
            ],
            full_script=script.to_full_script(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Framework script generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
