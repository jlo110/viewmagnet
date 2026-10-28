"""Distribution Hub: multi-account cross-platform publishing endpoints."""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime as _dt
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_async_session, get_session
from src.database.models import (
    ConnectedAccount,
    DistributionJob,
    DistributionResult,
    User,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["distribution"])


# ---------------------------------------------------------------------------
# Outcomes response models (Week 10) — kept inline so the router's
# response_model declarations stay self-contained.
# ---------------------------------------------------------------------------


class SnapshotPointResponse(BaseModel):
    """One window's snapshot for a published post.

    All metric fields are nullable because no platform exposes all
    of them and the UI prefers showing "—" to a fake zero.
    """

    window_key: str
    sampled_at: str
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    watch_time_seconds: Optional[float] = None
    avg_view_percentage: Optional[float] = None
    click_through_rate: Optional[float] = None


class PublishedOutcomeResponse(BaseModel):
    """One published post + its captured snapshots + attribution."""

    distribution_job_id: int
    distribution_result_id: int
    platform: str
    posted_url: Optional[str]
    published_at: str
    title: str
    source_video_url: Optional[str]
    snapshots: dict[str, SnapshotPointResponse] = Field(default_factory=dict)
    latest: Optional[SnapshotPointResponse] = None
    cta_provenance: Optional[dict] = None


class RecommendationGroupResponse(BaseModel):
    tool: str
    label: str
    sample_count: int
    avg_views: Optional[float] = None
    avg_likes: Optional[float] = None
    avg_engagement_rate: Optional[float] = None
    avg_retention: Optional[float] = None


class OutcomesResponse(BaseModel):
    outcomes: list[PublishedOutcomeResponse]
    recommendation_effectiveness: list[RecommendationGroupResponse]


class AccountConnectRequest(BaseModel):
    platform: str  # youtube | tiktok | instagram | twitter
    platform_account_id: str
    handle: str
    access_token: str
    refresh_token: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    follower_count: Optional[int] = None


class AccountUpdateRequest(BaseModel):
    auto_publish: Optional[bool] = None
    default_caption_variation: Optional[bool] = None


class DistributionPublishRequest(BaseModel):
    title: str
    base_caption: str
    target_account_ids: list[int]
    video_url: Optional[str] = None
    source_video_url: Optional[str] = None
    clip_start_sec: Optional[float] = None
    clip_end_sec: Optional[float] = None
    thumbnail_url: Optional[str] = None
    hashtags: Optional[list[str]] = None
    vary_captions: bool = True


# ---------------------------------------------------------------------------
# Response models — mirror src.features.distribution_hub serializers
# ---------------------------------------------------------------------------


class ConnectedAccountSummary(BaseModel):
    """One row in the connected-accounts response. Matches
    distribution_hub.AccountSummary.to_dict() field-for-field."""

    id: int
    platform: str = Field(..., description="youtube | tiktok | instagram | twitter")
    handle: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    follower_count: Optional[int] = None
    is_active: bool
    auto_publish: bool = Field(..., description="True if new jobs auto-target this account")
    default_caption_variation: bool = Field(
        ..., description="True if this account opts in to LLM-varied per-platform captions"
    )
    connected_at: str
    last_used_at: Optional[str] = None


class AccountListResponse(BaseModel):
    accounts: list[ConnectedAccountSummary]


class DeleteAccountResponse(BaseModel):
    success: bool


class PlatformSetupInfo(BaseModel):
    """One platform's OAuth setup state. ``accounts`` is the list of
    currently-connected handles; ``instructions`` is the marketing-page
    'how to connect' copy."""

    name: str
    accounts: list[ConnectedAccountSummary] = Field(default_factory=list)
    instructions: Optional[dict] = Field(
        default=None,
        description="Per-platform OAuth setup copy (URLs, scopes, env vars).",
    )

    model_config = {"extra": "allow"}


class DistributionResultSummary(BaseModel):
    """One per-account result inside a JobSummary."""

    id: int
    account_id: int
    status: str = Field(..., description="pending | success | failed")
    posted_url: Optional[str] = None
    posted_id: Optional[str] = None
    caption_used: Optional[str] = None
    error_message: Optional[str] = None
    completed_at: Optional[str] = None

    model_config = {"extra": "allow"}


class DistributionJobSummary(BaseModel):
    """Matches distribution_hub.JobSummary.to_dict()."""

    id: int
    title: str
    status: str = Field(..., description="pending | running | completed | partial | failed")
    target_count: int = Field(..., ge=0)
    success_count: int = Field(..., ge=0)
    failure_count: int = Field(..., ge=0)
    base_caption: Optional[str] = None
    video_url: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    results: list[DistributionResultSummary] = Field(default_factory=list)


class JobListResponse(BaseModel):
    jobs: list[DistributionJobSummary]


