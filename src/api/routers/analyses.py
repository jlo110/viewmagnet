"""/dashboard/stats and /analyses/* (history, by id, count)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from src.auth.dependencies import get_current_user
from src.config import PLAN_LIMITS
from src.database.connection import get_async_session
from src.database.models import User, UserVideoAnalysis

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["analyses"])


@router.get("/dashboard/stats")
async def get_dashboard_stats(current_user: User = Depends(get_current_user)):
    """Get dashboard statistics for the authenticated user."""
    user_id = current_user.id
    async with get_async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()

        # Reset monthly usage if needed (inline to avoid sync helper)
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        period_start = getattr(user, "usage_period_start", None) or user.created_at or now
        if (now - period_start) >= timedelta(days=30):
            user.analyses_this_month = 0
            user.usage_period_start = now
            await session.commit()
            await session.refresh(user)

        plan_cfg = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"])
        base_limit = plan_cfg.get("analyses_per_month", 10)
        referral_bonus = getattr(user, "referral_bonus_analyses", 0)
        total_limit = base_limit + referral_bonus if base_limit >= 0 else -1
        used = user.analyses_this_month

        if total_limit == -1:
            analyses_remaining = -1  # Unlimited
        else:
            analyses_remaining = max(0, total_limit - used)

        analyses_result = await session.execute(
            select(UserVideoAnalysis)
            .where(UserVideoAnalysis.user_id == user_id)
            .order_by(UserVideoAnalysis.analyzed_at.desc())
            .limit(20)
        )
        analyses = analyses_result.scalars().all()

        if not analyses:
            return {
                "avg_prediction_score": 0,
                "total_views_30d": 0,
                "videos_analyzed": 0,
                "analyses_remaining": analyses_remaining,
                "analyses_used": used,
                "analyses_limit": total_limit,
                "referral_bonus": referral_bonus,
                "above_baseline_pct": 0,
                "recent_analyses": [],
                "performance_trend": [],
            }

        scores = [a.prediction_score for a in analyses if a.prediction_score]
        avg_score = sum(scores) / len(scores) if scores else 0
        above_baseline = (sum(1 for s in scores if s > 50) / len(scores) * 100) if scores else 0

        performance_trend = []
        for a in reversed(analyses[:10]):
            if a.analyzed_at and a.prediction_score:
                performance_trend.append({
                    "date": a.analyzed_at.strftime("%b %d"),
                    "score": round(a.prediction_score),
                    "title": (a.title or "Unknown")[:30],
                })

        return {
            "avg_prediction_score": round(avg_score, 1),
            "total_views_30d": 0,  # Would need YouTube Analytics
            "videos_analyzed": len(analyses),
            "analyses_remaining": analyses_remaining,
            "analyses_used": used,
            "analyses_limit": total_limit,
            "referral_bonus": referral_bonus,
            "above_baseline_pct": round(above_baseline),
            "recent_analyses": [
                {
                    "video_id": a.video_id,
                    "title": a.title or "Unknown",
                    "score": a.prediction_score or 0,
                    "status": "above" if (a.prediction_score or 0) > 50 else "below",
                    "views": "N/A",
                    "date": a.analyzed_at.strftime("%b %d") if a.analyzed_at else "Unknown",
                }
                for a in analyses[:5]
            ],
            "performance_trend": performance_trend,
        }


@router.get("/analyses/history")
async def get_analysis_history(
    limit: int = Query(default=20, ge=1, le=500),
    current_user: User = Depends(get_current_user),
):
    """Get the authenticated user's video-analysis history.

    Uses ``AsyncSession`` so this list endpoint doesn't block the event loop.
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(UserVideoAnalysis)
            .where(UserVideoAnalysis.user_id == current_user.id)
            .order_by(UserVideoAnalysis.analyzed_at.desc())
            .limit(limit)
        )
        analyses = result.scalars().all()

        return {
            "analyses": [
                {
                    "id": a.id,
                    "video_id": a.video_id,
                    "video_url": a.video_url,
                    "title": a.title or "Unknown",
                    "prediction_score": a.prediction_score,
                    "prediction_tier": a.prediction_tier,
                    "title_score": a.title_score,
                    "thumbnail_score": a.thumbnail_score,
                    "analyzed_at": a.analyzed_at.isoformat() if a.analyzed_at else None,
                }
                for a in analyses
            ],
            "total": len(analyses),
        }


