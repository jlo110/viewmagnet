"""Studio multi-clip projects API (Week 7).

Projects are the long-form editor: an ordered list of existing
``EditSession`` clips that the Studio stitches into a single render.
Each clip in a project is a FK to an ``EditSession``, never a copy,
so a clip can belong to multiple projects without divergence.

This router exposes:

* ``POST   /studio/projects``                           — create empty project
* ``GET    /studio/projects``                           — list user projects
* ``GET    /studio/projects/:id``                       — full ProjectSpec
* ``PATCH  /studio/projects/:id``                       — title/aspect/transition/brand
* ``DELETE /studio/projects/:id``                       — delete project (clips stay)
* ``POST   /studio/projects/:id/clips``                 — append an existing session
* ``PATCH  /studio/projects/:id/clips/:clipId``         — reorder / trim / transition
* ``DELETE /studio/projects/:id/clips/:clipId``         — ripple-delete

The render endpoint lives in ``src.api.routers.studio`` alongside the
single-clip render (so both share the polling shape); see
``src/features/studio/render_project.py`` for the job.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_async_session
from src.database.models import (
    EditSession,
    StudioProject,
    StudioProjectClip,
    User,
)
from src.features.billing.render_budget import (
    estimate_render_minutes,
    get_budget_snapshot,
    would_exceed_budget,
)
from src.features.studio.project_spec import (
    PROJECT_SPEC_VERSION,
    ProjectClipSpec,
    ProjectSpec,
)
from src.features.studio.spec import (
    AspectRatio,
    BrandKit,
    TransitionType,
)
from src.queue import enqueue_job
from src.queue.telemetry import (
    record_render_budget_blocked,
    record_render_queued,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["studio-projects"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ProjectCreateRequest(BaseModel):
    """Initial state for a new empty project."""

    title: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = Field(default=None, max_length=10_000)
    default_aspect: AspectRatio = AspectRatio.PORTRAIT_9_16


class ProjectUpdateRequest(BaseModel):
    """Partial update on the project row itself (not its clips)."""

    title: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = Field(default=None, max_length=10_000)
    default_aspect: Optional[AspectRatio] = None
    default_transition_type: Optional[TransitionType] = None
    default_transition_ms: Optional[int] = Field(default=None, ge=0, le=2000)
    brand_kit: Optional[BrandKit] = None


class ProjectClipAppendRequest(BaseModel):
    """Append an existing EditSession to the project as the last clip."""

    edit_session_id: int = Field(..., gt=0)
    trim_in_seconds: Optional[float] = Field(default=None, ge=0.0)
    trim_out_seconds: Optional[float] = Field(default=None, ge=0.0)
    transition_in_type: Optional[TransitionType] = None
    transition_in_ms: Optional[int] = Field(default=None, ge=0, le=2000)


class ProjectClipUpdateRequest(BaseModel):
    """Partial update on a single clip row. ``position`` triggers
    reorder; the API renumbers neighbors so positions stay contiguous."""

    position: Optional[int] = Field(default=None, ge=0)
    trim_in_seconds: Optional[float] = Field(default=None, ge=0.0)
    trim_out_seconds: Optional[float] = Field(default=None, ge=0.0)
    transition_in_type: Optional[TransitionType] = None
    transition_in_ms: Optional[int] = Field(default=None, ge=0, le=2000)


class ProjectListItem(BaseModel):
    """Compact row for the ``GET /studio/projects`` list view."""

    id: int
    title: str
    default_aspect: AspectRatio
    clip_count: int
    last_render_status: str
    last_render_url: Optional[str]
    updated_at: datetime


class ProjectRenderResponse(BaseModel):
    """Same shape as the single-session render response so the frontend
    can reuse its polling component."""

    job_id: Optional[str] = None
    project_id: int
    status: str
    last_render_url: Optional[str] = None
    progress: Optional[int] = None
    progress_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_brand_kit(project: StudioProject) -> BrandKit:
    """Parse the stored JSON into a BrandKit, falling back to defaults
    on any error so a corrupted blob never blocks the page from loading."""
    if not project.brand_kit_json:
        return BrandKit()
    try:
        return BrandKit.model_validate_json(project.brand_kit_json)
    except Exception:
        logger.warning(
            "studio.project.brand_kit_parse_failed",
            project_id=project.id,
        )
        return BrandKit()


def _row_to_clip_spec(
    clip_row: StudioProjectClip,
    session_row: EditSession,
) -> ProjectClipSpec:
    """Denormalize a project-clip row + its underlying session into the
    spec shape the UI expects."""
    return ProjectClipSpec(
        id=clip_row.id,
        edit_session_id=session_row.id,
        position=clip_row.position,
        clip_key=session_row.clip_key,
        title=session_row.title,
        source_url=session_row.source_video_url,
        source_start_time=session_row.source_start_time or 0.0,
        source_end_time=session_row.source_end_time or 0.0,
        session_render_url=session_row.last_render_url,
        session_render_status=session_row.last_render_status,  # type: ignore[arg-type]
        trim_in_seconds=clip_row.trim_in_seconds,
        trim_out_seconds=clip_row.trim_out_seconds,
        transition_in_type=(
            TransitionType(clip_row.transition_in_type)
            if clip_row.transition_in_type
            else None
        ),
        transition_in_ms=clip_row.transition_in_ms,
    )


async def _project_to_spec(
    db,
    project: StudioProject,
) -> ProjectSpec:
    """Build the full :class:`ProjectSpec` for a project row.

    Pulls every underlying EditSession in one query (no N+1) and zips
    them with the ordered project-clip rows.
    """
    clip_rows: List[StudioProjectClip] = list(
        (await db.execute(
            select(StudioProjectClip)
            .where(StudioProjectClip.project_id == project.id)
            .order_by(StudioProjectClip.position.asc())
        )).scalars().all()
    )

    clips: List[ProjectClipSpec] = []
    if clip_rows:
        session_ids = [c.edit_session_id for c in clip_rows]
        sessions = (
            await db.execute(
                select(EditSession).where(EditSession.id.in_(session_ids))
            )
        ).scalars().all()
        sessions_by_id = {s.id: s for s in sessions}
        for clip_row in clip_rows:
            session = sessions_by_id.get(clip_row.edit_session_id)
            if session is None:
                # The underlying session was deleted out from under us
                # (FK cascade should normally prevent this, but stay
                # defensive — surface as a missing clip rather than
                # crash the whole project view).
                logger.warning(
                    "studio.project.dangling_clip",
                    project_id=project.id,
                    clip_id=clip_row.id,
                )
                continue
            clips.append(_row_to_clip_spec(clip_row, session))

    return ProjectSpec(
        version=PROJECT_SPEC_VERSION,
        id=project.id,
        user_id=project.user_id,
        title=project.title,
        description=project.description,
        default_aspect=AspectRatio(project.default_aspect),
        default_transition_type=TransitionType(project.default_transition_type),
        default_transition_ms=project.default_transition_ms,
        brand_kit=_load_brand_kit(project),
        last_render_status=project.last_render_status,  # type: ignore[arg-type]
        last_render_url=project.last_render_url,
        last_render_error=project.last_render_error,
        render_progress=project.render_progress,
        render_progress_message=project.render_progress_message,
        clips=clips,
    )


async def _renumber_positions(db, project_id: int) -> None:
    """Re-pack ``position`` to a contiguous 0-indexed sequence.

    Called after every reorder / delete so the unique
    ``(project_id, position)`` index never sees gaps and the UI's
    drag-reorder math stays simple. Cheap — projects are small lists.
    """
    rows = (
        await db.execute(
            select(StudioProjectClip)
            .where(StudioProjectClip.project_id == project_id)
            .order_by(StudioProjectClip.position.asc(), StudioProjectClip.id.asc())
        )
    ).scalars().all()
    # Two-pass renumber to dodge the UNIQUE(project_id, position) index:
    # first move every row to an unreachable temporary slot, then snap
    # them down to the target positions.
    OFFSET = 1_000_000
    for i, row in enumerate(rows):
        row.position = OFFSET + i
    await db.flush()
    for i, row in enumerate(rows):
        row.position = i
    await db.flush()


async def _load_project_for_user(
    db,
    project_id: int,
    user_id: int,
) -> StudioProject:
    """Fetch a project row and 404 if missing / not owned by the user."""
    project = (
        await db.execute(
            select(StudioProject).where(
                StudioProject.id == project_id,
                StudioProject.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )
    return project


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------


@router.post("/studio/projects", response_model=ProjectSpec, status_code=status.HTTP_201_CREATED)
@limiter.limit(Tier.WRITE)
async def create_project(
    request: Request,
    body: ProjectCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """Create an empty project. Returns the freshly-created spec so the
    frontend can navigate straight to its edit view."""
    async with get_async_session() as db:
        project = StudioProject(
            user_id=current_user.id,
            title=body.title or "Untitled project",
            description=body.description,
            default_aspect=body.default_aspect.value,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        logger.info(
            "studio.project.created",
            project_id=project.id,
            user_id=current_user.id,
            default_aspect=project.default_aspect,
        )
        return await _project_to_spec(db, project)


@router.get("/studio/projects", response_model=List[ProjectListItem])
@limiter.limit(Tier.READ)
async def list_projects(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """List the user's projects newest-first, with clip counts joined in."""
    async with get_async_session() as db:
        projects = (
            (await db.execute(
                select(StudioProject)
                .where(StudioProject.user_id == current_user.id)
                .order_by(StudioProject.updated_at.desc())
                .limit(100)
            )).scalars().all()
        )
        # Compute clip counts in a single follow-up query.
        if projects:
            counts_rows = await db.execute(
                select(
                    StudioProjectClip.project_id,
                    # raw count(*) keeps us SQLite-friendly
                )
            )
            # Cheaper to just iterate per project given list cap of 100.
            counts: dict[int, int] = {}
            for p in projects:
                counts[p.id] = len((
                    await db.execute(
                        select(StudioProjectClip).where(
                            StudioProjectClip.project_id == p.id
                        )
                    )
                ).scalars().all())
        else:
            counts = {}

        return [
            ProjectListItem(
                id=p.id,
                title=p.title,
                default_aspect=AspectRatio(p.default_aspect),
                clip_count=counts.get(p.id, 0),
                last_render_status=p.last_render_status,
                last_render_url=p.last_render_url,
                updated_at=p.updated_at,
            )
            for p in projects
        ]


