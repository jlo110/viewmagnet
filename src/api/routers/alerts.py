"""Smart Alerts: /alerts, /alerts/settings, /alerts/{id}/dismiss, /alerts/summary."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from src.api._common import _dismissed_alerts, _recent_analyses
from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["alerts"])


class AlertSettingsRequest(BaseModel):
    enabled: bool = True
    underperformance_alerts: bool = True
    optimal_time_alerts: bool = True
    competitor_alerts: bool = True
    consistency_alerts: bool = True
    trend_alerts: bool = True
    milestone_alerts: bool = True
    underperformance_threshold: float = 0.5
    consistency_days: int = 14
    competitor_channels: list[str] = []


class AlertResponse(BaseModel):
    id: str
    type: str
    priority: str
    title: str
    message: str
    action: str
    action_url: Optional[str]
    data: dict
    created_at: str
    dismissed: bool


def _generate_analysis_based_alerts(channel_id: str, user_id: str) -> list:
    """Generate alerts based on recent video analyses cached in memory."""
    from src.features.smart_alerts import Alert, AlertPriority, AlertType

    alerts: list = []
    now = datetime.now()

    if channel_id not in _recent_analyses:
        return alerts

    for video_id, data in _recent_analyses[channel_id].items():
        result = data.get("result", {})
        cached_at = data.get("cached_at", now)

        # Skip stale analyses (older than 7 days).
        if (now - cached_at).days > 7:
            continue

        score = result.get("score", 50)
        title = result.get("video_title", "Unknown Video")[:40]
        mode = result.get("niche_comparison", {}).get("analysis_mode", "prediction")
        trajectory = result.get("trajectory", {}).get("label", "")

        if mode in ["velocity", "evaluation"] and score < 40:
            alert_id = f"underperf_{video_id}"
            if alert_id not in _dismissed_alerts:
                alerts.append(Alert(
                    id=alert_id,
                    type=AlertType.UNDERPERFORMANCE,
                    priority=AlertPriority.HIGH if score < 25 else AlertPriority.MEDIUM,
                    title="Video Underperforming",
                    message=(
                        f"'{title}...' has a Magnet Score of {score}. "
                        "Consider promoting or updating packaging."
                    ),
                    action="View Analysis",
                    action_url=f"https://youtube.com/watch?v={video_id}",
                    data={"video_id": video_id, "score": score, "mode": mode},
                    created_at=cached_at,
                    expires_at=now + timedelta(days=7),
                    dismissed=False,
                ))

        if trajectory == "viral" or (score >= 85 and mode == "velocity"):
            alert_id = f"milestone_{video_id}"
            if alert_id not in _dismissed_alerts:
                alerts.append(Alert(
                    id=alert_id,
                    type=AlertType.MILESTONE,
                    priority=AlertPriority.LOW,
                    title="Video Performing Well!",
                    message=(
                        f"'{title}...' is outperforming expectations with a score of {score}."
                    ),
                    action="View Stats",
                    action_url=f"https://youtube.com/watch?v={video_id}",
                    data={
                        "video_id": video_id,
                        "score": score,
                        "trajectory": trajectory,
                    },
                    created_at=cached_at,
                    expires_at=now + timedelta(days=3),
                    dismissed=False,
                ))

        if trajectory == "slow":
            alert_id = f"slow_{video_id}"
            if alert_id not in _dismissed_alerts:
                alerts.append(Alert(
                    id=alert_id,
                    type=AlertType.UNDERPERFORMANCE,
                    priority=AlertPriority.MEDIUM,
                    title="Slow Growth Detected",
                    message=(
                        f"'{title}...' has a slow trajectory. Consider active promotion."
                    ),
                    action="Promote Now",
                    action_url=f"https://youtube.com/watch?v={video_id}",
                    data={"video_id": video_id, "trajectory": trajectory},
                    created_at=cached_at,
                    expires_at=now + timedelta(days=5),
                    dismissed=False,
                ))

        if mode == "prediction":
            title_score = result.get("component_scores", {}).get("title_effectiveness", 50)
            thumb_score = result.get("component_scores", {}).get("thumbnail_impact", 50)

            if title_score < 40 or thumb_score < 40:
                weak_part = "title" if title_score < thumb_score else "thumbnail"
                alert_id = f"packaging_{video_id}"
                if alert_id not in _dismissed_alerts:
                    alerts.append(Alert(
                        id=alert_id,
                        type=AlertType.UNDERPERFORMANCE,
                        priority=AlertPriority.MEDIUM,
                        title=f"Weak {weak_part.title()} Detected",
                        message=(
                            f"'{title}...' has a low {weak_part} score "
                            f"({title_score if weak_part == 'title' else thumb_score}). "
                            "Consider improving before publishing."
                        ),
                        action="View Recommendations",
                        action_url=None,
                        data={
                            "video_id": video_id,
                            "title_score": title_score,
                            "thumbnail_score": thumb_score,
                        },
                        created_at=cached_at,
                        expires_at=now + timedelta(days=3),
                        dismissed=False,
                    ))

    return alerts


@router.get("/alerts", response_model=list[AlertResponse])
@limiter.limit(Tier.READ)
async def get_alerts(
    request: Request,
    channel_id: str = Query(..., max_length=24),
    current_user: User = Depends(get_current_user),
):
    """Smart alerts for a channel (auth required; user derived from JWT)."""
    user_id = str(current_user.id)
    request.state.current_user = current_user

    try:
        from src.features.smart_alerts import AlertSettings, SmartAlertSystem

        system = SmartAlertSystem()
        settings = AlertSettings(user_id=user_id)
        alerts = system.check_alerts(channel_id, settings)

        analysis_alerts = _generate_analysis_based_alerts(channel_id, user_id)
        alerts.extend(analysis_alerts)

        return [
            AlertResponse(
                id=a.id,
                type=a.type.value if hasattr(a.type, "value") else str(a.type),
                priority=a.priority.value if hasattr(a.priority, "value") else str(a.priority),
                title=a.title,
                message=a.message,
                action=a.action,
                action_url=a.action_url,
                data=a.data,
                created_at=(
                    a.created_at.isoformat() if hasattr(a.created_at, "isoformat")
                    else str(a.created_at)
                ),
                dismissed=a.dismissed,
            )
            for a in alerts
        ]
    except Exception as e:
        logger.error(f"Failed to get alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alerts/settings")
@limiter.limit(Tier.WRITE)
async def update_alert_settings(
    request: Request,
    settings: Optional[AlertSettingsRequest] = None,
    current_user: User = Depends(get_current_user),
):
    """Update alert settings for the authenticated user."""
    user_id = str(current_user.id)
    request.state.current_user = current_user
    try:
        from src.features.smart_alerts import AlertSettings

        alert_settings = AlertSettings(
            user_id=user_id,
            enabled=settings.enabled if settings else True,
            underperformance_alerts=settings.underperformance_alerts if settings else True,
            optimal_time_alerts=settings.optimal_time_alerts if settings else True,
            competitor_alerts=settings.competitor_alerts if settings else True,
            consistency_alerts=settings.consistency_alerts if settings else True,
            trend_alerts=settings.trend_alerts if settings else True,
            milestone_alerts=settings.milestone_alerts if settings else True,
            underperformance_threshold=(
                settings.underperformance_threshold if settings else 0.5
            ),
            consistency_days=settings.consistency_days if settings else 14,
            competitor_channels=settings.competitor_channels if settings else [],
        )

        return {
            "status": "updated",
            "user_id": user_id,
            "settings": {
                "enabled": alert_settings.enabled,
                "underperformance_alerts": alert_settings.underperformance_alerts,
                "optimal_time_alerts": alert_settings.optimal_time_alerts,
                "competitor_alerts": alert_settings.competitor_alerts,
                "consistency_alerts": alert_settings.consistency_alerts,
                "trend_alerts": alert_settings.trend_alerts,
                "milestone_alerts": alert_settings.milestone_alerts,
            },
        }
    except Exception as e:
        logger.error(f"Failed to update alert settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alerts/{alert_id}/dismiss")
@limiter.limit(Tier.WRITE)
async def dismiss_alert(
    request: Request,
    alert_id: str,
    current_user: User = Depends(get_current_user),
):
    """Dismiss an alert (auth required)."""
    user_id = str(current_user.id)
    request.state.current_user = current_user
    try:
        from src.features.smart_alerts import SmartAlertSystem

        system = SmartAlertSystem()
        system.dismiss_alert(user_id, alert_id)
        _dismissed_alerts.add(alert_id)

        return {"status": "dismissed", "alert_id": alert_id}
    except Exception as e:
        logger.error(f"Failed to dismiss alert: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts/summary")
@limiter.limit(Tier.READ)
async def get_alert_summary(
    request: Request,
    channel_id: str = Query(..., max_length=24),
    current_user: User = Depends(get_current_user),
):
    """Summary of alerts for a channel (auth required)."""
    user_id = str(current_user.id)
    request.state.current_user = current_user
    try:
        from src.features.smart_alerts import (
            AlertSettings,
            SmartAlertSystem,
            get_alert_summary,
        )

        system = SmartAlertSystem()
        settings = AlertSettings(user_id=user_id)
        alerts = system.check_alerts(channel_id, settings)
        return get_alert_summary(alerts)
    except Exception as e:
        logger.error(f"Failed to get alert summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