class PublishStartResponse(BaseModel):
    """Returned synchronously by /distribution/publish — the actual
    posting runs in the background. Poll /distribution/jobs/{id} for
    completion."""

    job_id: int
    status: str = Field(..., description="Always 'pending' on creation")
    target_count: int = Field(..., ge=0)
    message: str


@router.get("/distribution/accounts", response_model=AccountListResponse)
async def list_distribution_accounts(
    active_only: bool = False,
    current_user: User = Depends(get_current_user),
) -> AccountListResponse:
    """List all connected social accounts for the current user."""
    try:
        from src.features.distribution_hub import list_accounts
        async with get_async_session() as session:
            accounts = list_accounts(session, current_user.id, active_only=active_only)
            return AccountListResponse(
                accounts=[ConnectedAccountSummary(**a.to_dict()) for a in accounts]
            )
    except Exception as e:
        logger.error(f"Failed to list accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/distribution/accounts", response_model=ConnectedAccountSummary)
async def connect_distribution_account(
    request: AccountConnectRequest,
    current_user: User = Depends(get_current_user),
) -> ConnectedAccountSummary:
    """Manually register a connected social account.

    For YouTube specifically, prefer ``/auth/youtube`` (the OAuth flow auto-creates
    a ``YouTubeConnection`` record).
    """
    try:
        from src.features.distribution_hub import AccountSummary, add_account
        async with get_async_session() as session:
            account = add_account(
                session,
                user_id=current_user.id,
                platform=request.platform,
                platform_account_id=request.platform_account_id,
                handle=request.handle,
                access_token=request.access_token,
                refresh_token=request.refresh_token,
                display_name=request.display_name,
                avatar_url=request.avatar_url,
                follower_count=request.follower_count,
            )
            return ConnectedAccountSummary(**AccountSummary.from_model(account).to_dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to connect account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch(
    "/distribution/accounts/{account_id}", response_model=ConnectedAccountSummary
)
async def update_distribution_account(
    account_id: int,
    request: AccountUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> ConnectedAccountSummary:
    """Update settings on a connected account."""
    try:
        from src.features.distribution_hub import AccountSummary, update_account
        async with get_async_session() as session:
            account = update_account(
                session,
                user_id=current_user.id,
                account_id=account_id,
                auto_publish=request.auto_publish,
                default_caption_variation=request.default_caption_variation,
            )
            if not account:
                raise HTTPException(status_code=404, detail="Account not found")
            return ConnectedAccountSummary(**AccountSummary.from_model(account).to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/distribution/accounts/{account_id}", response_model=DeleteAccountResponse
)
async def remove_distribution_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
) -> DeleteAccountResponse:
    """Disconnect a social account (soft-delete)."""
    try:
        from src.features.distribution_hub import remove_account
        async with get_async_session() as session:
            removed = remove_account(session, current_user.id, account_id)
            if not removed:
                raise HTTPException(status_code=404, detail="Account not found")
            return DeleteAccountResponse(success=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/distribution/setup-status",
    response_model=dict[str, PlatformSetupInfo],
    response_model_exclude_none=False,
)
async def get_distribution_setup_status(
    current_user: User = Depends(get_current_user),
) -> dict[str, PlatformSetupInfo]:
    """Get OAuth setup instructions + connected accounts grouped by platform."""
    try:
        from src.features.distribution_hub import get_oauth_setup_status
        async with get_async_session() as session:
            return get_oauth_setup_status(session, current_user.id)
    except Exception as e:
        logger.error(f"Failed to get setup status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/distribution/jobs", response_model=JobListResponse)
async def list_distribution_jobs(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
) -> JobListResponse:
    """List recent distribution jobs for the current user."""
    try:
        from src.features.distribution_hub import list_jobs
        async with get_async_session() as session:
            jobs = list_jobs(session, current_user.id, limit=limit)
            return JobListResponse(
                jobs=[DistributionJobSummary(**j.to_dict()) for j in jobs]
            )
    except Exception as e:
        logger.error(f"Failed to list distribution jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/distribution/jobs/{job_id}", response_model=DistributionJobSummary)
async def get_distribution_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
) -> DistributionJobSummary:
    """Get a single distribution job + its per-account results."""
    try:
        from src.features.distribution_hub import get_job
        async with get_async_session() as session:
            job = get_job(session, current_user.id, job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            return DistributionJobSummary(**job.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get distribution job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/distribution/outcomes", response_model=OutcomesResponse)
@limiter.limit(Tier.READ)
async def list_outcomes(
    request: Request,  # noqa: ARG001 — required by slowapi limiter
    limit: int = 50,
    current_user: User = Depends(get_current_user),
):
    """Per-published-post timeline + recommendation effectiveness rollup.

    Powers the Distribution Hub "Outcomes" tab. Returns two parallel
    structures:

      * ``outcomes`` — one entry per successful publish to a single
        platform, with all captured snapshots (1h/24h/7d/30d) and
        the originating recommendation attribution (if any).
      * ``recommendation_effectiveness`` — grouped rollup so the
        dashboard can show "videos that took the Lead Magnet
        recommendation averaged +X% retention vs baseline".

    Returns an empty response (200, not 404) when the user hasn't
    published anything yet — the frontend renders an honest empty
    state pointing at Distribution Hub.
    """
    from src.features.publish_outcomes import (
        list_user_outcomes,
        rollup_recommendation_effectiveness,
    )

    # list_user_outcomes is a sync function, so use sync session for now
    with get_session() as db:
        outcomes = list_user_outcomes(
            db, user_id=current_user.id, limit=limit
        )
        groups = rollup_recommendation_effectiveness(outcomes)
        return OutcomesResponse(
            outcomes=[
                PublishedOutcomeResponse(
                    distribution_job_id=o.distribution_job_id,
                    distribution_result_id=o.distribution_result_id,
                    platform=o.platform,
                    posted_url=o.posted_url,
                    published_at=o.published_at,
                    title=o.title,
                    source_video_url=o.source_video_url,
                    snapshots={
                        k: SnapshotPointResponse(**vars(v))
                        for k, v in o.snapshots.items()
                    },
                    latest=(
                        SnapshotPointResponse(**vars(o.latest))
                        if o.latest is not None
                        else None
                    ),
                    cta_provenance=o.cta_provenance,
                )
                for o in outcomes
            ],
            recommendation_effectiveness=[
                RecommendationGroupResponse(**vars(g)) for g in groups
            ],
        )


@router.post("/distribution/publish", response_model=PublishStartResponse)
@limiter.limit(Tier.MEDIA_HEAVY)
async def publish_to_distribution(
    request: Request,
    body: DistributionPublishRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> PublishStartResponse:
    """Publish a video to N connected accounts.

    Creates a ``DistributionJob`` immediately and runs the actual posting in
    the background. Poll ``GET /distribution/jobs/{id}`` for status.
    """
    try:
        from src.features.distribution_hub import create_job

        async with get_async_session() as session:
            try:
                job = create_job(
                    session,
                    user_id=current_user.id,
                    title=body.title,
                    base_caption=body.base_caption,
                    target_account_ids=body.target_account_ids,
                    video_url=body.video_url,
                    source_video_url=body.source_video_url,
                    clip_start_sec=body.clip_start_sec,
                    clip_end_sec=body.clip_end_sec,
                    thumbnail_url=body.thumbnail_url,
                    vary_captions=body.vary_captions,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            job_id = job.id

        # Enqueue durable background work (RQ if Redis is configured,
        # else in-process via BackgroundTasks).
        from src.queue import enqueue_job, get_queue
        if get_queue() is not None:
            enqueue_job(
                "src.api.routers.distribution:_run_distribution_job",
                job_id=job_id,
                user_id=current_user.id,
                hashtags=body.hashtags or [],
                job_timeout=900,
            )
        else:
            # BackgroundTasks supports async functions directly
            background_tasks.add_task(
                _run_distribution_job_async,
                job_id=job_id,
                user_id=current_user.id,
                hashtags=body.hashtags or [],
            )

        return PublishStartResponse(
            job_id=job_id,
            status="pending",
            target_count=job.target_count,
            message=(
                "Distribution job started in background. "
                "Poll /distribution/jobs/{id} for status."
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start distribution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _run_distribution_job(job_id: int, user_id: int, hashtags: list[str]):
    """Sync wrapper for RQ: runs the async distribution job via asyncio.run().

    RQ and the sync queue fallback call functions synchronously, so we need
    this wrapper to properly execute the async logic.
    """
    import asyncio
    asyncio.run(_run_distribution_job_async(job_id, user_id, hashtags))


async def _run_distribution_job_async(job_id: int, user_id: int, hashtags: list[str]):
    """Async implementation of distribution job logic."""
    try:
        from src.features.llm_client import get_llm_client
        from src.features.social_publisher import SocialPublisher

        async with get_async_session() as session:
            job = (await session.execute(select(DistributionJob).where(
                DistributionJob.id == job_id,
                DistributionJob.user_id == user_id,
            ))).scalars().first()

            if not job:
                logger.error(f"Distribution job {job_id} not found")
                return

            job.status = "running"
            job.started_at = _dt.utcnow()
            await session.commit()

            results_pending = (await session.execute(select(DistributionResult).where(
                DistributionResult.job_id == job.id
            ))).scalars().all()
            account_ids = [r.account_id for r in results_pending]
            accounts_db = (await session.execute(
                select(ConnectedAccount).where(ConnectedAccount.id.in_(account_ids))
            )).scalars().all()

            accounts_payload = [
                {
                    "id": a.id,
                    "platform": a.platform,
                    "handle": a.handle,
                    "access_token": a.access_token,
                }
                for a in accounts_db
            ]

            video_url = job.video_url
            base_caption = job.base_caption or ""
            title = job.title
            vary = job.vary_captions

        if not video_url:
            async with get_async_session() as session:
                results = (await session.execute(select(DistributionResult).where(
                    DistributionResult.job_id == job_id
                ))).scalars().all()
                for r in results:
                    r.status = "failed"
                    r.error_message = "No video URL provided"
                    r.completed_at = _dt.utcnow()

                job = (await session.execute(select(DistributionJob).where(
                    DistributionJob.id == job_id
                ))).scalars().first()
                if job:
                    job.status = "failed"
                    job.failure_count = len(results)
                    job.completed_at = _dt.utcnow()
                await session.commit()
            return

        tmpdir = tempfile.mkdtemp(prefix="dist_")
        try:
            local_video = os.path.join(tmpdir, "video.mp4")

            try:
                import yt_dlp

                ydl_opts = {
                    "format": "best[height<=1080]/best",
                    "outtmpl": os.path.join(tmpdir, "video.%(ext)s"),
                    "quiet": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                for f in os.listdir(tmpdir):
                    if f.startswith("video."):
                        local_video = os.path.join(tmpdir, f)
                        break
            except Exception as e:
                logger.warning(f"yt-dlp failed, trying direct download: {e}")
                import httpx

                async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
                    resp = await client.get(video_url)
                    resp.raise_for_status()
                    with open(local_video, "wb") as f:
                        f.write(resp.content)

            if not os.path.exists(local_video):
                raise RuntimeError("Failed to download video")

            # Look up the publishing user's plan so the caption-variant
            # LLM call gets attributed correctly (Pro users get a much
            # higher budget than free; before this, the call was being
            # treated as anonymous/unbounded).
            user_plan = "free"
            try:
                async with get_async_session() as session:
                    user_row = (await session.execute(select(User).where(User.id == user_id))).scalars().first()
                    if user_row and user_row.plan:
                        user_plan = user_row.plan
            except Exception as e:
                logger.warning(f"distribution.plan_lookup_failed: {e}")

            publisher = SocialPublisher(use_upload_post=True)
            try:
                publish_results = await publisher.publish_to_accounts(
                    video_path=local_video,
                    title=title,
                    base_caption=base_caption,
                    accounts=accounts_payload,
                    hashtags=hashtags,
                    vary_captions=vary,
                    llm_client=get_llm_client() if vary else None,
                    user_id=user_id,
                    plan=user_plan,
                )
            finally:
                await publisher.close()

            success_count = 0
            failure_count = 0
            async with get_async_session() as session:
                for pr in publish_results:
                    db_result = (await session.execute(select(DistributionResult).where(
                        DistributionResult.job_id == job_id,
                        DistributionResult.account_id == pr["account_id"],
                    ))).scalars().first()
                    if not db_result:
                        continue
                    db_result.status = pr["status"]
                    db_result.posted_url = pr.get("posted_url")
                    db_result.posted_id = pr.get("posted_id")
                    db_result.caption_used = pr.get("caption_used")
                    db_result.error_message = pr.get("error_message")
                    db_result.completed_at = _dt.utcnow()

                    if pr["status"] == "success":
                        success_count += 1
                    else:
                        failure_count += 1

                job = (await session.execute(select(DistributionJob).where(
                    DistributionJob.id == job_id
                ))).scalars().first()
                if job:
                    job.success_count = success_count
                    job.failure_count = failure_count
                    if success_count == len(publish_results):
                        job.status = "completed"
                    elif success_count == 0:
                        job.status = "failed"
                    else:
                        job.status = "partial"
                    job.completed_at = _dt.utcnow()

                for pr in publish_results:
                    acct = (await session.execute(select(ConnectedAccount).where(
                        ConnectedAccount.id == pr["account_id"]
                    ))).scalars().first()
                    if acct:
                        acct.last_used_at = _dt.utcnow()

                await session.commit()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    except Exception as e:
        logger.error(f"Distribution job {job_id} failed: {e}")
        try:
            async with get_async_session() as session:
                job = (await session.execute(select(DistributionJob).where(
                    DistributionJob.id == job_id
                ))).scalars().first()
                if job:
                    job.status = "failed"
                    job.completed_at = _dt.utcnow()
                results = (await session.execute(select(DistributionResult).where(
                    DistributionResult.job_id == job_id,
                    DistributionResult.status == "pending",
                ))).scalars().all()
                for r in results:
                    r.status = "failed"
                    r.error_message = f"Job-level failure: {str(e)}"
                    r.completed_at = _dt.utcnow()
                await session.commit()
        except Exception:
            pass