@router.get("/studio/projects/{project_id}", response_model=ProjectSpec)
@limiter.limit(Tier.READ)
async def get_project(
    request: Request,
    project_id: int,
    current_user: User = Depends(get_current_user),
):
    """Fetch one project + its ordered clips."""
    async with get_async_session() as db:
        project = await _load_project_for_user(db, project_id, current_user.id)
        return await _project_to_spec(db, project)


@router.patch("/studio/projects/{project_id}", response_model=ProjectSpec)
@limiter.limit(Tier.WRITE)
async def update_project(
    request: Request,
    project_id: int,
    body: ProjectUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """Patch the project row (title, defaults, brand kit).

    Brand-kit updates serialize the Pydantic model to JSON so the
    render job can hydrate it without depending on the DB schema.
    """
    async with get_async_session() as db:
        project = await _load_project_for_user(db, project_id, current_user.id)

        if body.title is not None:
            project.title = body.title
        if body.description is not None:
            # Empty string clears the description (lets the UI reset
            # it without needing a separate "delete" call).
            project.description = body.description or None
        if body.default_aspect is not None:
            project.default_aspect = body.default_aspect.value
        if body.default_transition_type is not None:
            project.default_transition_type = body.default_transition_type.value
        if body.default_transition_ms is not None:
            project.default_transition_ms = body.default_transition_ms
        if body.brand_kit is not None:
            project.brand_kit_json = body.brand_kit.model_dump_json()

        await db.commit()
        await db.refresh(project)
        return await _project_to_spec(db, project)


@router.delete("/studio/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(Tier.WRITE)
async def delete_project(
    request: Request,
    project_id: int,
    current_user: User = Depends(get_current_user),
):
    """Delete the project and all its clip-join rows.

    Does **not** delete the underlying ``EditSession``s — a clip can
    belong to multiple projects (or live independently in Drafts) so
    we leave those alone. The FK cascade handles the join rows.
    """
    async with get_async_session() as db:
        project = await _load_project_for_user(db, project_id, current_user.id)
        await db.delete(project)
        await db.commit()
        return None


# ---------------------------------------------------------------------------
# Project clip operations
# ---------------------------------------------------------------------------


@router.post(
    "/studio/projects/{project_id}/clips",
    response_model=ProjectSpec,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(Tier.WRITE)
async def append_clip(
    request: Request,
    project_id: int,
    body: ProjectClipAppendRequest,
    current_user: User = Depends(get_current_user),
):
    """Append an existing EditSession to the project as the last clip.

    The session must belong to the same user; we reject other users'
    sessions to avoid leaking cross-tenant data.
    """
    async with get_async_session() as db:
        project = await _load_project_for_user(db, project_id, current_user.id)

        session = (
            await db.execute(
                select(EditSession).where(
                    EditSession.id == body.edit_session_id,
                    EditSession.user_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="edit session not found",
            )

        # New position = current max + 1 (or 0 for first clip).
        existing = (
            await db.execute(
                select(StudioProjectClip).where(
                    StudioProjectClip.project_id == project.id
                )
            )
        ).scalars().all()
        next_position = (
            max((c.position for c in existing), default=-1) + 1
        )

        clip = StudioProjectClip(
            project_id=project.id,
            edit_session_id=session.id,
            position=next_position,
            trim_in_seconds=body.trim_in_seconds,
            trim_out_seconds=body.trim_out_seconds,
            transition_in_type=(
                body.transition_in_type.value if body.transition_in_type else None
            ),
            transition_in_ms=body.transition_in_ms,
        )
        db.add(clip)
        # Bump project.updated_at so the project re-sorts to the top of
        # the list view after an edit.
        project.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(project)
        return await _project_to_spec(db, project)


@router.patch(
    "/studio/projects/{project_id}/clips/{clip_id}",
    response_model=ProjectSpec,
)
@limiter.limit(Tier.WRITE)
async def update_clip(
    request: Request,
    project_id: int,
    clip_id: int,
    body: ProjectClipUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """Patch a clip. ``position`` triggers a reorder; the API renumbers
    every other clip in the project so the (project_id, position)
    index always sees a contiguous 0-indexed sequence."""
    async with get_async_session() as db:
        project = await _load_project_for_user(db, project_id, current_user.id)
        clip = (
            await db.execute(
                select(StudioProjectClip).where(
                    StudioProjectClip.id == clip_id,
                    StudioProjectClip.project_id == project.id,
                )
            )
        ).scalar_one_or_none()
        if clip is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="clip not found"
            )

        # Apply non-position field updates first.
        if body.trim_in_seconds is not None:
            clip.trim_in_seconds = body.trim_in_seconds
        if body.trim_out_seconds is not None:
            clip.trim_out_seconds = body.trim_out_seconds
        if body.transition_in_type is not None:
            clip.transition_in_type = body.transition_in_type.value
        if body.transition_in_ms is not None:
            clip.transition_in_ms = body.transition_in_ms

        # Now handle position. We move the clip out of the way to a
        # sentinel slot, renumber the rest of the project to close the
        # gap, then snap it into the target slot.
        if body.position is not None and body.position != clip.position:
            target = body.position
            # Sentinel large position so the UNIQUE index doesn't complain
            # while we shuffle.
            clip.position = 1_000_000 + clip.id
            await db.flush()

            # Renumber everything else into a contiguous sequence.
            siblings = (
                await db.execute(
                    select(StudioProjectClip)
                    .where(
                        StudioProjectClip.project_id == project.id,
                        StudioProjectClip.id != clip.id,
                    )
                    .order_by(StudioProjectClip.position.asc())
                )
            ).scalars().all()
            # Clamp target into [0, len(siblings)] so callers can't
            # request a sparse position.
            target = max(0, min(target, len(siblings)))

            # Two-pass: move siblings to sentinel slots, then snap
            # them around the target. Same dance as ``_renumber_positions``
            # but with a hole at ``target`` for our clip.
            for i, s in enumerate(siblings):
                s.position = 2_000_000 + i
            await db.flush()
            for i, s in enumerate(siblings):
                s.position = i if i < target else i + 1
            clip.position = target
            await db.flush()

        project.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(project)
        return await _project_to_spec(db, project)


@router.delete(
    "/studio/projects/{project_id}/clips/{clip_id}",
    response_model=ProjectSpec,
)
@limiter.limit(Tier.WRITE)
async def delete_clip(
    request: Request,
    project_id: int,
    clip_id: int,
    current_user: User = Depends(get_current_user),
):
    """Ripple-delete a clip: remove it and renumber the clips after it
    so positions stay contiguous."""
    async with get_async_session() as db:
        project = await _load_project_for_user(db, project_id, current_user.id)
        clip = (
            await db.execute(
                select(StudioProjectClip).where(
                    StudioProjectClip.id == clip_id,
                    StudioProjectClip.project_id == project.id,
                )
            )
        ).scalar_one_or_none()
        if clip is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="clip not found"
            )

        await db.delete(clip)
        await db.flush()
        await _renumber_positions(db, project.id)
        project.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(project)
        return await _project_to_spec(db, project)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post(
    "/studio/projects/{project_id}/render",
    response_model=ProjectRenderResponse,
)
@limiter.limit(Tier.WRITE)
async def render_project_endpoint(
    request: Request,
    response: Response,
    project_id: int,
    current_user: User = Depends(get_current_user),
):
    """Enqueue a project render. Returns the current status; the
    frontend then polls the status endpoint for live progress.

    Refuses to enqueue when the project has zero clips (the worker
    would just fail immediately) or when a render is already
    queued/rendering (idempotent dedupe — second click is a no-op
    that returns the existing job id).

    Sets ``X-Render-Budget-Remaining-Minutes`` (Week 8 hybrid gating)
    so the frontend can warn proactively at 80% used and disable the
    button at 100% — without having to make a separate ``/usage/renders``
    call after every enqueue."""
    async with get_async_session() as db:
        project = await _load_project_for_user(db, project_id, current_user.id)

        # Need clip rows (not just count) to estimate render minutes.
        clip_rows = list(
            (await db.execute(
                select(StudioProjectClip)
                .where(StudioProjectClip.project_id == project.id)
                .order_by(StudioProjectClip.position.asc())
            )).scalars().all()
        )
        clip_count = len(clip_rows)
        if clip_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="project has no clips to render",
            )

        # Render-minute budget pre-check (Week 8). Same hard-cap
        # semantics as the single-clip /studio/render endpoint:
        # paid plans short-circuit inside ``would_exceed_budget`` so
        # this is free for them.
        #
        # Use ``ProjectSpec.total_duration_seconds`` so the projected
        # duration matches what the renderer actually outputs — that
        # already accounts for per-clip trims AND the transition
        # overlap shortening between clips (a 500ms crossfade between
        # two 10s clips yields a 19.5s output, not 20s). Without this
        # adjustment a user with ~30s left in their monthly budget
        # could be falsely rejected by a project whose actual output
        # fits, simply because we summed pre-transition durations.
        spec_for_budget = await _project_to_spec(db, project)
        projected_seconds = spec_for_budget.total_duration_seconds
        projected_minutes = estimate_render_minutes(projected_seconds)
        if would_exceed_budget(current_user.id, projected_minutes):
            snapshot = get_budget_snapshot(current_user.id)
            # Telemetry (Week 8): explicit ``render.budget_blocked``
            # event so we can measure conversion pressure — how often
            # free users hit the cap vs how often the modal converts.
            record_render_budget_blocked(
                user_id=current_user.id,
                render_kind="project",
                render_id=project_id,
                projected_seconds=round(projected_seconds, 2),
                minutes_remaining=round(snapshot.minutes_remaining, 2),
                plan=current_user.plan,
            )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "render_budget_exceeded",
                    "message": (
                        f"You've used {snapshot.minutes_used:.1f} of "
                        f"{snapshot.minutes_limit:.0f} free render minutes "
                        f"this month. Upgrade to Pro for unlimited renders."
                    ),
                    "minutes_used": snapshot.minutes_used,
                    "minutes_limit": snapshot.minutes_limit,
                    "minutes_remaining": snapshot.minutes_remaining,
                    "projected_minutes": projected_minutes,
                },
            )

        # Stamp the budget header once we've passed the pre-check.
        # Done as a single helper so both early returns (in-flight) and
        # the final return share the same value. Math.inf collapses to
        # "unlimited" so the client doesn't have to special-case it.
        snapshot = get_budget_snapshot(current_user.id)
        if snapshot.unlimited:
            response.headers["X-Render-Budget-Remaining-Minutes"] = "unlimited"
        else:
            response.headers["X-Render-Budget-Remaining-Minutes"] = (
                f"{snapshot.minutes_remaining:.1f}"
            )

        # Queue surge headers (P3 polish): mirror the session endpoint
        # so a project enqueue that lands during a busy spell can
        # surface the same "wait ~X seconds" toast the frontend
        # already understands.
        from src.queue import get_queue_depth as _depth_probe
        from src.queue.surge import classify_depth as _classify_surge

        surge_at_enqueue = _classify_surge(_depth_probe())
        if surge_at_enqueue.available and surge_at_enqueue.level != "normal":
            response.headers["X-Render-Queue-Surge"] = surge_at_enqueue.level
            response.headers["X-Render-Queue-Wait-Seconds"] = str(
                surge_at_enqueue.estimated_wait_seconds
            )

        # Soft cap (Week 8 hybrid Pro gating): the project still renders
        # but we signal the frontend to surface the upgrade modal. Two
        # current triggers, both free-plan-only:
        #
        #   * Project output longer than 2 minutes (we render it; Pro
        #     unlocks longer outputs without a nudge).
        #
        # The header is informational only — the actual render proceeds
        # below. The Renders/Studio pages listen for this and call
        # ``openUpgrade("render_softcap")``.
        plan_lower = (current_user.plan or "free").lower()
        if plan_lower == "free":
            soft_reasons: list[str] = []
            if projected_seconds > 120:
                soft_reasons.append("duration_over_2min")
            if soft_reasons:
                response.headers["X-Render-Softcap"] = ",".join(soft_reasons)
                logger.info(
                    "render.softcap_signaled",
                    user_id=current_user.id,
                    kind="project",
                    render_id=project_id,
                    reasons=soft_reasons,
                    projected_seconds=round(projected_seconds, 2),
                )

        if project.last_render_status in ("queued", "rendering"):
            # Already in flight — return the current state, no new job.
            return ProjectRenderResponse(
                job_id=project.last_render_job_id,
                project_id=project.id,
                status=project.last_render_status,
                last_render_url=project.last_render_url,
                progress=project.render_progress,
                progress_message=project.render_progress_message,
            )

        project.last_render_status = "queued"
        project.last_render_error = None
        project.render_progress = 0
        project.render_progress_message = "Queued"
        await db.commit()
        await db.refresh(project)

    job_id = enqueue_job(
        "src.features.studio.render_project:render_project",
        project_id,
        job_timeout=3600,  # 1h ceiling — project renders can be long
        # Deterministic id (Week 8): a second click on Render while
        # the first is still in-flight returns the existing job id
        # instead of double-spending the queue. The DB-level guard
        # above also catches this, but the queue-level guard means
        # an HTTP retry layer can't race the DB write.
        job_id=f"render-project-{project_id}",
    )

    # Telemetry: the job is officially queued. Fires AFTER the DB
    # row flip + AFTER the enqueue so the event reflects reality.
    record_render_queued(
        user_id=current_user.id,
        render_kind="project",
        render_id=project_id,
        projected_seconds=round(projected_seconds, 2),
        job_id=job_id,
        plan=current_user.plan,
    )

    async with get_async_session() as db:
        fresh = await db.get(StudioProject, project_id)
        if fresh is None:
            raise HTTPException(
                status_code=500, detail="project vanished after render"
            )
        if job_id:
            fresh.last_render_job_id = job_id
            await db.commit()
            await db.refresh(fresh)
        logger.info(
            "studio.project.render_enqueued",
            project_id=fresh.id,
            user_id=current_user.id,
            clip_count=clip_count,
            job_id=job_id,
        )
        return ProjectRenderResponse(
            job_id=job_id,
            project_id=fresh.id,
            status=fresh.last_render_status,
            last_render_url=fresh.last_render_url,
            progress=fresh.render_progress,
            progress_message=fresh.render_progress_message,
        )


@router.get(
    "/studio/projects/{project_id}/render/status",
    response_model=ProjectRenderResponse,
)
@limiter.limit(Tier.READ)
async def render_project_status(
    request: Request,
    project_id: int,
    current_user: User = Depends(get_current_user),
):
    """Poll endpoint for live project-render progress. Same shape as
    the single-session ``/studio/render/:id/status`` so the frontend
    polling component is shared."""
    async with get_async_session() as db:
        project = await _load_project_for_user(db, project_id, current_user.id)
        return ProjectRenderResponse(
            job_id=project.last_render_job_id,
            project_id=project.id,
            status=project.last_render_status,
            last_render_url=project.last_render_url,
            progress=project.render_progress,
            progress_message=project.render_progress_message,
        )


@router.post(
    "/studio/projects/{project_id}/render/cancel",
    response_model=ProjectRenderResponse,
)
@limiter.limit(Tier.WRITE)
async def render_project_cancel(
    request: Request,
    project_id: int,
    current_user: User = Depends(get_current_user),
):
    """Cancel an in-flight project render.

    Marks the project as ``failed`` with a ``"cancelled by user"``
    error blurb and sends the RQ cancel command (queued jobs are
    dropped; started jobs stop after the current ffmpeg call returns).

    Returns 409 if the project isn't in ``queued`` / ``rendering``
    state — there's nothing to cancel."""
    from src.queue import add_render_breadcrumb, cancel_job
    from src.queue.telemetry import record_render_cancelled
    from src.features.studio.render_project import (
        _publish_project_event as _publish,
    )

    async with get_async_session() as db:
        project = await _load_project_for_user(db, project_id, current_user.id)
        if project.last_render_status not in ("queued", "rendering"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"project render is {project.last_render_status}; "
                    "nothing to cancel"
                ),
            )
        job_id = project.last_render_job_id
        previous_status = project.last_render_status
        project.last_render_status = "failed"
        project.last_render_error = "cancelled by user"
        project.render_progress_message = "Cancelled"
        await db.commit()
        await db.refresh(project)
        # Mirror the state change to the live progress channel so the
        # frontend's progress bar terminates instantly instead of
        # waiting for the worker to notice the cancel.
        _publish(project.id, status="failed", message="Cancelled", error="cancelled by user")
        snapshot = ProjectRenderResponse(
            job_id=job_id,
            project_id=project.id,
            status=project.last_render_status,
            last_render_url=project.last_render_url,
            progress=project.render_progress,
            progress_message=project.render_progress_message,
        )

    if job_id:
        cancel_job(job_id)
        # P3 polish: drop a Sentry breadcrumb so if the same render
        # surfaces in an error report later (e.g. operator re-runs and
        # it explodes), the timeline shows the cancel that preceded
        # the rerun.
        add_render_breadcrumb(
            category="render.cancel",
            message="user cancelled project render",
            data={
                "user_id": current_user.id,
                "render_kind": "project",
                "render_id": project_id,
                "job_id": job_id,
                "previous_status": previous_status,
            },
        )
        # Structured telemetry: dashboards split cancel_rate from
        # failure_rate, so this event is the *only* signal that
        # separates "user changed their mind" from "ffmpeg blew up".
        record_render_cancelled(
            user_id=current_user.id,
            render_kind="project",
            render_id=project_id,
            job_id=job_id,
            cancelled_by="user",
            previous_status=previous_status,
        )
        logger.info(
            "studio.project.render_cancelled",
            user_id=current_user.id,
            project_id=project_id,
            job_id=job_id,
            previous_status=previous_status,
        )
    return snapshot


