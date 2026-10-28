"""
Smart Alerts System

Automated notifications and reminders for creators:
- Video underperformance alerts
- Optimal posting time reminders
- Competitor upload alerts
- Consistency reminders
- Trend alerts
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from enum import Enum

from src.database.connection import get_session
from src.database.models import Video, Channel


class AlertType(Enum):
    UNDERPERFORMANCE = "underperformance"
    OPTIMAL_TIME = "optimal_time"
    COMPETITOR = "competitor"
    CONSISTENCY = "consistency"
    TREND = "trend"
    MILESTONE = "milestone"


class AlertPriority(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Alert:
    """A smart alert."""
    id: str
    type: AlertType
    priority: AlertPriority
    title: str
    message: str
    action: str  # What the creator should do
    action_url: Optional[str]
    data: Dict  # Additional context
    created_at: datetime
    expires_at: Optional[datetime]
    dismissed: bool = False


@dataclass
class AlertSettings:
    """User's alert preferences."""
    user_id: str
    enabled: bool = True
    
    # Which alerts to receive
    underperformance_alerts: bool = True
    optimal_time_alerts: bool = True
    competitor_alerts: bool = True
    consistency_alerts: bool = True
    trend_alerts: bool = True
    milestone_alerts: bool = True
    
    # Thresholds
    underperformance_threshold: float = 0.5  # Below 50% of average
    consistency_days: int = 14  # Alert after X days without upload
    
    # Delivery
    email_enabled: bool = True
    push_enabled: bool = False
    in_app_enabled: bool = True
    
    # Quiet hours
    quiet_start: int = 22  # 10 PM
    quiet_end: int = 8  # 8 AM
    
    # Competitor channels to track
    competitor_channels: List[str] = field(default_factory=list)


