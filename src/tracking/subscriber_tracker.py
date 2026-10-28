"""
Subscriber History Tracker for ViewMagnet.

Tracks subscriber counts over time to analyze growth patterns.
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from sqlalchemy.orm import Session

import structlog

logger = structlog.get_logger()


@dataclass
class SubscriberSnapshot:
    """A snapshot of subscriber count at a point in time."""
    channel_id: str
    subscriber_count: int
    timestamp: datetime
    view_count: Optional[int] = None
    video_count: Optional[int] = None


@dataclass
class GrowthMetrics:
    """Growth metrics for a channel."""
    channel_id: str
    channel_name: str
    current_subscribers: int
    growth_24h: int
    growth_24h_pct: float
    growth_7d: int
    growth_7d_pct: float
    growth_30d: int
    growth_30d_pct: float
    avg_daily_growth: float
    trajectory: str  # "accelerating", "steady", "slowing", "declining"
    snapshots: List[SubscriberSnapshot]


class SubscriberTracker:
    """
    Tracks subscriber counts over time for channels.
    
    Features:
    - Periodic snapshots of subscriber counts
    - Growth rate calculations (daily, weekly, monthly)
    - Trajectory analysis (accelerating, steady, slowing)
    - Historical data for trend visualization
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    def take_snapshot(
        self,
        channel_id: str,
        subscriber_count: int,
        view_count: Optional[int] = None,
        video_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Take a snapshot of a channel's subscriber count.
        
        Args:
            channel_id: YouTube channel ID.
            subscriber_count: Current subscriber count.
            view_count: Total view count (optional).
            video_count: Total video count (optional).
        
        Returns:
            Dict with snapshot details.
        """
        from src.database.models import ChannelSnapshot
        
        snapshot = ChannelSnapshot(
            channel_id=channel_id,
            subscriber_count=subscriber_count,
            total_views=view_count or 0,
            video_count=video_count or 0,
            snapshot_at=datetime.utcnow(),
        )
        
        self.session.add(snapshot)
        self.session.commit()
        
        logger.info(f"Took subscriber snapshot for {channel_id}: {subscriber_count:,}")
        
        return {
            "channel_id": channel_id,
            "subscriber_count": subscriber_count,
            "captured_at": snapshot.snapshot_at.isoformat(),
        }
    
    def get_snapshots(
        self,
        channel_id: str,
        days: int = 30,
    ) -> List[SubscriberSnapshot]:
        """
        Get historical snapshots for a channel.
        
        Args:
            channel_id: YouTube channel ID.
            days: Number of days of history to retrieve.
        
        Returns:
            List of SubscriberSnapshot objects.
        """
        from src.database.models import ChannelSnapshot
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        snapshots = self.session.query(ChannelSnapshot).filter(
            ChannelSnapshot.channel_id == channel_id,
            ChannelSnapshot.snapshot_at >= cutoff,
        ).order_by(ChannelSnapshot.snapshot_at.asc()).all()
        
        return [
            SubscriberSnapshot(
                channel_id=s.channel_id,
                subscriber_count=s.subscriber_count,
                timestamp=s.snapshot_at,
                view_count=s.total_views,
                video_count=s.video_count,
            )
            for s in snapshots
        ]
    
    def calculate_growth(
        self,
        channel_id: str,
    ) -> Optional[GrowthMetrics]:
        """
        Calculate growth metrics for a channel.
        
        Args:
            channel_id: YouTube channel ID.
        
        Returns:
            GrowthMetrics object or None if insufficient data.
        """
        from src.database.models import Channel
        
        # Get channel info
        channel = self.session.query(Channel).filter(
            Channel.channel_id == channel_id
        ).first()
        
        if not channel:
            return None
        
        # Get snapshots for last 30 days
        snapshots = self.get_snapshots(channel_id, days=30)
        
        if len(snapshots) < 2:
            return None
        
        current = snapshots[-1]
        
        # Find snapshots at key intervals
        now = datetime.utcnow()
        snapshot_24h = self._find_closest_snapshot(snapshots, now - timedelta(days=1))
        snapshot_7d = self._find_closest_snapshot(snapshots, now - timedelta(days=7))
        snapshot_30d = self._find_closest_snapshot(snapshots, now - timedelta(days=30))
        
        # Calculate growth
        growth_24h = current.subscriber_count - snapshot_24h.subscriber_count if snapshot_24h else 0
        growth_7d = current.subscriber_count - snapshot_7d.subscriber_count if snapshot_7d else 0
        growth_30d = current.subscriber_count - snapshot_30d.subscriber_count if snapshot_30d else 0
        
        # Calculate percentages
        growth_24h_pct = (growth_24h / snapshot_24h.subscriber_count * 100) if snapshot_24h and snapshot_24h.subscriber_count > 0 else 0
        growth_7d_pct = (growth_7d / snapshot_7d.subscriber_count * 100) if snapshot_7d and snapshot_7d.subscriber_count > 0 else 0
        growth_30d_pct = (growth_30d / snapshot_30d.subscriber_count * 100) if snapshot_30d and snapshot_30d.subscriber_count > 0 else 0
        
        # Calculate average daily growth
        first_snapshot = snapshots[0]
        days_covered = (current.timestamp - first_snapshot.timestamp).days or 1
        total_growth = current.subscriber_count - first_snapshot.subscriber_count
        avg_daily_growth = total_growth / days_covered
        
        # Determine trajectory
        trajectory = self._calculate_trajectory(snapshots)
        
        return GrowthMetrics(
            channel_id=channel_id,
            channel_name=channel.channel_name,
            current_subscribers=current.subscriber_count,
            growth_24h=growth_24h,
            growth_24h_pct=round(growth_24h_pct, 2),
            growth_7d=growth_7d,
            growth_7d_pct=round(growth_7d_pct, 2),
            growth_30d=growth_30d,
            growth_30d_pct=round(growth_30d_pct, 2),
            avg_daily_growth=round(avg_daily_growth, 1),
            trajectory=trajectory,
            snapshots=snapshots,
        )
    
    def _find_closest_snapshot(
        self,
        snapshots: List[SubscriberSnapshot],
        target_time: datetime,
    ) -> Optional[SubscriberSnapshot]:
        """Find the snapshot closest to a target time."""
        if not snapshots:
            return None
        
        closest = min(
            snapshots,
            key=lambda s: abs((s.timestamp - target_time).total_seconds())
        )
        
        # Only return if within 12 hours of target
        if abs((closest.timestamp - target_time).total_seconds()) < 43200:
            return closest
        
        return None
    
    def _calculate_trajectory(self, snapshots: List[SubscriberSnapshot]) -> str:
        """
        Calculate growth trajectory from snapshots.
        
        Compares recent growth rate to historical growth rate.
        """
        if len(snapshots) < 7:
            return "insufficient_data"
        
        # Split into two halves
        midpoint = len(snapshots) // 2
        first_half = snapshots[:midpoint]
        second_half = snapshots[midpoint:]
        
        # Calculate growth rates
        def growth_rate(snaps: List[SubscriberSnapshot]) -> float:
            if len(snaps) < 2:
                return 0
            days = (snaps[-1].timestamp - snaps[0].timestamp).days or 1
            growth = snaps[-1].subscriber_count - snaps[0].subscriber_count
            return growth / days
        
        first_rate = growth_rate(first_half)
        second_rate = growth_rate(second_half)
        
        if first_rate == 0:
            return "steady"
        
        change_ratio = second_rate / first_rate if first_rate != 0 else 1
        
        if change_ratio > 1.2:
            return "accelerating"
        elif change_ratio < 0.8:
            return "slowing"
        elif second_rate < 0:
            return "declining"
        else:
            return "steady"
    
    def get_growth_comparison(
        self,
        channel_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Compare growth metrics for multiple channels.
        
        Args:
            channel_ids: List of channel IDs to compare.
        
        Returns:
            List of growth metrics sorted by growth rate.
        """
        results = []
        
        for channel_id in channel_ids:
            metrics = self.calculate_growth(channel_id)
            if metrics:
                results.append({
                    "channel_id": metrics.channel_id,
                    "channel_name": metrics.channel_name,
                    "subscribers": metrics.current_subscribers,
                    "growth_30d": metrics.growth_30d,
                    "growth_30d_pct": metrics.growth_30d_pct,
                    "trajectory": metrics.trajectory,
                })
        
        # Sort by growth percentage
        results.sort(key=lambda x: x["growth_30d_pct"], reverse=True)
        
        return results
    
    def should_take_snapshot(
        self,
        channel_id: str,
        min_hours: int = 6,
    ) -> bool:
        """
        Check if it's time to take a new snapshot.
        
        Args:
            channel_id: Channel ID to check.
            min_hours: Minimum hours between snapshots.
        
        Returns:
            True if a new snapshot should be taken.
        """
        from src.database.models import ChannelSnapshot
        
        latest = self.session.query(ChannelSnapshot).filter(
            ChannelSnapshot.channel_id == channel_id
        ).order_by(ChannelSnapshot.snapshot_at.desc()).first()
        
        if not latest:
            return True
        
        time_since = datetime.utcnow() - latest.snapshot_at
        return time_since > timedelta(hours=min_hours)
    
    def schedule_snapshots(
        self,
        channel_ids: List[str],
    ) -> List[str]:
        """
        Check which channels need snapshots.
        
        Args:
            channel_ids: List of channel IDs to check.
        
        Returns:
            List of channel IDs that need snapshots.
        """
        needs_snapshot = []
        
        for channel_id in channel_ids:
            if self.should_take_snapshot(channel_id):
                needs_snapshot.append(channel_id)
        
        return needs_snapshot


def create_channel_snapshot_table():
    """Create the ChannelSnapshot table if it doesn't exist."""
    from src.database.connection import engine
    
    # Check if table exists, create if not
    from sqlalchemy import inspect
    inspector = inspect(engine)
    
    if "channel_snapshots" not in inspector.get_table_names():
        from src.database.models import ChannelSnapshot
        ChannelSnapshot.__table__.create(engine)
        logger.info("Created channel_snapshots table")


# Add ChannelSnapshot model to models.py if not exists
CHANNEL_SNAPSHOT_MODEL = '''
class ChannelSnapshot(Base):
    """Historical snapshot of channel subscriber count."""
    __tablename__ = "channel_snapshots"
    
    id = Column(Integer, primary_key=True)
    channel_id = Column(String(50), ForeignKey("channels.channel_id"), index=True)
    subscriber_count = Column(Integer)
    view_count = Column(BigInteger, nullable=True)
    video_count = Column(Integer, nullable=True)
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    channel = relationship("Channel", back_populates="snapshots")
'''
