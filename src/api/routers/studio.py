"""Studio editor API: /studio/sessions/:clipKey GET/PUT, /studio/render POST.

The Studio editor is backed by a single canonical ``EditSpec`` JSON document
that drives both the in-browser Remotion preview and the server-side render
job. This router is intentionally thin — most logic lives in
``src.features.studio``.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import io
import os
import uuid
from pathlib import Path

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_async_session
from src.database.models import EditSession, User, UserBrandKit
from src.features.studio.peaks import compute_peaks
from src.features.studio.source_proxy import (
    get_normalized_source as _proxy_normalize,
    is_proxyable as _proxy_is_proxyable,
)
from src.features.llm_client import get_llm_client
from src.features.billing.render_budget import (
    BudgetSnapshot,
    estimate_render_minutes,
    get_budget_snapshot,
    would_exceed_budget,
)
from src.features.studio.spec import BrandKit, CameraCut, EditSpec, TransitionInstance
from src.features.studio.templates import (
    TEMPLATE_NAMES,
    apply_template as _apply_template,
)
from src.features.studio.transition_catalog import (
    list_for_frontend as _list_transitions_for_frontend,
)
from src.features.studio.tracking import is_cache_valid as _tracking_cache_valid
from src.queue import enqueue_job
from src.queue.telemetry import (
    record_render_budget_blocked,
    record_render_queued,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["studio"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SessionUpsertRequest(BaseModel):
    """Body for PUT /studio/sessions/:clipKey. The spec is the canonical state."""

    title: Optional[str] = None
    spec: EditSpec
    # CTA provenance (Week 10): when the user lands in Studio via a
    # cross-tool deep link with a recommendation context, the
    # frontend ships the envelope (``{"tool", "reason", "from"}``)
    # here on the upsert. The session row keeps it so when the
    # rendered video is later published, the metrics roll up against
    # the originating recommendation. Subsequent saves with no CTA
    # leave the existing provenance untouched — once attributed,
    # always attributed.
    cta_provenance: Optional[dict] = None


class SessionResponse(BaseModel):
    """Shape returned by GET / PUT / list endpoints."""

    id: int
    clip_key: str
    title: Optional[str]
    source_video_url: str
    source_clip_index: int
    source_clip_path: Optional[str]
    source_start_time: Optional[float]
    source_end_time: Optional[float]
    spec: Dict[str, Any]
    last_render_status: str
    last_render_url: Optional[str]
    last_render_error: Optional[str]
    last_rendered_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    # Week 10: CTA provenance for the session — set on first
    # deep-link entry, ``None`` for direct opens. The frontend
    # surfaces this as a chip ("From: Hook Lab recommendation") so
    # the user remembers why they started this edit.
    cta_provenance: Optional[Dict[str, Any]] = None


class RenderResponse(BaseModel):
    """Shape returned by POST /studio/render and GET /studio/render/{id}/status.

    ``session_id`` is included so the frontend can poll the status endpoint
    after firing render() without round-tripping back through the sessions list.
    ``progress`` is 0-100 and ``progress_message`` is the human-readable state
    written by the render job (e.g. "Encoding 42%", "Uploading to storage").
    """

    job_id: Optional[str]
    status: str
    last_render_url: Optional[str] = None
    session_id: Optional[int] = None
    progress: Optional[int] = None
    progress_message: Optional[str] = None


class SessionListItem(BaseModel):
    id: int
    clip_key: str
    title: Optional[str]
    source_video_url: str
    last_render_status: str
    last_render_url: Optional[str]
    updated_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_response(row: EditSession) -> SessionResponse:
    try:
        spec_dict = json.loads(row.spec or "{}")
    except Exception:
        spec_dict = {}
    # Normalize through EditSpec so new fields added in later weeks (e.g.
    # ``camera`` in Week 4) get their defaults backfilled for sessions saved
    # under an older schema. Without this the frontend would crash on
    # ``spec.camera.tracks`` for any pre-Week-4 row. Falls back to the raw
    # dict on validation failure so we don't 500 on a malformed legacy row.
    if spec_dict:
        try:
            spec_dict = EditSpec.model_validate(spec_dict).model_dump(mode="json")
        except Exception as exc:
            logger.warning(
                "studio.session.spec_normalize_failed",
                session_id=row.id,
                error=str(exc),
            )
    cta_dict: Optional[Dict[str, Any]] = None
    if row.cta_provenance:
        try:
            parsed = json.loads(row.cta_provenance)
            if isinstance(parsed, dict):
                cta_dict = parsed
        except Exception:  # noqa: BLE001
            # Corrupt JSON shouldn't 500 the session fetch; just drop
            # the attribution chip for this row.
            cta_dict = None

    return SessionResponse(
        id=row.id,
        clip_key=row.clip_key,
        title=row.title,
        source_video_url=row.source_video_url,
        source_clip_index=row.source_clip_index,
        source_clip_path=row.source_clip_path,
        source_start_time=row.source_start_time,
        source_end_time=row.source_end_time,
        spec=spec_dict,
        last_render_status=row.last_render_status,
        last_render_url=row.last_render_url,
        last_render_error=row.last_render_error,
        last_rendered_at=row.last_rendered_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        cta_provenance=cta_dict,
    )


def _stable_clip_key(source_url: str, clip_index: int, start: float, end: float) -> str:
    """Deterministic key so the same source clip always resolves to the
    same EditSession for a given user — lets users resume edits."""
    raw = f"{source_url}|{clip_index}|{start:.3f}|{end:.3f}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]


# ---------------------------------------------------------------------------
# Brand kit helpers (Week 6)
# ---------------------------------------------------------------------------


async def _user_brand_kit(db, user_id: int) -> Optional[UserBrandKit]:
    """Fetch the per-user brand kit row (or None)."""
    result = await db.execute(
        select(UserBrandKit).where(UserBrandKit.user_id == user_id)
    )
    return result.scalar_one_or_none()


def _brand_kit_to_spec(row: UserBrandKit) -> BrandKit:
    """Convert a UserBrandKit DB row → BrandKit Pydantic submodel."""
    return BrandKit(
        logo_url=row.logo_url,
        logo_position=row.logo_position or "br",  # type: ignore[arg-type]
        logo_opacity=row.logo_opacity,
        primary_color=row.primary_color,
        accent_color=row.accent_color,
        font_family=row.font_family,
    )


def _is_default_brand_kit(bk: BrandKit) -> bool:
    """True when the spec's brand kit hasn't been customized.

    Used to decide whether to overlay the user's saved brand kit when
    creating a fresh session — if the user is mid-edit and explicitly
    cleared their colors, we don't want to undo that on the next save.
    """
    return (
        not bk.logo_url
        and not bk.primary_color
        and not bk.accent_color
        and not bk.font_family
        and bk.logo_position == "br"
        and abs(bk.logo_opacity - 0.85) < 1e-6
    )


async def _maybe_seed_brand_kit(db, user_id: int, spec: EditSpec) -> EditSpec:
    """If the incoming spec has no brand customizations AND the user has a
    saved brand kit, fill it in so every new session is branded by default.
    """
    if spec.brand_kit and not _is_default_brand_kit(spec.brand_kit):
        return spec
    row = await _user_brand_kit(db, user_id)
    if row is None:
        return spec
    spec.brand_kit = _brand_kit_to_spec(row)
    return spec


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/studio/sessions", response_model=List[SessionListItem])
@limiter.limit(Tier.READ)
async def list_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """List the current user's most-recently-edited Studio sessions."""
    async with get_async_session() as db:
        stmt = (
            select(EditSession)
            .where(EditSession.user_id == current_user.id)
            .order_by(EditSession.updated_at.desc())
            .limit(50)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [
            SessionListItem(
                id=r.id,
                clip_key=r.clip_key,
                title=r.title,
                source_video_url=r.source_video_url,
                last_render_status=r.last_render_status,
                last_render_url=r.last_render_url,
                updated_at=r.updated_at,
            )
            for r in rows
        ]


@router.get("/studio/sessions/{clip_key}", response_model=SessionResponse)
@limiter.limit(Tier.READ)
async def get_session_by_key(
    request: Request,
    clip_key: str,
    current_user: User = Depends(get_current_user),
):
    """Fetch a single edit session by its stable clip key (sha256 prefix).

    Returns 404 if not found — the frontend treats that as "start a fresh
    session" and follows up with PUT to create the row.
    """
    async with get_async_session() as db:
        stmt = select(EditSession).where(
            EditSession.user_id == current_user.id,
            EditSession.clip_key == clip_key,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        return _row_to_response(row)


@router.put("/studio/sessions/{clip_key}", response_model=SessionResponse)
@limiter.limit(Tier.WRITE)
async def upsert_session(
    request: Request,
    clip_key: str,
    body: SessionUpsertRequest,
    current_user: User = Depends(get_current_user),
):
    """Create or update the user's edit session for this clip.

    The full ``EditSpec`` JSON is replaced on every call — clients keep a
    local optimistic copy and PUT periodically (debounced) so we never
    deal with partial patches.
    """
    clip = body.spec.clip

    async with get_async_session() as db:
        stmt = select(EditSession).where(
            EditSession.user_id == current_user.id,
            EditSession.clip_key == clip_key,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()

        # Week 6: first time we see this clip for this user, splat the
        # user's saved brand kit on top of the defaults. Skip when the
        # user has already customized brand_kit so we never undo an
        # explicit clear. ``_maybe_seed_brand_kit`` mutates body.spec.
        if row is None:
            body.spec = await _maybe_seed_brand_kit(db, current_user.id, body.spec)

        spec_json = body.spec.model_dump_json()

        # Persist CTA provenance ONLY when the client supplies one and
        # the row doesn't already have one. The "first attribution
        # wins" rule keeps the analytics rollup honest — if a user
        # opened Studio via a Hook Lab CTA, then later re-opened
        # the same session from Drafts (no CTA), the original
        # attribution stays. Same logic prevents background spec
        # autosaves from clobbering the provenance with ``null``.
        cta_payload = (
            json.dumps(body.cta_provenance, default=str)
            if body.cta_provenance
            else None
        )

        if row is None:
            row = EditSession(
                user_id=current_user.id,
                clip_key=clip_key,
                source_video_url=clip.source_url,
                source_clip_index=0,
                source_clip_path=clip.source_clip_path,
                source_start_time=clip.start_time,
                source_end_time=clip.end_time,
                title=body.title or clip.suggested_title,
                spec=spec_json,
                cta_provenance=cta_payload,
            )
            db.add(row)
        else:
            row.source_video_url = clip.source_url
            row.source_clip_path = clip.source_clip_path
            row.source_start_time = clip.start_time
            row.source_end_time = clip.end_time
            row.title = body.title or row.title or clip.suggested_title
            row.spec = spec_json
            # First-wins: only stamp if currently unattributed and the
            # client actually sent a CTA payload.
            if cta_payload is not None and not row.cta_provenance:
                row.cta_provenance = cta_payload

        await db.commit()
        await db.refresh(row)
        return _row_to_response(row)


@router.delete("/studio/sessions/{clip_key}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(Tier.WRITE)
async def delete_session(
    request: Request,
    clip_key: str,
    current_user: User = Depends(get_current_user),
):
    """Delete (hard) a user's Studio draft session.

    The Drafts page calls this when the user clicks the trash icon. We
    do a hard delete because the row is cheap to recreate (the spec is
    derived from the source clip on next open) and there's no audit
    requirement to retain edit history.
    """
    async with get_async_session() as db:
        stmt = select(EditSession).where(
            EditSession.user_id == current_user.id,
            EditSession.clip_key == clip_key,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            # Idempotent — if the row is already gone, treat as success.
            return None
        await db.delete(row)
        await db.commit()
    return None


class RenderRequest(BaseModel):
    """Body for POST /studio/render. ``clip_key`` identifies which session;
    optionally ``spec`` can be sent to PUT-and-render atomically (useful for
    the "Render" button right after an edit)."""

    clip_key: str = Field(..., min_length=8, max_length=64)
    spec: Optional[EditSpec] = None
    title: Optional[str] = None


@router.post("/studio/render", response_model=RenderResponse)
@limiter.limit(Tier.MEDIA_HEAVY)
async def render(
    request: Request,
    body: RenderRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
):
    """Enqueue (or sync-run) a render of the user's current Studio session.

    If ``spec`` is included we persist it first so the rendered output always
    matches what the user just clicked Render on.
    """
    async with get_async_session() as db:
        stmt = select(EditSession).where(
            EditSession.user_id == current_user.id,
            EditSession.clip_key == body.clip_key,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()

        if body.spec is not None:
            spec_json = body.spec.model_dump_json()
            clip = body.spec.clip
            if row is None:
                row = EditSession(
                    user_id=current_user.id,
                    clip_key=body.clip_key,
                    source_video_url=clip.source_url,
                    source_clip_index=0,
                    source_clip_path=clip.source_clip_path,
                    source_start_time=clip.start_time,
                    source_end_time=clip.end_time,
                    title=body.title or clip.suggested_title,
                    spec=spec_json,
                )
                db.add(row)
            else:
                row.source_video_url = clip.source_url
                row.source_clip_path = clip.source_clip_path
                row.source_start_time = clip.start_time
                row.source_end_time = clip.end_time
                row.title = body.title or row.title or clip.suggested_title
                row.spec = spec_json

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No session for clip_key; send `spec` to create one first.",
            )

        # Render-minute budget pre-check (Week 8). Free plan is capped
        # at 30 min/UTC-month; Pro/Enterprise are unlimited and short-
        # circuit inside ``would_exceed_budget`` so this is effectively
        # free for paid users. We estimate from the clip window —
        # render duration ≈ output duration — so it's a tight upper
        # bound. The 402 response carries the snapshot so the frontend
        # can show "X / Y min used; upgrade to render more".
        projected_seconds = max(
            0.0,
            (row.source_end_time or 0.0) - (row.source_start_time or 0.0),
        )
        projected_minutes = estimate_render_minutes(projected_seconds)
        if would_exceed_budget(current_user.id, projected_minutes):
            snapshot = get_budget_snapshot(current_user.id)
            record_render_budget_blocked(
                user_id=current_user.id,
                render_kind="session",
                render_id=row.id,
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

        row.last_render_status = "queued"
        row.last_render_error = None
        await db.commit()
        await db.refresh(row)
        session_id = row.id

    # Stamp the budget header so the frontend quota card can refresh
    # without re-fetching ``/studio/budget`` on a timer.
    snapshot_after = get_budget_snapshot(current_user.id)
    if snapshot_after.unlimited:
        response.headers["X-Render-Budget-Remaining-Minutes"] = "unlimited"
    else:
        response.headers["X-Render-Budget-Remaining-Minutes"] = (
            f"{snapshot_after.minutes_remaining:.1f}"
        )

    # Queue surge header (P3 polish): the frontend Renders/Studio
    # pages listen for this and surface a "queue is busier than
    # usual — your render will start in ~X seconds" toast at the
    # moment the user clicks Render. Cheaper than a polled banner
    # and immediate enough that users can decide to leave the page
    # if they don't want to wait. Best-effort: skipped when Redis
    # isn't available so dev/test runs don't grow phantom headers.
    from src.queue import get_queue_depth as _depth_probe
    from src.queue.surge import classify_depth as _classify_surge

    surge_at_enqueue = _classify_surge(_depth_probe())
    if surge_at_enqueue.available and surge_at_enqueue.level != "normal":
        response.headers["X-Render-Queue-Surge"] = surge_at_enqueue.level
        response.headers["X-Render-Queue-Wait-Seconds"] = str(
            surge_at_enqueue.estimated_wait_seconds
        )

    # Soft cap (Week 8 hybrid Pro gating): the render proceeds but a
    # header signals the frontend to surface the upgrade modal. Single
    # clips currently nudge on duration > 2 min (free plan only).
    plan_lower = (current_user.plan or "free").lower()
    if plan_lower == "free" and projected_seconds > 120:
        response.headers["X-Render-Softcap"] = "duration_over_2min"
        logger.info(
            "render.softcap_signaled",
            user_id=current_user.id,
            kind="session",
            render_id=session_id,
            reasons=["duration_over_2min"],
            projected_seconds=round(projected_seconds, 2),
        )

    job_id = enqueue_job(
        "src.features.studio.render:render_session",
        session_id,
        job_timeout=900,  # 15 min ceiling for a single render
        # Deterministic id (Week 8): dedupe a double-click at the
        # queue layer so a transient HTTP retry can't enqueue the
        # same render twice. Matches the project render endpoint.
        job_id=f"render-session-{session_id}",
    )

    # Structured telemetry: ``render.queued`` is the entrypoint of
    # the render funnel — every subsequent event (started/progress/
    # completed/failed) ties back to this one via render_id.
    record_render_queued(
        user_id=current_user.id,
        render_kind="session",
        render_id=session_id,
        projected_seconds=round(projected_seconds, 2),
        job_id=job_id,
        plan=current_user.plan,
    )

    # When ``enqueue_job`` ran the function synchronously (no Redis), the row
    # is already updated to ``done`` or ``failed`` — re-read to surface that.
    async with get_async_session() as db:
        fresh = await db.get(EditSession, session_id)
        if fresh is None:
            raise HTTPException(status_code=500, detail="session vanished after render")
        return RenderResponse(
            job_id=job_id,
            status=fresh.last_render_status,
            last_render_url=fresh.last_render_url,
            session_id=fresh.id,
            progress=fresh.render_progress,
            progress_message=fresh.render_progress_message,
        )


class SurgeStatus(BaseModel):
    """Queue surge snapshot returned alongside the budget (Week 8 P3).

    The frontend uses this to render a "queue is busier than usual"
    pill / banner so a user with a long queued render doesn't think
    we're frozen. All fields are best-effort: when Redis isn't
    configured, ``available`` is False and the UI hides the banner.
    """

    level: str  # "normal" | "busy" | "slammed"
    queue_depth: int
    started: int
    estimated_wait_seconds: int
    available: bool


class BudgetResponse(BaseModel):
    """Render-minute budget snapshot shown on the Renders page (Week 8)."""

    plan: str
    minutes_used: float
    minutes_limit: float  # serializes as ``Infinity``-string-safe sentinel
    minutes_remaining: float
    percent_used: float
    unlimited: bool
    month_start: datetime
    # P3 polish: piggyback on the existing budget poll so the frontend
    # gets a free surge signal without a second round-trip.
    surge: Optional[SurgeStatus] = None


def _snapshot_to_response(snap: BudgetSnapshot) -> BudgetResponse:
    """Convert the dataclass snapshot to the API response shape.

    Pydantic / JSON can't represent ``math.inf`` so we clamp the
    unlimited case to a very large finite number for ``minutes_limit``
    / ``minutes_remaining`` and rely on ``unlimited=True`` for the
    UI's display logic.

    Also probes the worker queue depth (best-effort, never raises)
    so the frontend can render a "queue is busier than usual" surge
    banner without an extra round-trip.
    """
    import math

    from src.queue import get_queue_depth
    from src.queue.surge import classify_depth

    finite_limit = (
        9_999_999.0 if math.isinf(snap.minutes_limit) else snap.minutes_limit
    )
    finite_remaining = (
        9_999_999.0
        if math.isinf(snap.minutes_remaining)
        else snap.minutes_remaining
    )
    surge_snapshot = classify_depth(get_queue_depth())
    return BudgetResponse(
        plan=snap.plan,
        minutes_used=round(snap.minutes_used, 3),
        minutes_limit=round(finite_limit, 3),
        minutes_remaining=round(finite_remaining, 3),
        percent_used=round(snap.percent_used, 1),
        unlimited=snap.unlimited,
        month_start=snap.month_start,
        surge=SurgeStatus(**surge_snapshot.to_dict()),
    )


@router.get("/studio/budget", response_model=BudgetResponse)
@limiter.limit(Tier.READ)
async def get_render_budget(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Current-month render-minute usage + remaining budget for the user.

    Drives the Renders-page Quota card (Week 8). Always returns a
    valid snapshot — never inserts a placeholder row, so calling
    this on a brand-new user is free of writes.
    """
    return _snapshot_to_response(get_budget_snapshot(current_user.id))


@router.post("/studio/render/{session_id}/cancel", response_model=RenderResponse)
@limiter.limit(Tier.WRITE)
async def render_cancel(
    request: Request,
    session_id: int,
    current_user: User = Depends(get_current_user),
):
    """Cancel an in-flight single-clip render.

    Mirrors the project cancel endpoint: marks the session as
    ``failed`` with ``"cancelled by user"`` so the UI terminates the
    progress bar instantly, then sends the RQ cancel command.

    Returns 409 when the render isn't ``queued`` / ``rendering`` —
    nothing to cancel."""
    from src.queue import add_render_breadcrumb, cancel_job
    from src.queue.telemetry import record_render_cancelled
    from src.features.studio.render import (
        _publish_session_event as _publish,
    )

    async with get_async_session() as db:
        row = await db.get(EditSession, session_id)
        if row is None or row.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
            )
        if row.last_render_status not in ("queued", "rendering"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"render is {row.last_render_status}; nothing to cancel"
                ),
            )
        job_id = row.last_render_job_id
        previous_status = row.last_render_status
        row.last_render_status = "failed"
        row.last_render_error = "cancelled by user"
        row.render_progress_message = "Cancelled"
        await db.commit()
        await db.refresh(row)
        _publish(row.id, status="failed", message="Cancelled", error="cancelled by user")
        snapshot = RenderResponse(
            job_id=job_id,
            status=row.last_render_status,
            last_render_url=row.last_render_url,
            session_id=row.id,
            progress=row.render_progress,
            progress_message=row.render_progress_message,
        )

    if job_id:
        cancel_job(job_id)
        # P3 polish: breadcrumb + structured telemetry so dashboards
        # can split user-initiated cancellations from real failures.
        # The breadcrumb shows up if a downstream operation (e.g. a
        # re-run that *then* crashes) raises a Sentry-captured
        # exception; the telemetry event flows into
        # ``summarize_renders`` for ``cancel_rate``.
        add_render_breadcrumb(
            category="render.cancel",
            message="user cancelled session render",
            data={
                "user_id": current_user.id,
                "render_kind": "session",
                "render_id": session_id,
                "job_id": job_id,
                "previous_status": previous_status,
            },
        )
        record_render_cancelled(
            user_id=current_user.id,
            render_kind="session",
            render_id=session_id,
            job_id=job_id,
            cancelled_by="user",
            previous_status=previous_status,
        )
        logger.info(
            "studio.render.cancelled",
            user_id=current_user.id,
            session_id=session_id,
            job_id=job_id,
            previous_status=previous_status,
        )
    return snapshot


@router.get("/studio/render/{session_id}/status", response_model=RenderResponse)
@limiter.limit(Tier.READ)
async def render_status(
    request: Request,
    session_id: int,
    current_user: User = Depends(get_current_user),
):
    """Poll endpoint for the frontend — returns current render state.

    The Studio frontend polls this every 1.5s while ``status`` is ``queued``
    or ``rendering`` so it can show a live progress bar driven by the render
    job's ``_set_progress`` writes.
    """
    async with get_async_session() as db:
        row = await db.get(EditSession, session_id)
        if row is None or row.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        return RenderResponse(
            job_id=row.last_render_job_id,
            status=row.last_render_status,
            last_render_url=row.last_render_url,
            session_id=row.id,
            progress=row.render_progress,
            progress_message=row.render_progress_message,
        )


# ---------------------------------------------------------------------------
# Waveform peaks (Week 3)
# ---------------------------------------------------------------------------


# Per-session lock: prevents two concurrent /peaks requests from running
# ffmpeg twice for the same clip. Held only while the (slow) extraction runs;
# the second request returns 503 with a Retry-After hint and the frontend
# re-polls. ``threading.Lock`` is fine — we never await while holding it.
_PEAKS_LOCKS: Dict[int, threading.Lock] = {}
_PEAKS_LOCKS_GUARD = threading.Lock()


def _peaks_lock(session_id: int) -> threading.Lock:
    with _PEAKS_LOCKS_GUARD:
        lock = _PEAKS_LOCKS.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _PEAKS_LOCKS[session_id] = lock
        return lock


class PeaksResponse(BaseModel):
    """Compact audio-waveform peaks for the timeline.

    ``peaks`` is a flat list of floats in [0,1]; length == ``bins``. Each
    value is the max absolute audio sample in that time bin. ``duration``
    is end - start seconds (so the frontend doesn't have to recompute it).
    """

    duration: float
    bins: int
    peaks: List[float]


def _peaks_cache_valid(row: EditSession, bins: int) -> bool:
    """The cached peaks are usable iff they cover the *current* clip window
    at the requested resolution."""
    if not row.peaks_json or row.peaks_bins != bins:
        return False
    if row.peaks_start_time != row.source_start_time:
        return False
    if row.peaks_end_time != row.source_end_time:
        return False
    return True


@router.get("/studio/sessions/{clip_key}/peaks", response_model=PeaksResponse)
@limiter.limit(Tier.READ)
async def get_peaks(
    request: Request,
    clip_key: str,
    bins: int = 2000,
    current_user: User = Depends(get_current_user),
):
    """Return audio-waveform peaks for the session's source clip.

    DB-cached; recomputes whenever the requested ``bins`` differs from the
    cached value or the underlying clip window has changed (trim).

    If a concurrent computation is in flight for the same session this
    returns 503 with ``Retry-After: 1`` so the frontend (or a sibling tab)
    polls instead of running ffmpeg twice.
    """
    bins = max(50, min(bins, 8000))

    async with get_async_session() as db:
        row = await db.execute(
            select(EditSession).where(
                EditSession.user_id == current_user.id,
                EditSession.clip_key == clip_key,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")

        if _peaks_cache_valid(row, bins):
            try:
                cached = json.loads(row.peaks_json or "[]")
            except json.JSONDecodeError:
                cached = []
            duration = max(0.0, (row.peaks_end_time or 0.0) - (row.peaks_start_time or 0.0))
            return PeaksResponse(duration=duration, bins=bins, peaks=cached)

        session_id = row.id
        source_url = row.source_video_url
        source_path = row.source_clip_path
        start = row.source_start_time or 0.0
        end = row.source_end_time or (start + 0.01)

    lock = _peaks_lock(session_id)
    if not lock.acquire(blocking=False):
        # Another request is computing — tell the client to come back.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "1"},
            content={"detail": "peaks computation in flight", "retry_after": 1},
        )

    try:
        peaks, duration = await asyncio.to_thread(
            compute_peaks, source_url, source_path, start, end, bins
        )
        async with get_async_session() as db:
            fresh = await db.get(EditSession, session_id)
            if fresh is not None:
                # Only persist if the clip window hasn't shifted under us
                # while ffmpeg was running.
                if fresh.source_start_time == start and fresh.source_end_time == end:
                    fresh.peaks_json = json.dumps(peaks)
                    fresh.peaks_bins = bins
                    fresh.peaks_start_time = start
                    fresh.peaks_end_time = end
                    await db.commit()
        return PeaksResponse(duration=duration, bins=bins, peaks=peaks)
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Multi-subject tracking (Week 4)
# ---------------------------------------------------------------------------


# Per-session lock for the (slow) tracking job — prevents two GETs from
# enqueueing redundant jobs while one is already in flight. The actual
# heavy work happens in the RQ worker; this lock just gates the enqueue +
# the synchronous-fallback execution.
_TRACKING_LOCKS: Dict[int, threading.Lock] = {}
_TRACKING_LOCKS_GUARD = threading.Lock()


def _tracking_lock(session_id: int) -> threading.Lock:
    with _TRACKING_LOCKS_GUARD:
        lock = _TRACKING_LOCKS.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _TRACKING_LOCKS[session_id] = lock
        return lock


class TrackingFrameSample(BaseModel):
    """One sparse per-detection bbox sample for a tracked subject."""

    t: float
    x: int
    y: int
    w: int
    h: int
    conf: float


class TrackingSubjectResponse(BaseModel):
    id: int
    label: str
    color_hex: str
    smoothed_crop_x: List[int]
    frames: List[TrackingFrameSample]


class TrackingResponse(BaseModel):
    """Returned on `done` from GET /studio/sessions/{key}/tracking."""

    status: str  # "done" — anything else returns 503
    fps: float
    frame_w: int
    frame_h: int
    start_time: float
    end_time: float
    subjects: List[TrackingSubjectResponse]


class TrackingStatusBody(BaseModel):
    """Returned with 503 while computation is queued/in-flight or after a
    failure. Mirrors `TrackingStatus` on the frontend."""

    status: str  # "idle" | "computing" | "failed"
    progress: Optional[int] = None
    progress_message: Optional[str] = None
    retry_after: Optional[int] = None


@router.get("/studio/sessions/{clip_key}/tracking")
@limiter.limit(Tier.READ)
async def get_tracking(
    request: Request,
    clip_key: str,
    n: int = 4,
    current_user: User = Depends(get_current_user),
):
    """Return cached multi-subject tracking for the session, auto-enqueueing
    the precompute job when it isn't ready.

    First-load behavior: if `tracking_status == "idle"` (or stale because of
    a trim / different N), we enqueue ``src.features.studio.tracking:compute_tracking``
    and return 503 with `Retry-After: 2`. The frontend's polling hook will
    re-request every couple seconds and get the payload once the worker
    finishes (~30s for a 15s clip).
    """
    n = max(1, min(8, int(n)))

    async with get_async_session() as db:
        row = await db.execute(
            select(EditSession).where(
                EditSession.user_id == current_user.id,
                EditSession.clip_key == clip_key,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")

        if _tracking_cache_valid(row, n):
            try:
                payload = json.loads(row.tracking_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            return TrackingResponse(
                status="done",
                fps=float(payload.get("fps", 30.0)),
                frame_w=int(payload.get("frame_w", 1920)),
                frame_h=int(payload.get("frame_h", 1080)),
                start_time=row.tracking_start_time or 0.0,
                end_time=row.tracking_end_time or 0.0,
                subjects=[
                    TrackingSubjectResponse(**s) for s in payload.get("subjects", [])
                ],
            )

        session_id = row.id
        current_status = row.tracking_status
        progress = row.tracking_progress
        message = row.tracking_progress_message

    # Already computing? Don't enqueue again — just tell the client to wait.
    # Note: we deliberately do NOT try to detect "stale computing" status
    # from this request handler. The per-session ``threading.Lock`` only
    # lives in THIS API process, so it can never know whether the RQ worker
    # process is genuinely running the job or has died. Recovery from crashed
    # workers happens via the startup sweep in src/api/main.py:lifespan,
    # which resets orphaned "computing" rows to "idle" on every API boot.
    if current_status == "computing":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "2"},
            content=TrackingStatusBody(
                status="computing",
                progress=progress,
                progress_message=message,
                retry_after=2,
            ).model_dump(),
        )

    # idle / failed / stale-(per-cache-key) → kick off a fresh job. The lock
    # is just to dedupe concurrent GETs in this API process from enqueueing
    # twice; ``compute_tracking`` itself is safe to re-run (idempotent).
    lock = _tracking_lock(session_id)
    if lock.acquire(blocking=False):
        try:
            async with get_async_session() as db:
                fresh = await db.get(EditSession, session_id)
                if fresh is not None and fresh.tracking_status != "computing":
                    fresh.tracking_status = "computing"
                    fresh.tracking_progress = 0
                    fresh.tracking_progress_message = "Queued"
                    await db.commit()
            # Prefer the RQ queue if Redis is configured; otherwise spawn a
            # background thread so the GET returns immediately instead of
            # blocking 30+ seconds while ML runs inline.
            from src.queue.client import get_queue

            if get_queue() is not None:
                enqueue_job(
                    "src.features.studio.tracking:compute_tracking",
                    session_id,
                    n,
                    job_timeout=600,
                )
            else:
                from src.features.studio.tracking import compute_tracking as _ct

                threading.Thread(
                    target=_ct,
                    args=(session_id, n),
                    name=f"tracking-{session_id}-{n}",
                    daemon=True,
                ).start()
        finally:
            lock.release()

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        headers={"Retry-After": "2"},
        content=TrackingStatusBody(
            status="computing", progress=0, progress_message="Queued", retry_after=2,
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Camera auto-switch heuristic
# ---------------------------------------------------------------------------


class AutoSwitchResponse(BaseModel):
    """Suggested camera cuts derived from transcript + tracking."""

    tracks: List[Dict[str, Any]]
    reasoning: str


@router.post("/studio/sessions/{clip_key}/camera/auto-switch", response_model=AutoSwitchResponse)
@limiter.limit(Tier.READ)
async def camera_auto_switch(
    request: Request,
    clip_key: str,
    current_user: User = Depends(get_current_user),
):
    """Suggest a ``CameraCut`` schedule from cached tracking + the transcript.

    Heuristic: walk the transcript word-by-word; for each word's time window
    pick the subject whose face bbox shows the most centroid Y motion
    (proxy for mouth/jaw motion → likely the speaker). Falls back to the
    subject closest to frame-center when motion is tied or detections are
    too sparse. Coalesces consecutive same-subject windows and enforces a
    minimum cut length so the output isn't strobe-flashy.

    Requires tracking to be cached — returns 409 with a hint to call
    /tracking first if not.
    """
    async with get_async_session() as db:
        row = await db.execute(
            select(EditSession).where(
                EditSession.user_id == current_user.id,
                EditSession.clip_key == clip_key,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        if not row.tracking_json:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="tracking not cached yet; fetch /tracking first",
            )
        try:
            tracking_payload = json.loads(row.tracking_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="corrupt tracking_json")
        try:
            spec_dict = json.loads(row.spec or "{}")
        except json.JSONDecodeError:
            spec_dict = {}
        clip = (spec_dict.get("clip") or {})
        transcript = clip.get("transcript") or []
        clip_dur = max(0.01, float(clip.get("end_time", 0)) - float(clip.get("start_time", 0)))

    cuts = _compute_auto_switch_cuts(
        transcript=transcript,
        tracking=tracking_payload,
        clip_duration=clip_dur,
    )
    reasoning = (
        f"Picked {len(cuts)} cuts from {len(transcript)} words and "
        f"{len(tracking_payload.get('subjects', []))} subjects "
        "(mouth-motion heuristic with 0.5s minimum dwell)."
    )
    return AutoSwitchResponse(
        tracks=[c.model_dump() for c in cuts], reasoning=reasoning
    )


def _compute_auto_switch_cuts(
    transcript: List[Dict[str, Any]],
    tracking: Dict[str, Any],
    clip_duration: float,
    min_cut_seconds: float = 0.5,
) -> List[CameraCut]:
    """Pure-function heuristic so it's easy to unit-test in isolation.

    Returns a non-overlapping, ordered list of ``CameraCut`` covering
    ``[0, clip_duration]``. When the heuristic can't pick a subject (no
    detections in the window) we fall back to subject 0 — empty list is only
    returned when there are no subjects at all.
    """
    subjects = tracking.get("subjects") or []
    if not subjects:
        return []
    subject_ids = [int(s["id"]) for s in subjects]

    # Precompute per-subject sorted (t, center_y) samples so we can compute
    # motion across small windows without re-sorting per word.
    motion_data: Dict[int, List[Dict[str, float]]] = {}
    for s in subjects:
        samples: List[Dict[str, float]] = []
        for f in s.get("frames", []):
            samples.append({"t": float(f["t"]), "cy": float(f["y"]) + float(f["h"]) / 2})
        samples.sort(key=lambda r: r["t"])
        motion_data[int(s["id"])] = samples

    # If no transcript at all, just return one cut for subject 0.
    if not transcript:
        return [CameraCut(start=0.0, end=clip_duration, subject_id=subject_ids[0])]

    picked: List[tuple[float, float, int]] = []  # (start, end, subject_id)
    for w in transcript:
        ws = float(w.get("start", 0.0))
        we = float(w.get("end", ws + 0.1))
        win_start = max(0.0, ws - 0.1)
        win_end = min(clip_duration, we + 0.2)
        if win_end <= win_start:
            continue
        best_subject = subject_ids[0]
        best_motion = -1.0
        for sid in subject_ids:
            cys = [
                rec["cy"]
                for rec in motion_data.get(sid, [])
                if win_start <= rec["t"] <= win_end
            ]
            if len(cys) < 2:
                continue
            motion = max(cys) - min(cys)
            if motion > best_motion:
                best_motion = motion
                best_subject = sid
        picked.append((win_start, win_end, best_subject))

    if not picked:
        return [CameraCut(start=0.0, end=clip_duration, subject_id=subject_ids[0])]

    # Coalesce consecutive same-subject windows.
    coalesced: List[List[Any]] = []
    for start, end, sid in picked:
        if coalesced and coalesced[-1][2] == sid:
            coalesced[-1][1] = end
        else:
            coalesced.append([start, end, sid])

    # Enforce min cut length: merge any cut shorter than min into its
    # neighbor (prefer the LATER neighbor since the next subject is usually
    # the one speaking now).
    i = 0
    while i < len(coalesced):
        start, end, sid = coalesced[i]
        if end - start < min_cut_seconds and len(coalesced) > 1:
            if i + 1 < len(coalesced):
                coalesced[i + 1][0] = start
                coalesced.pop(i)
                continue
            if i - 1 >= 0:
                coalesced[i - 1][1] = end
                coalesced.pop(i)
                continue
        i += 1

    # Stitch boundaries so the timeline is fully covered (no gaps); the
    # first cut starts at 0, the last ends at clip_duration.
    if coalesced:
        coalesced[0][0] = 0.0
        coalesced[-1][1] = clip_duration
        for k in range(len(coalesced) - 1):
            mid = (coalesced[k][1] + coalesced[k + 1][0]) / 2
            coalesced[k][1] = mid
            coalesced[k + 1][0] = mid

    return [
        CameraCut(start=round(s, 3), end=round(e, 3), subject_id=int(sid))
        for s, e, sid in coalesced
    ]


# ---------------------------------------------------------------------------
# Auto-zoom — LLM-detected punchline timestamps (Week 5)
# ---------------------------------------------------------------------------


_AUTO_ZOOM_SYSTEM = (
    "You are an editor selecting punch-in zoom moments for a short-form video. "
    "Given a word-level transcript with timestamps, return JSON of the most "
    "impactful moments — punchlines, surprises, emotional peaks, key reveals — "
    "where a subtle 1.0→1.3x zoom would emphasize the line. Pick at most one "
    "moment per 3 seconds. Return between 1 and 6 timestamps total. "
    "ONLY return a JSON object of the form: "
    '{"timestamps": [1.2, 4.7, 9.1]} (seconds, floats). No prose, no markdown.'
)


def _build_auto_zoom_user_prompt(transcript: List[Dict[str, Any]], duration: float) -> str:
    """Render the transcript as ``[t.tt] word`` lines so the model has both
    timing and text in one compact view."""
    lines = []
    for w in transcript[:600]:  # hard cap to keep prompt bounded
        try:
            ts = float(w.get("start", 0.0))
            text = str(w.get("text", "")).strip()
        except (TypeError, ValueError):
            continue
        if not text:
            continue
        lines.append(f"[{ts:5.2f}] {text}")
    return (
        f"Clip duration: {duration:.2f} seconds.\n"
        f"Transcript ({len(lines)} words):\n"
        + "\n".join(lines)
        + "\n\nReturn the JSON object now."
    )


def _coerce_timestamps(raw: Any, duration: float) -> List[float]:
    """Validate + clamp the LLM's timestamp list. Drops anything off-clip,
    rounds to 0.01s, and enforces the 3s-minimum spacing."""
    if isinstance(raw, dict):
        raw = raw.get("timestamps") or raw.get("zooms") or []
    if not isinstance(raw, list):
        return []
    out: List[float] = []
    for v in raw:
        try:
            t = round(float(v), 2)
        except (TypeError, ValueError):
            continue
        if t < 0 or t > duration:
            continue
        # enforce 3s gap from the most recent accepted timestamp
        if out and (t - out[-1]) < 3.0:
            continue
        out.append(t)
        if len(out) >= 8:
            break
    return out


class AutoZoomResponse(BaseModel):
    """Result of POST /studio/sessions/{key}/auto-zoom."""

    timestamps: List[float]
    count: int
    cached: bool = False


@router.post(
    "/studio/sessions/{clip_key}/auto-zoom",
    response_model=AutoZoomResponse,
)
# LLM_HEAVY (was READ). Auto-zoom hits the LLM with the full transcript;
# 100/min is far too generous and would let a misbehaving client torch
# the daily budget in seconds.
@limiter.limit(Tier.LLM_HEAVY)
async def detect_auto_zoom(
    request: Request,
    clip_key: str,
    current_user: User = Depends(get_current_user),
):
    """Detect punch-in zoom moments via the LLM and persist them to
    ``spec.auto_zoom.timestamps``.

    The result is folded back into the session row so the next debounced
    save from the frontend (or a reload) sees the updated spec. Auto-zoom
    is left disabled if the user hadn't already toggled it — the UI lets
    them enable it after seeing the suggestions.
    """
    async with get_async_session() as db:
        row = await db.execute(
            select(EditSession).where(
                EditSession.user_id == current_user.id,
                EditSession.clip_key == clip_key,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        try:
            spec_dict = json.loads(row.spec or "{}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="corrupt spec")
        try:
            spec = EditSpec.model_validate(spec_dict)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"spec validation failed: {exc}")
        clip = spec.clip
        duration = max(0.01, clip.end_time - clip.start_time)
        transcript = [w.model_dump() for w in clip.transcript]
        session_id = row.id

    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="transcript is empty; auto-zoom needs word timings",
        )

    user_prompt = _build_auto_zoom_user_prompt(transcript, duration)
    llm = get_llm_client()
    raw = await asyncio.to_thread(
        llm.generate_json,
        _AUTO_ZOOM_SYSTEM,
        user_prompt,
        300,  # max_tokens
        0.3,  # temperature — we want consistent picks
        current_user.id,
        "studio_auto_zoom",
        # Was hardcoded "free" — Pro users were getting clamped at
        # $0.50/day instead of their $10/day budget. Use the actual plan.
        current_user.plan or "free",
    )
    timestamps = _coerce_timestamps(raw, duration)

    if not timestamps:
        logger.warning(
            "studio.auto_zoom.no_timestamps",
            session_id=session_id,
            raw=str(raw)[:200],
        )
        # Fall back to an even-spaced sweep so the user still sees something
        # to react to. ~one zoom per 4s of clip.
        n = max(1, min(6, int(duration / 4)))
        timestamps = [round((i + 0.5) * duration / n, 2) for i in range(n)]

    # Persist by editing the spec JSON in place and writing back. We update
    # the timestamps and flip ``enabled`` on so the user immediately sees
    # the zooms in the preview without an extra click.
    async with get_async_session() as db:
        fresh = await db.get(EditSession, session_id)
        if fresh is None:
            raise HTTPException(status_code=500, detail="session vanished")
        try:
            current = json.loads(fresh.spec or "{}")
        except json.JSONDecodeError:
            current = {}
        az = current.setdefault("auto_zoom", {})
        az["timestamps"] = timestamps
        az["enabled"] = True
        if "max_scale" not in az:
            az["max_scale"] = 1.20
        # Re-validate so we never persist a broken spec.
        try:
            validated = EditSpec.model_validate(current)
            fresh.spec = validated.model_dump_json()
            await db.commit()
        except Exception as exc:
            logger.warning(
                "studio.auto_zoom.spec_validate_failed",
                session_id=session_id,
                error=str(exc),
            )

    return AutoZoomResponse(timestamps=timestamps, count=len(timestamps), cached=False)


# ---------------------------------------------------------------------------
# Emoji suggester (Week 6) — POST /studio/sessions/{key}/emojis/suggest
# ---------------------------------------------------------------------------


class EmojiSuggestResponse(BaseModel):
    """Result of POST /studio/sessions/{key}/emojis/suggest."""

    n_suggestions: int
    spec: Dict[str, Any]


@router.post(
    "/studio/sessions/{clip_key}/emojis/suggest",
    response_model=EmojiSuggestResponse,
)
# LLM_HEAVY (was READ). Calls the LLM with transcript text.
@limiter.limit(Tier.LLM_HEAVY)
async def suggest_emojis(
    request: Request,
    clip_key: str,
    current_user: User = Depends(get_current_user),
):
    """Run the LLM emoji suggester on the session's transcript and
    persist the result in-place on ``spec.clip.transcript[i].emoji``.

    The frontend toggles ``spec.captions.emoji_enabled`` independently —
    this endpoint just populates the data so flipping the switch on/off
    is reversible without re-burning LLM credits.
    """
    from src.features.studio.emoji_suggester import (
        suggest_emojis_for_transcript,
    )

    async with get_async_session() as db:
        row = await db.execute(
            select(EditSession).where(
                EditSession.user_id == current_user.id,
                EditSession.clip_key == clip_key,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="session not found",
            )
        try:
            spec = EditSpec.model_validate(json.loads(row.spec or "{}"))
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"spec validation failed: {exc}"
            )
        session_id = row.id
        plan = (current_user.plan or "free").lower()

    transcript = spec.clip.transcript
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="transcript is empty; nothing to suggest emojis for",
        )

    # Run LLM off the event loop so other API requests stay responsive.
    updated, n_suggestions = await asyncio.to_thread(
        suggest_emojis_for_transcript,
        transcript,
        user_id=current_user.id,
        plan=plan,
    )

    spec.clip.transcript = updated
    spec_json = spec.model_dump_json()
    spec_dict = json.loads(spec_json)

    async with get_async_session() as db:
        fresh = await db.get(EditSession, session_id)
        if fresh is None:
            raise HTTPException(status_code=500, detail="session vanished")
        fresh.spec = spec_json
        await db.commit()

    logger.info(
        "studio.emoji_suggester.complete",
        session_id=session_id,
        n_suggestions=n_suggestions,
    )
    return EmojiSuggestResponse(n_suggestions=n_suggestions, spec=spec_dict)


# ---------------------------------------------------------------------------
# Templates (Week 5)
# ---------------------------------------------------------------------------


class TemplateListItem(BaseModel):
    name: str
    description: str
    caption_style: str
    transition_type: str
    auto_zoom_enabled: bool


class ApplyTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


@router.get("/studio/templates", response_model=List[TemplateListItem])
@limiter.limit(Tier.READ)
async def list_templates(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Lightweight catalog of available presets (name + summary). The
    frontend uses this to render the Templates panel cards. Read-only —
    presets are code-defined, not user-editable."""
    from src.features.studio.templates import describe_templates

    return [TemplateListItem(**d) for d in describe_templates()]


@router.post(
    "/studio/sessions/{clip_key}/apply-template",
    response_model=SessionResponse,
)
@limiter.limit(Tier.WRITE)
async def apply_template_to_session(
    request: Request,
    clip_key: str,
    body: ApplyTemplateRequest,
    current_user: User = Depends(get_current_user),
):
    """Merge the named preset over the session's current spec and persist.

    Returns the freshly normalized ``SessionResponse`` so the frontend can
    drop it straight into its local state — no extra round-trip needed.
    """
    if body.name not in TEMPLATE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown template '{body.name}'; known: {TEMPLATE_NAMES}",
        )
    async with get_async_session() as db:
        row = await db.execute(
            select(EditSession).where(
                EditSession.user_id == current_user.id,
                EditSession.clip_key == clip_key,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        try:
            current = json.loads(row.spec or "{}")
            spec = EditSpec.model_validate(current)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"spec invalid: {exc}")

        try:
            merged = _apply_template(spec, body.name)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        row.spec = merged.model_dump_json()
        await db.commit()
        await db.refresh(row)
        return _row_to_response(row)


# ---------------------------------------------------------------------------
# Transitions catalog (Week 6) — 15 effects, grouped + previewable
# ---------------------------------------------------------------------------


class TransitionListItem(BaseModel):
    name: str
    category: str
    label: str
    description: str
    default_duration_ms: int
    has_sfx: bool
    thumbnail: str


@router.get("/studio/transitions", response_model=List[TransitionListItem])
@limiter.limit(Tier.READ)
async def list_transitions(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Return the 15-entry transition catalog used by the Effects panel.

    Pulled live from ``TRANSITION_CATALOG`` so adding a new entry on the
    backend automatically surfaces in the panel grid — no separate config
    file to keep in sync.
    """
    return [TransitionListItem(**d) for d in _list_transitions_for_frontend()]


# ---------------------------------------------------------------------------
# Per-boundary transition overrides (Week 6 Phase 4)
# ---------------------------------------------------------------------------


@router.post(
    "/studio/sessions/{clip_key}/boundary-transitions",
    response_model=SessionResponse,
)
@limiter.limit(Tier.WRITE)
async def upsert_boundary_transition(
    request: Request,
    clip_key: str,
    body: TransitionInstance,
    current_user: User = Depends(get_current_user),
):
    """Upsert a per-boundary transition by ``boundary_id``.

    If an entry with the same ``boundary_id`` already exists it's replaced
    in place; otherwise the new instance is appended to
    ``spec.boundary_transitions``. The global ``transitions.enabled`` flag
    is auto-flipped to ``True`` so the user sees the effect take hold
    without a second click.
    """
    async with get_async_session() as db:
        row = await db.execute(
            select(EditSession).where(
                EditSession.user_id == current_user.id,
                EditSession.clip_key == clip_key,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        try:
            spec = EditSpec.model_validate(json.loads(row.spec or "{}"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"spec invalid: {exc}")

        # Replace in place or append.
        existing_idx = next(
            (i for i, t in enumerate(spec.boundary_transitions) if t.boundary_id == body.boundary_id),
            None,
        )
        if existing_idx is None:
            spec.boundary_transitions.append(body)
        else:
            spec.boundary_transitions[existing_idx] = body
        spec.transitions.enabled = True

        row.spec = spec.model_dump_json()
        await db.commit()
        await db.refresh(row)
        return _row_to_response(row)


@router.delete(
    "/studio/sessions/{clip_key}/boundary-transitions/{boundary_id}",
    response_model=SessionResponse,
)
@limiter.limit(Tier.WRITE)
async def delete_boundary_transition(
    request: Request,
    clip_key: str,
    boundary_id: str,
    current_user: User = Depends(get_current_user),
):
    """Drop the per-boundary override for ``boundary_id``. The boundary
    then falls back to the global ``spec.transitions`` setting."""
    async with get_async_session() as db:
        row = await db.execute(
            select(EditSession).where(
                EditSession.user_id == current_user.id,
                EditSession.clip_key == clip_key,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        try:
            spec = EditSpec.model_validate(json.loads(row.spec or "{}"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"spec invalid: {exc}")
        spec.boundary_transitions = [
            t for t in spec.boundary_transitions if t.boundary_id != boundary_id
        ]
        row.spec = spec.model_dump_json()
        await db.commit()
        await db.refresh(row)
        return _row_to_response(row)


@router.post(
    "/studio/sessions/{clip_key}/boundary-transitions/apply-all",
    response_model=SessionResponse,
)
@limiter.limit(Tier.WRITE)
async def apply_transition_to_all_boundaries(
    request: Request,
    clip_key: str,
    current_user: User = Depends(get_current_user),
):
    """Bulk-apply the current global transition to every boundary.

    Useful when a user dials in a great transition+duration combo and
    wants it everywhere. Equivalent to expanding ``spec.transitions``
    into a full ``boundary_transitions`` list, like ``normalize()`` does
    on read — except triggered explicitly so the user sees the change in
    their save state immediately.
    """
    async with get_async_session() as db:
        row = await db.execute(
            select(EditSession).where(
                EditSession.user_id == current_user.id,
                EditSession.clip_key == clip_key,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        try:
            spec = EditSpec.model_validate(json.loads(row.spec or "{}"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"spec invalid: {exc}")

        spec.transitions.enabled = True
        spec.boundary_transitions = []  # force normalize() to repopulate
        normalized = spec.normalize()

        row.spec = normalized.model_dump_json()
        await db.commit()
        await db.refresh(row)
        return _row_to_response(row)


# ---------------------------------------------------------------------------
# Backgrounds (Week 6 Phase 2)
# ---------------------------------------------------------------------------


class BackgroundCatalogItem(BaseModel):
    id: str
    category: str
    label: str
    preview_thumbnail: str
    download_url: str
    duration_seconds: float
    attribution: Optional[str] = None


class BackgroundSearchItem(BaseModel):
    id: str
    source: str = "pexels"
    label: str
    preview_thumbnail: str
    download_url: str
    duration_seconds: float
    width: int
    height: int


class BackgroundSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=120)
    per_page: int = Field(default=12, ge=1, le=40)


@router.get("/studio/backgrounds", response_model=List[BackgroundCatalogItem])
@limiter.limit(Tier.READ)
async def list_backgrounds(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Hand-curated catalog of looping backgrounds (Minecraft parkour,
    satisfying soap-cutting, lo-fi rain, etc.)."""
    from src.features.studio.background_catalog import describe_featured_loops

    return [BackgroundCatalogItem(**d) for d in describe_featured_loops()]


@router.post(
    "/studio/backgrounds/search",
    response_model=Dict[str, List[BackgroundSearchItem]],
)
@limiter.limit(Tier.READ)
async def search_backgrounds(
    request: Request,
    body: BackgroundSearchRequest,
    current_user: User = Depends(get_current_user),
):
    """Pexels video search proxy, filtered to loop-able durations (>=10s)
    and returning standardized fields the BackgroundsPanel can render.

    Falls through to an empty list when ``PEXELS_API_KEY`` isn't set so
    the frontend can degrade gracefully to "featured only" mode.
    """
    from src.features.studio.background_catalog import search_pexels_videos

    try:
        rows = await search_pexels_videos(body.query, per_page=body.per_page)
    except RuntimeError as exc:  # missing API key, etc.
        logger.warning("studio.backgrounds.search_failed", error=str(exc))
        rows = []
    return {"results": [BackgroundSearchItem(**r) for r in rows]}


class BRollLibraryItem(BaseModel):
    """One bundled quick-pick B-roll clip exposed by ``GET /studio/broll/featured``.

    Shape matches the frontend's ``BackgroundCatalogEntry`` plus a
    ``description`` field so the panel can render an inline hint.
    """

    id: str
    label: str
    category: str
    description: str
    preview_thumbnail: str
    download_url: str
    duration_seconds: float
    source: str


@router.get("/studio/broll/featured", response_model=List[BRollLibraryItem])
@limiter.limit(Tier.READ)
async def list_featured_broll(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Default quick-pick B-roll library bundled with the repo.

    Renders 8 procedural clips so users can drop something onto the
    timeline in one click without configuring the Pexels API. Pexels
    search remains the primary path for real footage via /broll/search.
    """
    from src.features.studio.broll_library import describe_featured_broll

    return [BRollLibraryItem(**d) for d in describe_featured_broll()]


# ---------------------------------------------------------------------------
# Brand Kit (Week 6) — per-user logo + colors + font, auto-applied to renders
# ---------------------------------------------------------------------------
#
# Storage model:
#   - One ``UserBrandKit`` row per user (unique constraint on user_id).
#   - Logo lives in R2 under ``brand-assets/{user_id}/logo.{ext}`` — the row
#     keeps ``logo_r2_key`` so we can re-presign / delete on overwrite. In
#     dev (no R2 creds), we transparently fall back to a local static path
#     served by the existing ``/studio/assets/`` mount.
#   - ``upsert_session`` auto-seeds new sessions with the user's saved kit
#     (see ``_maybe_seed_brand_kit`` above) so every clip starts branded.


class BrandKitResponse(BaseModel):
    """GET /studio/user/brand-kit shape. Same fields as BrandKit + a flag
    for the UI to distinguish "no row yet" from "explicit defaults"."""

    logo_url: Optional[str] = None
    logo_position: str = "br"
    logo_opacity: float = 0.85
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None
    font_family: Optional[str] = None
    # Brand *voice* fields — completes the deep-integration story so
    # the brand kit auto-applies to Distribution publishes too, not
    # just visual elements in the Studio render.
    caption_signature: Optional[str] = None
    default_hashtags: Optional[str] = None
    exists: bool = False


class BrandKitUpdateRequest(BaseModel):
    """PUT /studio/user/brand-kit body. All fields optional; only the keys
    you send get patched, so the frontend can do small partial updates."""

    logo_url: Optional[str] = Field(default=None, max_length=1000)
    logo_position: Optional[str] = Field(default=None, pattern=r"^(tl|tr|bl|br)$")
    logo_opacity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    primary_color: Optional[str] = Field(
        default=None, pattern=r"^#[0-9A-Fa-f]{6}$"
    )
    accent_color: Optional[str] = Field(
        default=None, pattern=r"^#[0-9A-Fa-f]{6}$"
    )
    font_family: Optional[str] = Field(default=None, max_length=80)
    # Brand-voice fields. ``caption_signature`` is intentionally a free
    # text field (max 2000) so creators can include emoji, line breaks,
    # and a CTA link; ``default_hashtags`` is the comma-separated list
    # the Distribution publish merges into the user's caption.
    caption_signature: Optional[str] = Field(default=None, max_length=2000)
    default_hashtags: Optional[str] = Field(default=None, max_length=1000)


def _serialize_brand_kit(row: Optional[UserBrandKit]) -> BrandKitResponse:
    if row is None:
        return BrandKitResponse(exists=False)
    return BrandKitResponse(
        logo_url=row.logo_url,
        logo_position=row.logo_position or "br",
        logo_opacity=row.logo_opacity,
        primary_color=row.primary_color,
        accent_color=row.accent_color,
        font_family=row.font_family,
        caption_signature=row.caption_signature,
        default_hashtags=row.default_hashtags,
        exists=True,
    )


@router.get("/studio/user/brand-kit", response_model=BrandKitResponse)
@limiter.limit(Tier.READ)
async def get_user_brand_kit(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Return the caller's saved brand kit (or defaults when none exists)."""
    async with get_async_session() as db:
        return _serialize_brand_kit(await _user_brand_kit(db, current_user.id))


@router.put("/studio/user/brand-kit", response_model=BrandKitResponse)
@limiter.limit(Tier.WRITE)
async def upsert_user_brand_kit(
    request: Request,
    body: BrandKitUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """Upsert the caller's brand kit. Partial update — only sent keys patch."""
    async with get_async_session() as db:
        row = await _user_brand_kit(db, current_user.id)
        if row is None:
            row = UserBrandKit(user_id=current_user.id)
            db.add(row)
        # Apply only the keys the client sent so partial PUTs work.
        patch = body.model_dump(exclude_unset=True)
        for field, value in patch.items():
            setattr(row, field, value)
        await db.commit()
        await db.refresh(row)
        logger.info(
            "studio.brand_kit.upsert",
            user_id=current_user.id,
            fields=list(patch.keys()),
        )
        return _serialize_brand_kit(row)


# Logo upload — accepts PNG/JPEG/WebP up to ~2 MB. Stored in R2 when
# configured, otherwise written to a local static dir mounted at
# /studio/assets/uploads/ so dev works without cloud creds.
_LOGO_MAX_BYTES = 2 * 1024 * 1024
_LOGO_ALLOWED_MIMES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}


def _local_uploads_dir() -> str:
    """Where to write user-uploaded brand assets when R2 isn't configured.

    Lives under ``src/assets/uploads/{user_id}/`` so it's served by the
    existing ``/studio/assets`` static mount. Created lazily.
    """
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "assets", "uploads")
    )
    os.makedirs(base, exist_ok=True)
    return base


def _upload_logo_to_r2(
    *, user_id: int, content: bytes, ext: str, content_type: str
) -> Tuple[str, str]:
    """Upload the brand logo to R2 (or local fallback) and return (key, public_url).

    Falls back to a local file written under ``src/assets/uploads/{user_id}/``
    when R2 credentials aren't set — keeps dev usable on a fresh checkout.
    """
    from src.config import get_settings

    settings = get_settings()
    key = f"brand-assets/{user_id}/{uuid.uuid4().hex}.{ext}"

    has_r2 = bool(
        settings.r2_account_id
        and settings.r2_access_key_id
        and settings.r2_secret_access_key
    )
    if not has_r2:
        # Local dev fallback. Use the same filename pattern (uuid.ext) so
        # the URL is deterministic and we can delete on overwrite.
        local_dir = os.path.join(_local_uploads_dir(), str(user_id))
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, f"{uuid.uuid4().hex}.{ext}")
        with open(local_path, "wb") as f:
            f.write(content)
        rel = os.path.relpath(local_path, _local_uploads_dir())
        # Public URL routes through the Vite proxy (/api/studio/assets/...)
        # in dev so axios cookies / CSRF aren't required for the static fetch.
        public_url = f"/api/studio/assets/uploads/{rel}"
        return f"local:{local_path}", public_url

    try:
        from src.video_analysis.storage import R2Storage

        storage = R2Storage(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket_name=settings.r2_bucket_name or "viewmagnet-videos",
        )
        storage.client.upload_fileobj(
            io.BytesIO(content),
            storage.bucket_name,
            key,
            ExtraArgs={"ContentType": content_type, "CacheControl": "public, max-age=2592000"},
        )

        public_base = (settings.r2_public_url or "").rstrip("/")
        if public_base and not public_base.startswith("http://localhost"):
            public_url = f"{public_base}/{key}"
        else:
            public_url = storage.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": storage.bucket_name, "Key": key},
                ExpiresIn=60 * 60 * 24 * 30,  # 30 days
            )
        return key, public_url
    except Exception as exc:
        logger.exception(
            "studio.brand_kit.r2_upload_failed",
            user_id=user_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500, detail=f"logo upload failed: {exc}"
        )


def _delete_logo_object(key: Optional[str]) -> None:
    """Best-effort delete of a previously uploaded logo. Never raises —
    if the old object can't be removed we just log and move on (we don't
    want a stale cleanup failure to block a new upload)."""
    if not key:
        return
    try:
        if key.startswith("local:"):
            local_path = key[len("local:"):]
            if os.path.isfile(local_path):
                os.remove(local_path)
            return
        from src.config import get_settings
        from src.video_analysis.storage import R2Storage

        settings = get_settings()
        if not (
            settings.r2_account_id
            and settings.r2_access_key_id
            and settings.r2_secret_access_key
        ):
            return
        storage = R2Storage(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket_name=settings.r2_bucket_name or "viewmagnet-videos",
        )
        storage.client.delete_object(Bucket=storage.bucket_name, Key=key)
    except Exception as exc:
        logger.warning(
            "studio.brand_kit.logo_delete_failed", key=key, error=str(exc)
        )


@router.post("/studio/user/brand-kit/logo", response_model=BrandKitResponse)
@limiter.limit(Tier.WRITE)
async def upload_user_brand_logo(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload a brand logo image. Replaces any previously uploaded logo
    (the old R2 object is best-effort deleted)."""
    mime = (file.content_type or "").lower()
    if mime not in _LOGO_ALLOWED_MIMES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported mime type {mime!r}; allowed: PNG, JPEG, WebP, SVG",
        )

    content = await file.read()
    if len(content) > _LOGO_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"logo too large ({len(content)} bytes; limit {_LOGO_MAX_BYTES})",
        )
    if not content:
        raise HTTPException(status_code=400, detail="empty file")

    ext = _LOGO_ALLOWED_MIMES[mime]
    key, public_url = _upload_logo_to_r2(
        user_id=current_user.id, content=content, ext=ext, content_type=mime
    )

    async with get_async_session() as db:
        row = await _user_brand_kit(db, current_user.id)
        old_key = row.logo_r2_key if row else None
        if row is None:
            row = UserBrandKit(user_id=current_user.id)
            db.add(row)
        row.logo_r2_key = key
        row.logo_url = public_url
        await db.commit()
        await db.refresh(row)
        result = _serialize_brand_kit(row)

    # Delete previous logo OUTSIDE the DB session so a slow R2 call doesn't
    # hold a connection. Best-effort — failures are logged, not raised.
    if old_key and old_key != key:
        _delete_logo_object(old_key)

    logger.info(
        "studio.brand_kit.logo_uploaded",
        user_id=current_user.id,
        bytes=len(content),
        mime=mime,
    )
    return result


@router.delete("/studio/user/brand-kit/logo", response_model=BrandKitResponse)
@limiter.limit(Tier.WRITE)
async def delete_user_brand_logo(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Remove the uploaded logo. Other brand kit fields are preserved."""
    async with get_async_session() as db:
        row = await _user_brand_kit(db, current_user.id)
        if row is None:
            return _serialize_brand_kit(None)
        old_key = row.logo_r2_key
        row.logo_url = None
        row.logo_r2_key = None
        await db.commit()
        await db.refresh(row)
        result = _serialize_brand_kit(row)

    if old_key:
        _delete_logo_object(old_key)
    return result


@router.post("/studio/keys", response_model=Dict[str, str])
@limiter.limit(Tier.READ)
async def compute_clip_key(
    request: Request,
    body: Dict[str, Any],
    current_user: User = Depends(get_current_user),
):
    """Compute a stable clip_key from ``source_url``/``clip_index``/``start``/``end``.

    The frontend can compute this client-side too; we expose a server endpoint
    so we have one canonical implementation if the hash scheme ever changes.
    """
    try:
        key = _stable_clip_key(
            source_url=str(body["source_url"]),
            clip_index=int(body.get("clip_index", 0)),
            start=float(body["start_time"]),
            end=float(body["end_time"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc}")
    return {"clip_key": key}


# ---------------------------------------------------------------------------
# Source-video normalization proxy
# ---------------------------------------------------------------------------

# Auth bypass: this endpoint is hit directly by ``<video src>`` tags, which
# can't send our Authorization header (browsers strip non-CORS headers from
# media requests). To make this safe we only accept proxyable http(s) URLs
# and we cap response size at the source layer (MAX_INPUT_BYTES). No DB
# touches, no user state — it's purely a content-rewriter, and the upstream
# URL is already public (the user is asking us to fetch it on their behalf).
#
# The 307 redirect points the browser at the static file mount, which gives
# us proper HTTP Range support for free (Starlette's StaticFiles handles
# ``bytes=...`` requests natively, which is critical for `<video>` seeking).
@router.get("/studio/source-proxy")
async def studio_source_proxy(
    request: Request,
    url: str = Query(..., min_length=8, max_length=2000),
):
    """Normalize ``url`` to a Safari-friendly faststart MP4 and 307-redirect
    to the cached file. See ``src.features.studio.source_proxy`` for details.
    """
    if not _proxy_is_proxyable(url):
        raise HTTPException(
            status_code=400,
            detail="only absolute http(s) URLs can be proxied",
        )

    # Reject obvious abuse: only allow normal-looking URLs (no internal IPs).
    if any(host in url for host in ("localhost", "127.0.0.1", "0.0.0.0", "169.254.")):
        raise HTTPException(status_code=400, detail="refusing to proxy local URLs")

    try:
        # Synchronous download + transcode runs on the event loop, so we
        # offload to a thread to keep other requests responsive. The
        # per-URL lock inside ``get_normalized_source`` dedupes concurrent
        # calls for the same source.
        path = await asyncio.get_event_loop().run_in_executor(
            None, _proxy_normalize, url
        )
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except Exception as exc:
        logger.error("studio.source_proxy.failed", url=url[:200], error=str(exc))
        raise HTTPException(status_code=502, detail=f"source normalization failed: {exc}")

    # 307 preserves the method (GET) and lets the browser issue range
    # requests against the static mount in main.py. We use a *relative*
    # path so the redirect works whether or not the request was made
    # through a frontend proxy prefix (e.g. Vite's ``/api/*`` -> backend
    # rewriting). The browser resolves "source-cache/abc.mp4" against the
    # current URL ``/.../studio/source-proxy`` → ``/.../studio/source-cache/abc.mp4``.
    return RedirectResponse(
        url=f"source-cache/{path.name}",
        status_code=307,
    )


# ---------------------------------------------------------------------------
# Source-video upload (user-supplied footage)
# ---------------------------------------------------------------------------

class SourceUploadResponse(BaseModel):
    url: str = Field(..., description="Backend URL for the uploaded source file")
    filename: str


@router.post("/studio/source-upload", response_model=SourceUploadResponse)
@limiter.limit(Tier.WRITE)
async def studio_source_upload(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Accept a user-uploaded video file, run it through the same
    faststart normalization pipeline as source-proxy, and return the
    backend URL to use as ``clip.source_url`` in the Studio spec.

    This lets Studio work when the YouTube source is unavailable on the
    server (datacenter IP block). The user supplies their original footage
    and the frontend swaps it in as the source.
    """
    from src.features.studio.source_proxy import (
        CACHE_DIR,
        _ffmpeg_faststart,
        needs_normalization,
        _evict_oldest_if_needed,
    )
    import hashlib as _hl
    import shutil as _shutil

    # Validate content type.
    ct = (file.content_type or "").lower()
    if not (ct.startswith("video/") or ct in ("application/octet-stream", "")):
        raise HTTPException(
            status_code=400,
            detail="Only video files can be uploaded as source footage.",
        )

    # Read the file into a temp path, keyed by user + original filename so
    # two users uploading the same filename don't collide.
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Build a stable cache key from the file contents so the same upload
    # doesn't get processed twice in the same session.
    content_hash = _hl.sha256(raw_bytes).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{content_hash}.mp4"

    if not (cache_path.exists() and cache_path.stat().st_size > 0):
        import tempfile as _tf
        with _tf.TemporaryDirectory(prefix="source_upload_") as tmp:
            tmp_p = Path(tmp)
            raw_path = tmp_p / f"raw{Path(file.filename or 'upload').suffix or '.mp4'}"
            raw_path.write_bytes(raw_bytes)

            if needs_normalization(str(raw_path)):
                staged = tmp_p / "out.mp4"
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, _ffmpeg_faststart, raw_path, staged
                    )
                    import os as _os
                    _os.replace(staged, cache_path)
                except Exception as exc:
                    logger.error("studio.source_upload.ffmpeg_failed", error=str(exc))
                    # If ffmpeg fails just use the raw file — better than erroring out.
                    _shutil.copy2(raw_path, cache_path)
            else:
                _shutil.copy2(raw_path, cache_path)

        _evict_oldest_if_needed()

    logger.info(
        "studio.source_upload.done",
        user_id=current_user.id,
        filename=file.filename,
        cache_file=cache_path.name,
    )
    return SourceUploadResponse(
        url=f"studio/source-cache/{cache_path.name}",
        filename=cache_path.name,
    )