@router.get("/analyses/{video_id}")
async def get_analysis_by_video_id(
    video_id: str,
    current_user: User = Depends(get_current_user),
):
    """Fetch the most-recent analysis of ``video_id`` for the current user."""
    async with get_async_session() as session:
        result = await session.execute(
            select(UserVideoAnalysis)
            .where(
                UserVideoAnalysis.user_id == current_user.id,
                UserVideoAnalysis.video_id == video_id,
            )
            .order_by(UserVideoAnalysis.analyzed_at.desc())
            .limit(1)
        )
        analysis = result.scalars().first()

        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")

        explanations: list = []
        if analysis.shap_explanations:
            try:
                explanations = json.loads(analysis.shap_explanations)
            except json.JSONDecodeError:
                pass

        recommendations: list = []
        if analysis.recommendations:
            try:
                recommendations = json.loads(analysis.recommendations)
            except json.JSONDecodeError:
                pass

        return {
            "id": analysis.id,
            "video_id": analysis.video_id,
            "video_url": analysis.video_url,
            "title": analysis.title or "Unknown",
            "prediction_score": analysis.prediction_score,
            "prediction_tier": analysis.prediction_tier,
            "title_score": analysis.title_score,
            "thumbnail_score": analysis.thumbnail_score,
            "channel_score": None,
            "explanations": explanations,
            "recommendations": recommendations,
            "analyzed_at": analysis.analyzed_at.isoformat() if analysis.analyzed_at else None,
        }


@router.get("/analyses/video-count/{video_id}")
async def get_video_analysis_count(
    video_id: str,
    days: int = Query(default=7, ge=1, le=30),
    current_user: User = Depends(get_current_user),
):
    """Count how many times a video has been analyzed recently.

    Used by the UI to surface stability warnings against over-optimization.
    """
    async with get_async_session() as session:
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        result = await session.execute(
            select(UserVideoAnalysis)
            .where(
                UserVideoAnalysis.user_id == current_user.id,
                UserVideoAnalysis.video_id == video_id,
                UserVideoAnalysis.analyzed_at >= cutoff_date,
            )
            .order_by(UserVideoAnalysis.analyzed_at.asc())
        )
        analyses = result.scalars().all()
        count = len(analyses)

        if count == 0:
            return {
                "video_id": video_id,
                "count": 0,
                "days": days,
                "first_analyzed_at": None,
                "last_analyzed_at": None,
                "days_since_first": None,
                "stability_warning": None,
            }

        first_analyzed = analyses[0].analyzed_at
        last_analyzed = analyses[-1].analyzed_at
        days_since_first = (datetime.utcnow() - first_analyzed).days if first_analyzed else 0
        days_since_last = (datetime.utcnow() - last_analyzed).days if last_analyzed else 0

        stability_warning = None
        if count >= 4:
            stability_warning = {
                "level": "high",
                "message": (
                    f"You've analyzed this video {count} times in {days} days. "
                    "Consider waiting for performance data before making more changes."
                ),
                "recommendation": (
                    "Frequent re-analysis suggests over-optimization. Your title/"
                    "thumbnail need time to gather real viewer data. Wait at least "
                    "3-7 days before analyzing again."
                ),
            }
        elif count >= 2 and days_since_last <= 2:
            stability_warning = {
                "level": "medium",
                "message": (
                    f"You've analyzed this video {count} times recently. "
                    "Consider letting it perform before making changes."
                ),
                "recommendation": (
                    "Sometimes the best advice is to wait. Give your video time to "
                    "gather real data before re-optimizing."
                ),
            }

        return {
            "video_id": video_id,
            "count": count,
            "days": days,
            "first_analyzed_at": first_analyzed.isoformat() if first_analyzed else None,
            "last_analyzed_at": last_analyzed.isoformat() if last_analyzed else None,
            "days_since_first": days_since_first,
            "days_since_last": days_since_last,
            "stability_warning": stability_warning,
        }