class SmartAlertSystem:
    """Manages smart alerts for creators."""
    
    def __init__(self):
        self.alerts: Dict[str, List[Alert]] = {}  # user_id -> alerts
    
    def check_alerts(self, channel_id: str, settings: AlertSettings = None) -> List[Alert]:
        """
        Check all alert conditions for a channel.
        
        Args:
            channel_id: Channel to check
            settings: Alert preferences (uses defaults if not provided)
            
        Returns:
            List of triggered alerts
        """
        if settings is None:
            settings = AlertSettings(user_id=channel_id)
        
        alerts = []
        
        if settings.underperformance_alerts:
            underperf = self._check_underperformance(channel_id, settings)
            if underperf:
                alerts.extend(underperf)
        
        if settings.optimal_time_alerts:
            optimal = self._check_optimal_time(channel_id)
            if optimal:
                alerts.append(optimal)
        
        if settings.competitor_alerts and settings.competitor_channels:
            comp = self._check_competitors(channel_id, settings.competitor_channels)
            alerts.extend(comp)
        
        if settings.consistency_alerts:
            consistency = self._check_consistency(channel_id, settings.consistency_days)
            if consistency:
                alerts.append(consistency)
        
        if settings.milestone_alerts:
            milestones = self._check_milestones(channel_id)
            alerts.extend(milestones)
        
        return alerts
    
    def _check_underperformance(
        self, 
        channel_id: str, 
        settings: AlertSettings
    ) -> List[Alert]:
        """Check for underperforming videos."""
        alerts = []
        
        try:
            with get_session() as session:
                channel = session.query(Channel).filter_by(channel_id=channel_id).first()
                if not channel:
                    return alerts
                
                avg_views = channel.avg_views_per_video or 0
                threshold = avg_views * settings.underperformance_threshold
                
                # Get recent videos (last 7 days)
                week_ago = datetime.utcnow() - timedelta(days=7)
                recent_videos = session.query(Video).filter(
                    Video.channel_id == channel_id,
                    Video.published_at >= week_ago
                ).all()
                
                for video in recent_videos:
                    # Check if video is old enough (at least 24 hours)
                    if video.published_at < datetime.utcnow() - timedelta(hours=24):
                        if video.view_count < threshold:
                            ratio = video.view_count / avg_views if avg_views else 0
                            
                            alerts.append(Alert(
                                id=f"underperf_{video.video_id}",
                                type=AlertType.UNDERPERFORMANCE,
                                priority=AlertPriority.HIGH if ratio < 0.25 else AlertPriority.MEDIUM,
                                title="Video Underperforming",
                                message=f"'{video.title[:40]}...' is at {ratio*100:.0f}% of your average views",
                                action="Consider updating thumbnail or promoting on social",
                                action_url=f"https://youtube.com/watch?v={video.video_id}",
                                data={
                                    "video_id": video.video_id,
                                    "current_views": video.view_count,
                                    "expected_views": avg_views,
                                    "ratio": ratio
                                },
                                created_at=datetime.utcnow(),
                                expires_at=datetime.utcnow() + timedelta(days=7)
                            ))
        except Exception as e:
            print(f"Error checking underperformance: {e}")
        
        return alerts
    
    def _check_optimal_time(self, channel_id: str) -> Optional[Alert]:
        """Check if it's a good time to post."""
        try:
            with get_session() as session:
                # Get channel's best posting times from historical data
                videos = session.query(Video).filter_by(
                    channel_id=channel_id
                ).order_by(Video.view_count.desc()).limit(50).all()
                
                if not videos:
                    return None
                
                # Find best hour and day from top performers
                hours = {}
                days = {}
                
                for v in videos[:20]:  # Top 20 performers
                    if v.published_at:
                        hour = v.published_at.hour
                        day = v.published_at.strftime("%A")
                        hours[hour] = hours.get(hour, 0) + 1
                        days[day] = days.get(day, 0) + 1
                
                if not hours or not days:
                    return None
                
                best_hour = max(hours, key=hours.get)
                best_day = max(days, key=days.get)
                
                # Check if we're within 2 hours of optimal time
                current_hour = datetime.utcnow().hour
                current_day = datetime.utcnow().strftime("%A")
                
                if current_day == best_day and abs(current_hour - best_hour) <= 2:
                    return Alert(
                        id=f"optimal_time_{datetime.utcnow().date()}",
                        type=AlertType.OPTIMAL_TIME,
                        priority=AlertPriority.MEDIUM,
                        title="Optimal Posting Time",
                        message=f"Now is a great time to upload! Your top videos were posted around {best_hour}:00 on {best_day}s",
                        action="Consider uploading your next video now",
                        action_url="https://studio.youtube.com",
                        data={
                            "best_hour": best_hour,
                            "best_day": best_day,
                            "top_videos_at_this_time": hours.get(best_hour, 0)
                        },
                        created_at=datetime.utcnow(),
                        expires_at=datetime.utcnow() + timedelta(hours=3)
                    )
        except Exception as e:
            print(f"Error checking optimal time: {e}")
        
        return None
    
    def _check_competitors(
        self, 
        channel_id: str, 
        competitor_ids: List[str]
    ) -> List[Alert]:
        """Check for competitor uploads."""
        alerts = []
        
        try:
            with get_session() as session:
                # Check for new videos from competitors in last 24 hours
                day_ago = datetime.utcnow() - timedelta(hours=24)
                
                for comp_id in competitor_ids:
                    comp = session.query(Channel).filter_by(channel_id=comp_id).first()
                    if not comp:
                        continue
                    
                    new_videos = session.query(Video).filter(
                        Video.channel_id == comp_id,
                        Video.published_at >= day_ago
                    ).all()
                    
                    for video in new_videos:
                        # Check if it's a potential hit
                        comp_avg = comp.avg_views_per_video or 0
                        velocity = video.view_count / max(1, (datetime.utcnow() - video.published_at).total_seconds() / 3600)  # Views per hour
                        expected_velocity = comp_avg / 24 if comp_avg else 0
                        
                        is_trending = velocity > expected_velocity * 1.5
                        
                        alerts.append(Alert(
                            id=f"competitor_{video.video_id}",
                            type=AlertType.COMPETITOR,
                            priority=AlertPriority.HIGH if is_trending else AlertPriority.LOW,
                            title=f"Competitor Upload: {comp.channel_name}",
                            message=f"'{video.title[:40]}...' - {video.view_count:,} views in first hours",
                            action="Study this video for insights" if is_trending else "Monitor performance",
                            action_url=f"https://youtube.com/watch?v={video.video_id}",
                            data={
                                "competitor_name": comp.channel_name,
                                "video_id": video.video_id,
                                "views": video.view_count,
                                "is_trending": is_trending,
                                "velocity": velocity
                            },
                            created_at=datetime.utcnow(),
                            expires_at=datetime.utcnow() + timedelta(days=3)
                        ))
        except Exception as e:
            print(f"Error checking competitors: {e}")
        
        return alerts
    
    def _check_consistency(self, channel_id: str, threshold_days: int) -> Optional[Alert]:
        """Check if creator hasn't uploaded in a while."""
        try:
            with get_session() as session:
                # Get last upload
                last_video = session.query(Video).filter_by(
                    channel_id=channel_id
                ).order_by(Video.published_at.desc()).first()
                
                if not last_video or not last_video.published_at:
                    return None
                
                days_since = (datetime.utcnow() - last_video.published_at).days
                
                if days_since >= threshold_days:
                    return Alert(
                        id=f"consistency_{channel_id}_{datetime.utcnow().date()}",
                        type=AlertType.CONSISTENCY,
                        priority=AlertPriority.MEDIUM if days_since < threshold_days * 2 else AlertPriority.HIGH,
                        title="Upload Reminder",
                        message=f"It's been {days_since} days since your last upload. Your audience misses you!",
                        action="Upload a new video to maintain momentum",
                        action_url="https://studio.youtube.com",
                        data={
                            "days_since_upload": days_since,
                            "last_video_title": last_video.title,
                            "last_video_date": str(last_video.published_at)
                        },
                        created_at=datetime.utcnow(),
                        expires_at=datetime.utcnow() + timedelta(days=1)
                    )
        except Exception as e:
            print(f"Error checking consistency: {e}")
        
        return None
    
    def _check_milestones(self, channel_id: str) -> List[Alert]:
        """Check for milestone achievements."""
        alerts = []
        milestones = [1000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000]
        
        try:
            with get_session() as session:
                channel = session.query(Channel).filter_by(channel_id=channel_id).first()
                if not channel:
                    return alerts
                
                # Check subscriber milestones
                subs = channel.subscriber_count or 0
                for milestone in milestones:
                    # Check if recently crossed milestone (within 1% above)
                    if subs >= milestone and subs < milestone * 1.01:
                        alerts.append(Alert(
                            id=f"milestone_subs_{milestone}_{channel_id}",
                            type=AlertType.MILESTONE,
                            priority=AlertPriority.LOW,
                            title="🎉 Milestone Reached!",
                            message=f"Congratulations! You hit {milestone:,} subscribers!",
                            action="Celebrate with your community",
                            action_url=None,
                            data={
                                "type": "subscribers",
                                "milestone": milestone,
                                "current": subs
                            },
                            created_at=datetime.utcnow(),
                            expires_at=datetime.utcnow() + timedelta(days=7)
                        ))
                        break
                
                # Check video view milestones
                recent_videos = session.query(Video).filter(
                    Video.channel_id == channel_id,
                    Video.published_at >= datetime.utcnow() - timedelta(days=7)
                ).all()
                
                for video in recent_videos:
                    for milestone in milestones:
                        if video.view_count >= milestone and video.view_count < milestone * 1.05:
                            alerts.append(Alert(
                                id=f"milestone_views_{milestone}_{video.video_id}",
                                type=AlertType.MILESTONE,
                                priority=AlertPriority.LOW,
                                title="🎉 Video Milestone!",
                                message=f"'{video.title[:30]}...' hit {milestone:,} views!",
                                action="Share on social media",
                                action_url=f"https://youtube.com/watch?v={video.video_id}",
                                data={
                                    "type": "video_views",
                                    "milestone": milestone,
                                    "video_id": video.video_id,
                                    "current": video.view_count
                                },
                                created_at=datetime.utcnow(),
                                expires_at=datetime.utcnow() + timedelta(days=3)
                            ))
                            break
        except Exception as e:
            print(f"Error checking milestones: {e}")
        
        return alerts
    
    def get_pending_alerts(self, user_id: str) -> List[Alert]:
        """Get all pending (non-dismissed, non-expired) alerts for a user."""
        if user_id not in self.alerts:
            return []
        
        now = datetime.utcnow()
        return [
            a for a in self.alerts[user_id]
            if not a.dismissed and (a.expires_at is None or a.expires_at > now)
        ]
    
    def dismiss_alert(self, user_id: str, alert_id: str) -> bool:
        """Dismiss an alert."""
        if user_id not in self.alerts:
            return False
        
        for alert in self.alerts[user_id]:
            if alert.id == alert_id:
                alert.dismissed = True
                return True
        
        return False
    
    def format_alert_for_email(self, alert: Alert) -> Dict:
        """Format an alert for email delivery."""
        priority_emoji = {
            AlertPriority.HIGH: "🔴",
            AlertPriority.MEDIUM: "🟡",
            AlertPriority.LOW: "🟢"
        }
        
        return {
            "subject": f"{priority_emoji.get(alert.priority, '')} ViewMagnet: {alert.title}",
            "body": f"""
{alert.message}

Recommended Action:
{alert.action}

{f'View: {alert.action_url}' if alert.action_url else ''}

---
ViewMagnet - YouTube Intelligence Platform
Manage alerts: https://ViewMagnet.app/settings/alerts
""",
            "html": f"""
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <h2 style="color: #8b5cf6;">{alert.title}</h2>
    <p style="font-size: 16px;">{alert.message}</p>
    <div style="background: #f3f4f6; padding: 16px; border-radius: 8px; margin: 16px 0;">
        <strong>Recommended Action:</strong><br>
        {alert.action}
    </div>
    {f'<a href="{alert.action_url}" style="display: inline-block; background: #8b5cf6; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px;">View Details</a>' if alert.action_url else ''}
</div>
"""
        }


# Convenience functions
def check_channel_alerts(channel_id: str, settings: AlertSettings = None) -> List[Alert]:
    """Check all alerts for a channel."""
    system = SmartAlertSystem()
    return system.check_alerts(channel_id, settings)


def get_alert_summary(alerts: List[Alert]) -> Dict:
    """Get summary of alerts by type and priority."""
    summary = {
        "total": len(alerts),
        "by_type": {},
        "by_priority": {},
        "high_priority": []
    }
    
    for alert in alerts:
        # By type
        type_name = alert.type.value
        summary["by_type"][type_name] = summary["by_type"].get(type_name, 0) + 1
        
        # By priority
        priority_name = alert.priority.value
        summary["by_priority"][priority_name] = summary["by_priority"].get(priority_name, 0) + 1
        
        # High priority list
        if alert.priority == AlertPriority.HIGH:
            summary["high_priority"].append({
                "title": alert.title,
                "message": alert.message
            })
    
    return summary




