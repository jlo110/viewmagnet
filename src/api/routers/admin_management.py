"""Admin management endpoints for user/data administration.

Full CRUD operations for admins to manage users, analyses, renders,
distribution jobs, and other platform data. All endpoints require
admin access via ``require_admin``.

Routes:
  - GET /admin/users — list all users with stats
  - GET /admin/users/{id} — get user details
  - PATCH /admin/users/{id} — update user (plan, status, etc.)
  - DELETE /admin/users/{id} — delete user and their data
  - GET /admin/analyses — list all analyses
  - DELETE /admin/analyses/{id} — delete analysis
  - GET /admin/renders — list all render jobs
  - GET /admin/distribution — list all distribution jobs
  - GET /admin/projects — list all studio projects
  - GET /admin/stats — platform-wide statistics
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from src.api.limiter import Tier, limiter
from src.auth.admin import require_admin
from src.database.connection import get_async_session
from src.database.models import (
    AuditEvent,
    DistributionJob,
    StudioProject,
    User,
    UserVideoAnalysis,
    YouTubeConnection,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin-management"])


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------


class AdminUserSummary(BaseModel):
    id: int
    email: str
    name: Optional[str]
    plan: str
    is_active: bool
    is_admin: bool
    created_at: Optional[str]
    last_login: Optional[str]
    analyses_this_month: int
    total_analyses: int
    total_renders: int
    stripe_customer_id: Optional[str]


class AdminUserDetail(AdminUserSummary):
    subscription_status: Optional[str]
    subscription_expires_at: Optional[str]
    referral_code: Optional[str]
    referral_bonus_analyses: int
    youtube_connections: int


class AdminUserUpdate(BaseModel):
    plan: Optional[str] = None
    is_active: Optional[bool] = None
    name: Optional[str] = None
    analyses_this_month: Optional[int] = None
    referral_bonus_analyses: Optional[int] = None


class SetAdminBody(BaseModel):
    is_admin: bool = Field(..., description="Grant or revoke admin access")


class AdminAnalysisSummary(BaseModel):
    id: int
    user_id: int
    user_email: Optional[str]
    video_id: str
    title: Optional[str]
    prediction_score: Optional[float]
    analyzed_at: Optional[str]


class AdminRenderSummary(BaseModel):
    id: int
    user_id: int
    user_email: Optional[str]
    render_type: str
    status: str
    duration_minutes: float
    created_at: Optional[str]


class AdminDistributionSummary(BaseModel):
    id: int
    user_id: int
    user_email: Optional[str]
    status: str
    target_count: int
    completed_count: int
    created_at: Optional[str]


class AdminProjectSummary(BaseModel):
    id: int
    user_id: int
    user_email: Optional[str]
    title: Optional[str]
    clip_count: int
    last_render_status: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class AdminStatsResponse(BaseModel):
    total_users: int
    active_users_7d: int
    new_users_7d: int
    total_analyses: int
    analyses_7d: int
    total_renders: int
    renders_7d: int
    total_distribution_jobs: int
    distribution_jobs_7d: int
    users_by_plan: dict
    revenue_estimate_monthly: float


class PaginatedResponse(BaseModel):
    items: List
    total: int
    page: int
    page_size: int
    pages: int


# ---------------------------------------------------------------------------
# Stats & Overview
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=AdminStatsResponse)
@limiter.limit(Tier.READ)
async def get_admin_stats(
    request: Request,
    current_user: User = Depends(require_admin),
):
    """Get platform-wide statistics for admin dashboard."""
    async with get_async_session() as db:
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)

        # User counts
        total_users = (await db.execute(
            select(func.count(User.id))
        )).scalar() or 0

        active_users_7d = (await db.execute(
            select(func.count(User.id)).where(User.last_login >= week_ago)
        )).scalar() or 0

        new_users_7d = (await db.execute(
            select(func.count(User.id)).where(User.created_at >= week_ago)
        )).scalar() or 0

        # Analysis counts
        total_analyses = (await db.execute(
            select(func.count(UserVideoAnalysis.id))
        )).scalar() or 0

        analyses_7d = (await db.execute(
            select(func.count(UserVideoAnalysis.id))
            .where(UserVideoAnalysis.analyzed_at >= week_ago)
        )).scalar() or 0

        # Render counts — use AuditEvent (UserRenderUsage is monthly budget, not per-render)
        total_renders = (await db.execute(
            select(func.count(AuditEvent.id))
            .where(AuditEvent.event_type == "render.queued")
        )).scalar() or 0

        renders_7d = (await db.execute(
            select(func.count(AuditEvent.id))
            .where(AuditEvent.event_type == "render.queued", AuditEvent.created_at >= week_ago)
        )).scalar() or 0

        # Distribution counts
        total_distribution = (await db.execute(
            select(func.count(DistributionJob.id))
        )).scalar() or 0

        distribution_7d = (await db.execute(
            select(func.count(DistributionJob.id))
            .where(DistributionJob.created_at >= week_ago)
        )).scalar() or 0

        # Users by plan
        plan_counts = (await db.execute(
            select(User.plan, func.count(User.id))
            .group_by(User.plan)
        )).all()
        users_by_plan = {p[0] or "free": p[1] for p in plan_counts}

        # Estimate monthly revenue (simplified)
        plan_prices = {"starter": 29, "pro": 79, "agency": 199}
        revenue = sum(
            users_by_plan.get(plan, 0) * price
            for plan, price in plan_prices.items()
        )

        return AdminStatsResponse(
            total_users=total_users,
            active_users_7d=active_users_7d,
            new_users_7d=new_users_7d,
            total_analyses=total_analyses,
            analyses_7d=analyses_7d,
            total_renders=total_renders,
            renders_7d=renders_7d,
            total_distribution_jobs=total_distribution,
            distribution_jobs_7d=distribution_7d,
            users_by_plan=users_by_plan,
            revenue_estimate_monthly=revenue,
        )


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------


@router.get("/users")
@limiter.limit(Tier.READ)
async def list_users(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = Query(default=None),
    plan: Optional[str] = Query(default=None),
    current_user: User = Depends(require_admin),
):
    """List all users with pagination and filtering."""
    async with get_async_session() as db:
        query = select(User)

        if search:
            search_filter = f"%{search}%"
            query = query.where(
                (User.email.ilike(search_filter)) |
                (User.name.ilike(search_filter))
            )

        if plan:
            query = query.where(User.plan == plan)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_query)).scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        query = query.order_by(User.created_at.desc()).offset(offset).limit(page_size)
        users = (await db.execute(query)).scalars().all()

        # Get stats for each user
        items = []
        for u in users:
            total_analyses = (await db.execute(
                select(func.count(UserVideoAnalysis.id))
                .where(UserVideoAnalysis.user_id == u.id)
            )).scalar() or 0

            # Renders = queued render events (UserRenderUsage is the monthly
            # budget row, not a per-render record — see /stats above).
            total_renders = (await db.execute(
                select(func.count(AuditEvent.id))
                .where(AuditEvent.event_type == "render.queued", AuditEvent.user_id == u.id)
            )).scalar() or 0

            items.append(AdminUserSummary(
                id=u.id,
                email=u.email,
                name=u.name,
                plan=u.plan or "free",
                is_active=u.is_active if hasattr(u, 'is_active') else True,
                is_admin=u.is_admin,
                created_at=u.created_at.isoformat() if u.created_at else None,
                last_login=u.last_login.isoformat() if u.last_login else None,
                analyses_this_month=u.analyses_this_month or 0,
                total_analyses=total_analyses,
                total_renders=total_renders,
                stripe_customer_id=u.stripe_customer_id,
            ))

        return {
            "items": [i.model_dump() for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }


@router.get("/users/{user_id}")
@limiter.limit(Tier.READ)
async def get_user_detail(
    request: Request,
    user_id: int,
    current_user: User = Depends(require_admin),
):
    """Get detailed information about a specific user."""
    async with get_async_session() as db:
        user = (await db.execute(
            select(User).where(User.id == user_id)
        )).scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        total_analyses = (await db.execute(
            select(func.count(UserVideoAnalysis.id))
            .where(UserVideoAnalysis.user_id == user.id)
        )).scalar() or 0

        total_renders = (await db.execute(
            select(func.count(AuditEvent.id))
            .where(AuditEvent.event_type == "render.queued", AuditEvent.user_id == user.id)
        )).scalar() or 0

        youtube_count = (await db.execute(
            select(func.count(YouTubeConnection.id))
            .where(YouTubeConnection.user_id == user.id, YouTubeConnection.is_active == True)
        )).scalar() or 0

        return AdminUserDetail(
            id=user.id,
            email=user.email,
            name=user.name,
            plan=user.plan or "free",
            is_active=user.is_active if hasattr(user, 'is_active') else True,
            created_at=user.created_at.isoformat() if user.created_at else None,
            last_login=user.last_login.isoformat() if user.last_login else None,
            analyses_this_month=user.analyses_this_month or 0,
            total_analyses=total_analyses,
            total_renders=total_renders,
            stripe_customer_id=user.stripe_customer_id,
            subscription_status=user.subscription_status,
            subscription_expires_at=user.subscription_expires.isoformat() if user.subscription_expires else None,
            referral_code=user.referral_code,
            referral_bonus_analyses=user.referral_bonus_analyses or 0,
            youtube_connections=youtube_count,
        )


@router.patch("/users/{user_id}")
@limiter.limit(Tier.WRITE)
async def update_user(
    request: Request,
    user_id: int,
    body: AdminUserUpdate,
    current_user: User = Depends(require_admin),
):
    """Update user details (plan, status, etc.)."""
    async with get_async_session() as db:
        user = (await db.execute(
            select(User).where(User.id == user_id)
        )).scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if body.plan is not None:
            user.plan = body.plan
        if body.is_active is not None and hasattr(user, 'is_active'):
            user.is_active = body.is_active
        if body.name is not None:
            user.name = body.name
        if body.analyses_this_month is not None:
            user.analyses_this_month = body.analyses_this_month
        if body.referral_bonus_analyses is not None:
            user.referral_bonus_analyses = body.referral_bonus_analyses

        await db.commit()
        await db.refresh(user)

        logger.info(
            "admin.user_updated",
            user_id=user_id,
            updated_by=current_user.id,
            changes=body.model_dump(exclude_none=True),
        )

        return {"status": "updated", "user_id": user_id}


@router.patch("/users/{user_id}/set-admin")
@limiter.limit(Tier.WRITE)
async def set_user_admin(
    request: Request,
    user_id: int,
    body: SetAdminBody,
    current_user: User = Depends(require_admin),
):
    """Grant or revoke admin access for a user."""
    if user_id == current_user.id and not body.is_admin:
        raise HTTPException(status_code=400, detail="Cannot remove your own admin access")

    async with get_async_session() as db:
        user = (await db.execute(
            select(User).where(User.id == user_id)
        )).scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.is_admin = body.is_admin
        await db.commit()

        logger.info(
            "admin.set_admin",
            target_user_id=user_id,
            target_email=user.email,
            is_admin=body.is_admin,
            changed_by=current_user.id,
        )

        return {"status": "updated", "user_id": user_id, "is_admin": body.is_admin}


@router.delete("/users/{user_id}")
@limiter.limit(Tier.WRITE)
async def delete_user(
    request: Request,
    user_id: int,
    current_user: User = Depends(require_admin),
):
    """Delete a user and all their associated data."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    async with get_async_session() as db:
        user = (await db.execute(
            select(User).where(User.id == user_id)
        )).scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        await db.delete(user)
        await db.commit()

        logger.info(
            "admin.user_deleted",
            user_id=user_id,
            user_email=user.email,
            deleted_by=current_user.id,
        )

        return {"status": "deleted", "user_id": user_id}


