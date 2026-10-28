"""Owner-side analytics pull (Phase 3.2 — display half).

For each connected channel, restore the user's OAuth credentials and pull the
REAL analytics (impressions, CTR, average view %, retention curve) for the
videos we already track for that channel, upserting one ``OwnerVideoAnalytics``
row per video. This is display data — the honest, validated half of 3.2. The
prediction model that would train on this CTR is deferred behind the
channel-grouped re-validation (see TODO.md / the July eval); we never claim CTR
prediction off this until that gate passes.

Best-effort throughout: a single user's expired token or API error must not
break the batch. Uses the user's own analytics quota (their OAuth), not ours.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import structlog

logger = structlog.get_logger(__name__)

MAX_VIDEOS_PER_CHANNEL = 25
RECENT_DAYS = 60


def _creds_dict(conn) -> dict:
    """Build the google-auth creds dict from a YouTubeConnection (decrypts)."""
    return {
        "token": conn.access_token,
        "refresh_token": conn.refresh_token,
        "token_uri": conn.token_uri,
        "client_id": conn.client_id,
        "client_secret": conn.client_secret,
        "scopes": json.loads(conn.scopes) if conn.scopes else None,
    }


def _recent_video_ids(session, channel_id: str) -> list[str]:
    """The channel's recently-tracked video ids (we enrolled it on connect)."""
    from src.database.models import TrackedVideo

    cutoff = datetime.utcnow() - timedelta(days=RECENT_DAYS)
    rows = (
        session.query(TrackedVideo.video_id)
        .filter(TrackedVideo.channel_id == channel_id,
                TrackedVideo.published_at >= cutoff)
        .order_by(TrackedVideo.published_at.desc())
        .limit(MAX_VIDEOS_PER_CHANNEL)
        .all()
    )
    return [r[0] for r in rows]


def _upsert(session, user_id: int, channel_id: str, va, curve) -> None:
    from src.database.models import OwnerVideoAnalytics

    row = (
        session.query(OwnerVideoAnalytics)
        .filter_by(user_id=user_id, video_id=va.video_id)
        .first()
    )
    if row is None:
        row = OwnerVideoAnalytics(user_id=user_id, video_id=va.video_id, channel_id=channel_id)
        session.add(row)
    row.channel_id = channel_id
    row.title = (va.title or "")[:500]
    row.fetched_at = datetime.utcnow()
    row.views = int(va.views or 0)
    row.impressions = int(va.impressions or 0)
    row.ctr = float(va.ctr or 0.0)
    row.avg_view_percentage = float(va.avg_view_percentage or 0.0)
    row.avg_view_duration_seconds = float(va.avg_view_duration_seconds or 0.0)
    row.retention_curve = json.dumps(curve) if curve else None


def pull_for_connection(session, conn) -> int:
    """Pull + upsert analytics for one connection. Returns rows written."""
    from src.integrations.youtube_analytics import YouTubeAnalyticsClient

    client = YouTubeAnalyticsClient()
    client.credentials_from_dict(_creds_dict(conn))

    written = 0
    for vid in _recent_video_ids(session, conn.channel_id):
        try:
            va = client.get_video_analytics(vid)
            curve = client.get_retention_curve(vid)
            _upsert(session, conn.user_id, conn.channel_id, va, curve)
            written += 1
        except Exception as e:  # noqa: BLE001 — skip the one video, keep going
            logger.warning("owner_analytics.video_failed", video_id=vid, error=str(e)[:120])
    session.commit()
    return written


def pull_owner_analytics(session, user_id: int | None = None) -> dict:
    """Pull analytics for all active connections (or just ``user_id``'s)."""
    from src.database.models import YouTubeConnection

    q = session.query(YouTubeConnection).filter(YouTubeConnection.is_active.is_(True))
    if user_id is not None:
        q = q.filter(YouTubeConnection.user_id == user_id)
    conns = q.all()

    connections, videos = 0, 0
    for conn in conns:
        try:
            n = pull_for_connection(session, conn)
            videos += n
            connections += 1
        except Exception as e:  # noqa: BLE001 — one bad token shouldn't stop the batch
            logger.warning("owner_analytics.connection_failed",
                           user_id=conn.user_id, error=str(e)[:120])
    logger.info("owner_analytics.pulled", connections=connections, videos=videos)
    return {"connections": connections, "videos": videos}


def get_stored_analytics(session, user_id: int) -> dict:
    """Stored owner analytics for the user's channels, newest first, with a
    channel CTR baseline so each video reads above/below the user's own norm."""
    from src.database.models import OwnerVideoAnalytics

    rows = (
        session.query(OwnerVideoAnalytics)
        .filter(OwnerVideoAnalytics.user_id == user_id)
        .order_by(OwnerVideoAnalytics.fetched_at.desc(), OwnerVideoAnalytics.views.desc())
        .limit(100)
        .all()
    )
    ctrs = [r.ctr for r in rows if r.impressions > 0]
    channel_avg_ctr = round(sum(ctrs) / len(ctrs), 4) if ctrs else None
    return {
        "channel_avg_ctr": channel_avg_ctr,
        "fetched_at": rows[0].fetched_at.isoformat() + "Z" if rows else None,
        "videos": [
            {
                "video_id": r.video_id,
                "title": r.title,
                "views": r.views,
                "impressions": r.impressions,
                "ctr": r.ctr,
                "avg_view_percentage": r.avg_view_percentage,
                "avg_view_duration_seconds": r.avg_view_duration_seconds,
                "retention_curve": json.loads(r.retention_curve) if r.retention_curve else None,
                "watch_url": f"https://www.youtube.com/watch?v={r.video_id}",
            }
            for r in rows
        ],
    }
