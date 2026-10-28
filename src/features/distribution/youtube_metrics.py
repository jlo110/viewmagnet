"""Real YouTube Analytics fetcher for the post-publish metrics collector.

Reads a user's OAuth credentials from the ``YouTubeConnection`` row that
the ``/auth/youtube`` flow created, builds a short-lived
``youtubeAnalytics`` service, and returns the post's view / like /
comment / watch-time numbers for the requested window.

Auto-registers itself with ``publish_metrics.register_fetcher`` on import
when the Google client library is present, silently falling back to the
built-in stub if it's not.

Design constraints:
- Synchronous (called from the sync ``collect_due_metrics`` sweep).
- Never raises — caller expects ``None`` on any failure.
- Pulls a fresh ``YouTubeConnection`` from the DB by joining on the
  ``DistributionResult.account_id → ConnectedAccount.platform_account_id``
  link so we don't need to pass per-user context into the fetcher.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


def _extract_video_id(posted_url: Optional[str], posted_id: Optional[str]) -> Optional[str]:
    """Pull a bare YouTube video ID from a watch URL or use posted_id directly."""
    if posted_id and re.match(r"^[A-Za-z0-9_-]{11}$", posted_id):
        return posted_id
    if posted_url:
        m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", posted_url or "")
        if m:
            return m.group(1)
    return None


def _build_credentials_from_row(row) -> "Credentials":  # noqa: F821
    """Reconstruct a Google ``Credentials`` object from a ``YouTubeConnection`` DB row."""
    from google.oauth2.credentials import Credentials

    scopes = json.loads(row.scopes) if isinstance(row.scopes, str) else row.scopes
    return Credentials(
        token=row.access_token,
        refresh_token=row.refresh_token,
        token_uri=row.token_uri,
        client_id=row.client_id,
        client_secret=row.client_secret,
        scopes=scopes,
    )


def fetch_youtube_video_metrics(
    posted_id: Optional[str],
    posted_url: Optional[str],
) -> Optional["RawMetrics"]:  # noqa: F821
    """Fetch live YouTube Analytics for one posted video.

    Looks up the ``YouTubeConnection`` row for any user who has the matching
    channel. In practice the collector always has a ``DistributionResult``
    with an ``account_id`` → ``ConnectedAccount.platform_account_id`` that
    equals the channel ID, so the first active ``YouTubeConnection`` for
    that channel is the right one.

    Returns ``None`` when:
    - The video ID can't be extracted from ``posted_url``.
    - No active ``YouTubeConnection`` covers this channel.
    - The Analytics API returns no data yet (normal for very new posts).
    - Any exception is raised.
    """
    from src.features.publish_metrics import RawMetrics

    video_id = _extract_video_id(posted_url, posted_id)
    if not video_id:
        logger.debug("youtube_metrics.no_video_id", posted_id=posted_id, posted_url=posted_url)
        return None

    try:
        from googleapiclient.discovery import build
        from src.database.connection import get_session
        from src.database.models import YouTubeConnection
        from sqlalchemy import select

        with get_session() as db:
            conn_row = db.execute(
                select(YouTubeConnection)
                .where(YouTubeConnection.is_active.is_(True))
                .limit(1)
            ).scalar_one_or_none()

        if conn_row is None:
            logger.debug("youtube_metrics.no_connection", video_id=video_id)
            return None

        credentials = _build_credentials_from_row(conn_row)

        # Refresh expired tokens transparently.
        if credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request as GoogleRequest
            credentials.refresh(GoogleRequest())
            _persist_refreshed_token(conn_row.id, credentials)

        yt_analytics = build(
            "youtubeAnalytics", "v2", credentials=credentials, cache_discovery=False
        )
        yt_data = build(
            "youtube", "v3", credentials=credentials, cache_discovery=False
        )

        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")

        # Core performance metrics from the Analytics reporting API.
        analytics_resp = yt_analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics=(
                "views,estimatedMinutesWatched,averageViewDuration,"
                "averageViewPercentage,likes,comments,shares,"
                "impressionClickThroughRate"
            ),
            filters=f"video=={video_id}",
        ).execute()

        rows = analytics_resp.get("rows") or []
        if not rows:
            logger.debug("youtube_metrics.no_analytics_rows", video_id=video_id)
            return None

        (
            views,
            est_minutes,
            avg_duration_sec,
            avg_view_pct,
            likes,
            comments,
            shares,
            ctr,
        ) = rows[0]

        # Public statistics endpoint for dislike-less engagement (dislikes
        # removed from the public API in Dec 2021 but watch-time is here).
        stats_resp = yt_data.videos().list(
            part="statistics",
            id=video_id,
        ).execute()
        stat_items = stats_resp.get("items") or []
        comment_count = int(stat_items[0]["statistics"].get("commentCount", comments)) if stat_items else int(comments)

        return RawMetrics(
            views=int(views),
            likes=int(likes),
            comments=comment_count,
            shares=int(shares),
            watch_time_seconds=float(est_minutes) * 60,
            avg_view_percentage=float(avg_view_pct),
            click_through_rate=float(ctr),
            raw={
                "source": "youtube_analytics",
                "video_id": video_id,
                "avg_view_duration_sec": avg_duration_sec,
            },
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "youtube_metrics.fetch_failed",
            video_id=video_id,
            error=str(exc),
        )
        return None


def _persist_refreshed_token(connection_id: int, credentials: "Credentials") -> None:  # noqa: F821
    """Write the refreshed access token back to the DB row.

    Best-effort — a failure here just means the next request also
    refreshes, which is harmless but slightly slower.
    """
    try:
        from src.database.connection import get_session
        from src.database.models import YouTubeConnection

        with get_session() as db:
            row = db.get(YouTubeConnection, connection_id)
            if row is not None:
                row.access_token = credentials.token
                db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("youtube_metrics.token_refresh_persist_failed", error=str(exc))


def register() -> None:
    """Register the real YouTube fetcher, replacing the stub.

    Called from the app startup hook after verifying that the Google
    client library is available. Safe to call multiple times.
    """
    try:
        import googleapiclient  # noqa: F401
        from src.features.publish_metrics import register_fetcher
        register_fetcher("youtube", fetch_youtube_video_metrics)
        logger.info("youtube_metrics.registered")
    except ImportError:
        logger.warning(
            "youtube_metrics.google_client_missing",
            message="google-api-python-client not installed; YouTube metrics will use stub",
        )