# ---------------------------------------------------------------------------
# Analysis Management
# ---------------------------------------------------------------------------


@router.get("/analyses")
@limiter.limit(Tier.READ)
async def list_analyses(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user_id: Optional[int] = Query(default=None),
    current_user: User = Depends(require_admin),
):
    """List all analyses with pagination."""
    async with get_async_session() as db:
        query = select(UserVideoAnalysis, User.email).join(
            User, User.id == UserVideoAnalysis.user_id, isouter=True
        )

        if user_id:
            query = query.where(UserVideoAnalysis.user_id == user_id)

        count_query = select(func.count(UserVideoAnalysis.id))
        if user_id:
            count_query = count_query.where(UserVideoAnalysis.user_id == user_id)
        total = (await db.execute(count_query)).scalar() or 0

        offset = (page - 1) * page_size
        query = query.order_by(UserVideoAnalysis.analyzed_at.desc()).offset(offset).limit(page_size)
        rows = (await db.execute(query)).all()

        items = [
            AdminAnalysisSummary(
                id=a.id,
                user_id=a.user_id,
                user_email=email,
                video_id=a.video_id,
                title=a.title,
                prediction_score=a.prediction_score,
                analyzed_at=a.analyzed_at.isoformat() if a.analyzed_at else None,
            ).model_dump()
            for a, email in rows
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }


@router.delete("/analyses/{analysis_id}")
@limiter.limit(Tier.WRITE)
async def delete_analysis(
    request: Request,
    analysis_id: int,
    current_user: User = Depends(require_admin),
):
    """Delete a specific analysis."""
    async with get_async_session() as db:
        analysis = (await db.execute(
            select(UserVideoAnalysis).where(UserVideoAnalysis.id == analysis_id)
        )).scalars().first()

        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")

        await db.delete(analysis)
        await db.commit()

        logger.info(
            "admin.analysis_deleted",
            analysis_id=analysis_id,
            deleted_by=current_user.id,
        )

        return {"status": "deleted", "analysis_id": analysis_id}


# ---------------------------------------------------------------------------
# Render Management
# ---------------------------------------------------------------------------


@router.get("/renders")
@limiter.limit(Tier.READ)
async def list_renders(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user_id: Optional[int] = Query(default=None),
    current_user: User = Depends(require_admin),
):
    """List render audit events (one row per render.queued event)."""
    import json as _json
    async with get_async_session() as db:
        query = select(AuditEvent, User.email).join(
            User, User.id == AuditEvent.user_id, isouter=True
        ).where(AuditEvent.event_type == "render.queued")

        if user_id:
            query = query.where(AuditEvent.user_id == user_id)

        count_query = select(func.count(AuditEvent.id)).where(AuditEvent.event_type == "render.queued")
        if user_id:
            count_query = count_query.where(AuditEvent.user_id == user_id)
        total = (await db.execute(count_query)).scalar() or 0

        offset = (page - 1) * page_size
        query = query.order_by(AuditEvent.created_at.desc()).offset(offset).limit(page_size)
        rows = (await db.execute(query)).all()

        items = []
        for r, email in rows:
            details = {}
            try:
                details = _json.loads(r.details or "{}")
            except Exception:
                pass
            items.append(AdminRenderSummary(
                id=r.id,
                user_id=r.user_id or 0,
                user_email=email,
                render_type=details.get("render_kind", "unknown"),
                status="queued",
                duration_minutes=0,
                created_at=r.created_at.isoformat() if r.created_at else None,
            ).model_dump())

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }


# ---------------------------------------------------------------------------
# Distribution Management
# ---------------------------------------------------------------------------


@router.get("/distribution")
@limiter.limit(Tier.READ)
async def list_distribution_jobs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user_id: Optional[int] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    current_user: User = Depends(require_admin),
):
    """List all distribution jobs."""
    async with get_async_session() as db:
        query = select(DistributionJob, User.email).join(
            User, User.id == DistributionJob.user_id, isouter=True
        )

        if user_id:
            query = query.where(DistributionJob.user_id == user_id)
        if status_filter:
            query = query.where(DistributionJob.status == status_filter)

        count_query = select(func.count(DistributionJob.id))
        if user_id:
            count_query = count_query.where(DistributionJob.user_id == user_id)
        if status_filter:
            count_query = count_query.where(DistributionJob.status == status_filter)
        total = (await db.execute(count_query)).scalar() or 0

        offset = (page - 1) * page_size
        query = query.order_by(DistributionJob.created_at.desc()).offset(offset).limit(page_size)
        rows = (await db.execute(query)).all()

        items = [
            AdminDistributionSummary(
                id=j.id,
                user_id=j.user_id,
                user_email=email,
                status=j.status or "unknown",
                target_count=j.target_count or 0,
                completed_count=j.success_count or 0,
                created_at=j.created_at.isoformat() if j.created_at else None,
            ).model_dump()
            for j, email in rows
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }


# ---------------------------------------------------------------------------
# Project Management
# ---------------------------------------------------------------------------


@router.get("/projects")
@limiter.limit(Tier.READ)
async def list_projects(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user_id: Optional[int] = Query(default=None),
    current_user: User = Depends(require_admin),
):
    """List all studio projects."""
    async with get_async_session() as db:
        query = select(StudioProject, User.email).join(
            User, User.id == StudioProject.user_id, isouter=True
        )

        if user_id:
            query = query.where(StudioProject.user_id == user_id)

        count_query = select(func.count(StudioProject.id))
        if user_id:
            count_query = count_query.where(StudioProject.user_id == user_id)
        total = (await db.execute(count_query)).scalar() or 0

        offset = (page - 1) * page_size
        query = query.order_by(StudioProject.updated_at.desc()).offset(offset).limit(page_size)
        rows = (await db.execute(query)).all()

        items = []
        for p, email in rows:
            from src.database.models import StudioProjectClip
            clip_count = (await db.execute(
                select(func.count(StudioProjectClip.id))
                .where(StudioProjectClip.project_id == p.id)
            )).scalar() or 0

            items.append(AdminProjectSummary(
                id=p.id,
                user_id=p.user_id,
                user_email=email,
                title=p.title,
                clip_count=clip_count,
                last_render_status=p.last_render_status,
                created_at=p.created_at.isoformat() if p.created_at else None,
                updated_at=p.updated_at.isoformat() if p.updated_at else None,
            ).model_dump())

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }


@router.delete("/projects/{project_id}")
@limiter.limit(Tier.WRITE)
async def delete_project(
    request: Request,
    project_id: int,
    current_user: User = Depends(require_admin),
):
    """Delete a studio project."""
    async with get_async_session() as db:
        project = (await db.execute(
            select(StudioProject).where(StudioProject.id == project_id)
        )).scalars().first()

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        await db.delete(project)
        await db.commit()

        logger.info(
            "admin.project_deleted",
            project_id=project_id,
            deleted_by=current_user.id,
        )

        return {"status": "deleted", "project_id": project_id}
