"""YouTube OAuth: start, callback, list, disconnect."""
from __future__ import annotations

import json
import os
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.cache import cache_delete, cache_get_json, cache_set_json
from src.config import get_settings
from sqlalchemy import select
from src.database.connection import get_async_session
from src.database.models import User, YouTubeConnection

logger = structlog.get_logger(__name__)
settings = get_settings()

router = APIRouter(tags=["youtube-oauth"])

_OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes is plenty for an OAuth round-trip


def _oauth_state_key(state: str) -> str:
    return f"oauth:youtube:state:{state}"


class YouTubeAuthURL(BaseModel):
    """YouTube OAuth authorization URL."""
    auth_url: str
    state: str


@router.get("/auth/youtube", response_model=YouTubeAuthURL)
@limiter.limit(Tier.AUTH)
async def start_youtube_auth(
    request: Request,
    current_user: User = Depends(get_current_user),
    redirect_uri: str = Query(
        default="http://localhost:8000/auth/youtube/callback",
        description="OAuth callback URL",
    ),
):
    """Start the YouTube OAuth flow.

    State is persisted in Redis (or the in-memory fallback) with a 10-minute
    TTL so the flow works across multiple uvicorn workers.
    """
    try:
        from src.integrations.youtube_analytics import YouTubeAnalyticsClient
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail=(
                "Google auth libraries not installed. Run: pip install "
                "google-auth google-auth-oauthlib google-api-python-client"
            ),
        )

    client_secrets_path = settings.google_client_secrets or "secrets/youtube_oauth.json"
    if not os.path.exists(client_secrets_path):
        raise HTTPException(
            status_code=500,
            detail=f"OAuth client secrets file not found at {client_secrets_path}",
        )

    client = YouTubeAnalyticsClient(client_secrets_file=client_secrets_path)
    auth_url, state = client.get_authorization_url(redirect_uri=redirect_uri)

    await cache_set_json(
        _oauth_state_key(state),
        {
            "user_id": current_user.id,
            "redirect_uri": redirect_uri,
            "created_at": datetime.utcnow().isoformat(),
        },
        ttl_seconds=_OAUTH_STATE_TTL_SECONDS,
    )

    return YouTubeAuthURL(auth_url=auth_url, state=state)


@router.get("/auth/youtube/callback")
async def youtube_oauth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
):
    """Handle the YouTube OAuth callback (multi-worker safe)."""
    state_data = await cache_get_json(_oauth_state_key(state))
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    # Single-use state -- delete immediately to prevent replay.
    await cache_delete(_oauth_state_key(state))

    user_id = state_data["user_id"]
    redirect_uri = state_data["redirect_uri"]

    try:
        from src.integrations.youtube_analytics import YouTubeAnalyticsClient
    except ImportError:
        raise HTTPException(status_code=500, detail="Google auth libraries not installed")

    client_secrets_path = os.environ.get("GOOGLE_CLIENT_SECRETS", "secrets/youtube_oauth.json")
    client = YouTubeAnalyticsClient(client_secrets_file=client_secrets_path)

    authorization_response = str(request.url)

    try:
        client.handle_callback(
            authorization_response=authorization_response,
            redirect_uri=redirect_uri,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth token exchange failed: {str(e)}")

    try:
        channel_info = client.get_channel_info()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to get channel info: {str(e)}")

    async with get_async_session() as session:
        result = await session.execute(
            select(YouTubeConnection).where(
                YouTubeConnection.user_id == user_id,
                YouTubeConnection.channel_id == channel_info["channel_id"],
            )
        )
        existing = result.scalars().first()

        creds_dict = client.credentials_to_dict()

        if existing:
            existing.access_token = creds_dict["token"]
            existing.refresh_token = creds_dict["refresh_token"]
            existing.is_active = True
            existing.last_synced = datetime.utcnow()
        else:
            connection = YouTubeConnection(
                user_id=user_id,
                channel_id=channel_info["channel_id"],
                channel_name=channel_info["channel_name"],
                subscriber_count=channel_info["subscriber_count"],
                access_token=creds_dict["token"],
                refresh_token=creds_dict["refresh_token"],
                token_uri=creds_dict["token_uri"],
                client_id=creds_dict["client_id"],
                client_secret=creds_dict["client_secret"],
                scopes=json.dumps(list(creds_dict["scopes"])),
            )
            session.add(connection)

        await session.commit()

    # Connect Your Own Channel (3.1): enroll the just-connected channel into
    # collection so the validated detector + durability grader run on its future
    # uploads. Best-effort — a failure here must never break the OAuth flow.
    try:
        from src.api.routers.watchlist import _enroll_for_collection
        from src.database.connection import get_session

        with get_session() as sync_db:
            _enroll_for_collection(sync_db, channel_info["channel_id"])
    except Exception as e:  # noqa: BLE001
        logger.warning("youtube_oauth.enroll_failed",
                       channel=channel_info.get("channel_id"), error=str(e)[:120])

    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    return RedirectResponse(
        url=f"{frontend_url}/settings/youtube?connected=true&channel={channel_info['channel_name']}"
    )


@router.get("/auth/youtube/disconnect")
@limiter.limit(Tier.WRITE)
async def disconnect_youtube(
    request: Request,
    channel_id: str = Query(...),
    current_user: User = Depends(get_current_user),
):
    """Disconnect a YouTube channel. Requires authentication."""
    async with get_async_session() as session:
        result = await session.execute(
            select(YouTubeConnection).where(
                YouTubeConnection.user_id == current_user.id,
                YouTubeConnection.channel_id == channel_id,
            )
        )
        connection = result.scalars().first()

        if not connection:
            raise HTTPException(status_code=404, detail="Connection not found")

        connection.is_active = False
        await session.commit()

    return {"status": "disconnected", "channel_id": channel_id}


@router.get("/auth/youtube/connections")
@limiter.limit(Tier.READ)
async def get_youtube_connections(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Get all YouTube connections for the authenticated user."""
    async with get_async_session() as session:
        result = await session.execute(
            select(YouTubeConnection).where(
                YouTubeConnection.user_id == current_user.id,
                YouTubeConnection.is_active == True,  # noqa: E712 (SQLAlchemy idiom)
            )
        )
        connections = result.scalars().all()

        return {
            "connections": [
                {
                    "channel_id": c.channel_id,
                    "channel_name": c.channel_name,
                    "subscriber_count": c.subscriber_count,
                    "connected_at": c.connected_at.isoformat() if c.connected_at else None,
                    "last_synced": c.last_synced.isoformat() if c.last_synced else None,
                }
                for c in connections
            ]
        }