# ---------------------------------------------------------------------------
# Unified Renders queue (Week 8)
# ---------------------------------------------------------------------------


class RenderQueueItem(BaseModel):
    """A single render — clip OR project — in the unified queue.

    Powers the Drafts → Renders tab which shows in-flight + recent
    renders across both kinds in one list. The frontend keys off
    ``kind + render_id`` for deduping and pairs the row with live
    WebSocket events from ``renderProgress.ts`` (which uses the
    same ``kind + render_id`` namespace).

    Intentionally flat — the consumer doesn't need to know about
    EditSession vs StudioProject SQL structure.
    """

    kind: str  # "session" | "project"
    render_id: int
    title: str
    status: str  # "idle" | "queued" | "rendering" | "done" | "failed"
    progress: Optional[int] = None
    progress_message: Optional[str] = None
    download_url: Optional[str] = None
    error: Optional[str] = None
    updated_at: datetime
    # Deep-link target so the row's "Open" button goes to the right
    # editor. Single clips deep-link into Studio via clip_key, projects
    # go to the multi-clip page.
    open_path: str
    # Session-only: surfaced so the Renders UI can call
    # ``POST /studio/render`` directly for a one-click retry (sending
    # only clip_key re-uses the stored spec). ``None`` for projects.
    clip_key: Optional[str] = None


