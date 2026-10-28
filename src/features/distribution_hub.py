"""
Distribution Hub - Multi-account, cross-platform distribution

Manages connected social accounts (YouTube, TikTok, Instagram, Twitter/X) and
orchestrates "distribute to all" jobs. Built on top of the existing
social_publisher infrastructure.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import structlog
from sqlalchemy.orm import Session

from src.database.models import (
    ConnectedAccount,
    DistributionJob,
    DistributionResult,
)

logger = structlog.get_logger()


SUPPORTED_PLATFORMS = ("youtube", "tiktok", "instagram", "twitter")


@dataclass
class AccountSummary:
    """Lightweight serializable view of a connected account."""
    id: int
    platform: str
    handle: str
    display_name: Optional[str]
    avatar_url: Optional[str]
    follower_count: Optional[int]
    is_active: bool
    auto_publish: bool
    default_caption_variation: bool
    connected_at: str
    last_used_at: Optional[str]
    
    @classmethod
    def from_model(cls, acct: ConnectedAccount) -> "AccountSummary":
        return cls(
            id=acct.id,
            platform=acct.platform,
            handle=acct.handle,
            display_name=acct.display_name,
            avatar_url=acct.avatar_url,
            follower_count=acct.follower_count,
            is_active=acct.is_active,
            auto_publish=acct.auto_publish,
            default_caption_variation=acct.default_caption_variation,
            connected_at=acct.connected_at.isoformat(),
            last_used_at=acct.last_used_at.isoformat() if acct.last_used_at else None,
        )
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "handle": self.handle,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "follower_count": self.follower_count,
            "is_active": self.is_active,
            "auto_publish": self.auto_publish,
            "default_caption_variation": self.default_caption_variation,
            "connected_at": self.connected_at,
            "last_used_at": self.last_used_at,
        }


@dataclass
class JobSummary:
    """Lightweight view of a distribution job + its per-account results."""
    id: int
    title: str
    status: str
    target_count: int
    success_count: int
    failure_count: int
    base_caption: Optional[str]
    video_url: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    results: List[Dict]
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "target_count": self.target_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "base_caption": self.base_caption,
            "video_url": self.video_url,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "results": self.results,
        }


# ============================================================
# ACCOUNT CRUD
# ============================================================


def list_accounts(session: Session, user_id: int, active_only: bool = False) -> List[AccountSummary]:
    """List all connected accounts for a user."""
    q = session.query(ConnectedAccount).filter(ConnectedAccount.user_id == user_id)
    if active_only:
        q = q.filter(ConnectedAccount.is_active == True)
    return [AccountSummary.from_model(a) for a in q.order_by(ConnectedAccount.connected_at.desc()).all()]


def add_account(
    session: Session,
    user_id: int,
    platform: str,
    platform_account_id: str,
    handle: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    display_name: Optional[str] = None,
    avatar_url: Optional[str] = None,
    follower_count: Optional[int] = None,
    scopes: Optional[List[str]] = None,
    token_expires_at: Optional[datetime] = None,
) -> ConnectedAccount:
    """Add a new connected account (or reactivate existing one)."""
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}. Must be one of {SUPPORTED_PLATFORMS}")
    
    # Check for existing
    existing = session.query(ConnectedAccount).filter(
        ConnectedAccount.user_id == user_id,
        ConnectedAccount.platform == platform,
        ConnectedAccount.platform_account_id == platform_account_id,
    ).first()
    
    if existing:
        # Update existing record (refresh credentials)
        existing.access_token = access_token
        existing.refresh_token = refresh_token
        existing.handle = handle
        existing.display_name = display_name
        existing.avatar_url = avatar_url
        existing.follower_count = follower_count
        existing.scopes = json.dumps(scopes) if scopes else None
        existing.token_expires_at = token_expires_at
        existing.is_active = True
        session.commit()
        logger.info(f"Refreshed connected account {platform}:@{handle} for user {user_id}")
        return existing
    
    account = ConnectedAccount(
        user_id=user_id,
        platform=platform,
        platform_account_id=platform_account_id,
        handle=handle,
        access_token=access_token,
        refresh_token=refresh_token,
        display_name=display_name,
        avatar_url=avatar_url,
        follower_count=follower_count,
        scopes=json.dumps(scopes) if scopes else None,
        token_expires_at=token_expires_at,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    logger.info(f"Added connected account {platform}:@{handle} for user {user_id}")
    return account


def remove_account(session: Session, user_id: int, account_id: int) -> bool:
    """Remove (soft-delete) a connected account."""
    account = session.query(ConnectedAccount).filter(
        ConnectedAccount.id == account_id,
        ConnectedAccount.user_id == user_id,
    ).first()
    
    if not account:
        return False
    
    account.is_active = False
    session.commit()
    logger.info(f"Deactivated account {account_id} for user {user_id}")
    return True


def update_account(
    session: Session,
    user_id: int,
    account_id: int,
    auto_publish: Optional[bool] = None,
    default_caption_variation: Optional[bool] = None,
) -> Optional[ConnectedAccount]:
    """Update settings on a connected account."""
    account = session.query(ConnectedAccount).filter(
        ConnectedAccount.id == account_id,
        ConnectedAccount.user_id == user_id,
    ).first()
    
    if not account:
        return None
    
    if auto_publish is not None:
        account.auto_publish = auto_publish
    if default_caption_variation is not None:
        account.default_caption_variation = default_caption_variation
    
    session.commit()
    return account


# ============================================================
# JOB MANAGEMENT
# ============================================================


def create_job(
    session: Session,
    user_id: int,
    title: str,
    base_caption: Optional[str],
    target_account_ids: List[int],
    video_url: Optional[str] = None,
    video_path: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    source_video_url: Optional[str] = None,
    clip_start_sec: Optional[float] = None,
    clip_end_sec: Optional[float] = None,
    vary_captions: bool = True,
) -> DistributionJob:
    """Create a distribution job + its per-account result rows."""
    # Validate accounts belong to user
    accounts = session.query(ConnectedAccount).filter(
        ConnectedAccount.id.in_(target_account_ids),
        ConnectedAccount.user_id == user_id,
        ConnectedAccount.is_active == True,
    ).all()
    
    if not accounts:
        raise ValueError("No valid active accounts in target list")
    
    job = DistributionJob(
        user_id=user_id,
        title=title,
        base_caption=base_caption,
        video_url=video_url,
        video_path=video_path,
        thumbnail_url=thumbnail_url,
        source_video_url=source_video_url,
        clip_start_sec=clip_start_sec,
        clip_end_sec=clip_end_sec,
        target_count=len(accounts),
        vary_captions=vary_captions,
        status="pending",
    )
    session.add(job)
    session.flush()  # Get job.id
    
    for acct in accounts:
        result = DistributionResult(
            job_id=job.id,
            account_id=acct.id,
            platform=acct.platform,
            status="pending",
        )
        session.add(result)
    
    session.commit()
    session.refresh(job)
    return job


def list_jobs(
    session: Session,
    user_id: int,
    limit: int = 20,
    status_filter: Optional[str] = None,
) -> List[JobSummary]:
    """List recent distribution jobs with their results."""
    q = session.query(DistributionJob).filter(DistributionJob.user_id == user_id)
    if status_filter:
        q = q.filter(DistributionJob.status == status_filter)
    jobs = q.order_by(DistributionJob.created_at.desc()).limit(limit).all()
    
    summaries = []
    for job in jobs:
        results = session.query(DistributionResult).filter(
            DistributionResult.job_id == job.id
        ).all()
        
        # Look up account handles for display
        account_ids = [r.account_id for r in results]
        accounts = (
            session.query(ConnectedAccount)
            .filter(ConnectedAccount.id.in_(account_ids))
            .all() if account_ids else []
        )
        account_map = {a.id: a for a in accounts}
        
        result_dicts = [
            {
                "id": r.id,
                "account_id": r.account_id,
                "platform": r.platform,
                "handle": account_map[r.account_id].handle if r.account_id in account_map else None,
                "status": r.status,
                "posted_url": r.posted_url,
                "posted_id": r.posted_id,
                "caption_used": r.caption_used,
                "error_message": r.error_message,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in results
        ]
        
        summaries.append(JobSummary(
            id=job.id,
            title=job.title,
            status=job.status,
            target_count=job.target_count,
            success_count=job.success_count,
            failure_count=job.failure_count,
            base_caption=job.base_caption,
            video_url=job.video_url,
            created_at=job.created_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            results=result_dicts,
        ))
    
    return summaries


def get_job(session: Session, user_id: int, job_id: int) -> Optional[JobSummary]:
    """Get a single job + its results."""
    summaries = list_jobs(session, user_id, limit=200)
    for s in summaries:
        if s.id == job_id:
            return s
    return None


def get_oauth_setup_status(session: Session, user_id: int) -> Dict[str, Dict]:
    """
    Per-platform OAuth setup status. Used by the frontend to show 'how to connect'
    cards for platforms with no accounts yet.
    """
    accounts = list_accounts(session, user_id, active_only=True)
    by_platform: Dict[str, List[AccountSummary]] = {p: [] for p in SUPPORTED_PLATFORMS}
    for a in accounts:
        if a.platform in by_platform:
            by_platform[a.platform].append(a)
    
    # Setup instructions per platform
    instructions = {
        "youtube": {
            "name": "YouTube",
            "oauth_path": "/auth/youtube",
            "docs": "Connect via YouTube OAuth in Settings.",
        },
        "tiktok": {
            "name": "TikTok",
            "oauth_path": "/auth/tiktok",
            "docs": "Requires TikTok for Developers API access. Apply at developers.tiktok.com.",
        },
        "instagram": {
            "name": "Instagram",
            "oauth_path": "/auth/instagram",
            "docs": "Requires Instagram Graph API. Connect a business account via Meta for Developers.",
        },
        "twitter": {
            "name": "Twitter / X",
            "oauth_path": "/auth/twitter",
            "docs": "Requires X API v2 elevated access.",
        },
    }
    
    return {
        platform: {
            **instructions[platform],
            "connected_count": len(by_platform[platform]),
            "accounts": [a.to_dict() for a in by_platform[platform]],
        }
        for platform in SUPPORTED_PLATFORMS
    }