@router.get("/studio/renders", response_model=List[RenderQueueItem])
@limiter.limit(Tier.READ)
async def list_user_renders(
    request: Request,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
):
    """Unified renders queue across single-clip sessions + multi-clip
    projects. Returns the user's most recent N renders sorted
    newest-first by ``updated_at``.

    The frontend Renders tab uses this as the initial snapshot and
    then layers live WebSocket events on top — so the list reflects
    historical state without needing a poll. ``limit`` is clamped to
    200 to keep the response small and the query cheap.
    """
    limit = max(1, min(200, limit))
    items: list[RenderQueueItem] = []

    async with get_async_session() as db:
        # Single-clip renders that aren't ``idle`` (those clutter the
        # queue with sessions that were never rendered).
        session_rows = (
            await db.execute(
                select(EditSession)
                .where(
                    EditSession.user_id == current_user.id,
                    EditSession.last_render_status != "idle",
                )
                .order_by(EditSession.updated_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        for s in session_rows:
            items.append(
                RenderQueueItem(
                    kind="session",
                    render_id=s.id,
                    title=s.title or s.clip_key[:24],
                    status=s.last_render_status,
                    progress=s.render_progress,
                    progress_message=s.render_progress_message,
                    download_url=s.last_render_url,
                    error=s.last_render_error,
                    updated_at=s.updated_at or s.created_at,
                    open_path=f"/dashboard/studio?clipKey={s.clip_key}",
                    clip_key=s.clip_key,
                )
            )

        project_rows = (
            await db.execute(
                select(StudioProject)
                .where(
                    StudioProject.user_id == current_user.id,
                    StudioProject.last_render_status != "idle",
                )
                .order_by(StudioProject.updated_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        for p in project_rows:
            items.append(
                RenderQueueItem(
                    kind="project",
                    render_id=p.id,
                    title=p.title,
                    status=p.last_render_status,
                    progress=p.render_progress,
                    progress_message=p.render_progress_message,
                    download_url=p.last_render_url,
                    error=p.last_render_error,
                    updated_at=p.updated_at or p.created_at,
                    open_path=f"/dashboard/studio/project/{p.id}",
                )
            )

    # Merge + sort newest-first; cap at ``limit``. Single-pass sort is
    # cheap given the per-source limit above.
    items.sort(key=lambda r: r.updated_at, reverse=True)
    return items[:limit]
