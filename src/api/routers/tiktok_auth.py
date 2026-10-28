"""TikTok OAuth 2.0: start, callback, disconnect.

Uses TikTok's Login Kit v2 (PKCE-optional):
  https://developers.tiktok.com/doc/oauth-user-access-token-management

Required env vars:
  TIKTOK_CLIENT_KEY      — from TikTok Developer Portal app
  TIKTOK_CLIENT_SECRET   — from TikTok Developer Portal app

When either var is absent the start endpoint returns 503 so the UI
can show a "not configured" state without crashing.

On success the callback writes a ``ConnectedAccount`` row (platform=tiktok)
with the encrypted access + refresh tokens, then redirects the frontend to
``/dashboard/distribution`` so the hub refreshes its account list.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.cache import cache_delete, cache_get_json, cache_set_json
from src.config import get_settings
from src.database.connection import get_async_session
from src.database.models import ConnectedAccount, User
from sqlalchemy import select

logger = structlog.get_logger(__name__)
settings = get_settings()
router = APIRouter(tags=["tiktok-oauth"])

_STATE_TTL = 600  # 10 minutes
_TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
_TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_TIKTOK_USER_URL = "https://open.tiktokapis.com/v2/user/info/"
_TIKTOK_SCOPES = "user.info.basic,user.info.profile,user.info.stats,video.list"


def _state_key(state: str) -> str:
    return f"oauth:tiktok:state:{state}"


def _client_key() -> Optional[str]:
    return os.environ.get("TIKTOK_CLIENT_KEY")


def _client_secret() -> Optional[str]:
    return os.environ.get("TIKTOK_CLIENT_SECRET")


def _is_configured() -> bool:
    return bool(_client_key() and _client_secret())


class TikTokAuthURL(BaseModel):
    auth_url: str
    state: str


@router.get("/auth/tiktok", response_model=TikTokAuthURL)
@limiter.limit(Tier.AUTH)
async def start_tiktok_auth(
    request: Request,
    current_user: User = Depends(get_current_user),
    redirect_uri: str = Query(
        default="",
        description="OAuth callback URL — defaults to <origin>/auth/tiktok/callback",
    ),
):
    """Begin the TikTok OAuth 2.0 flow.

    Returns an ``auth_url`` the frontend should redirect the user to.
    State is stored in Redis (10-minute TTL) so callbacks work across
    multiple API workers.
    """
    if not _is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "TikTok OAuth is not configured. "
                "Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET."
            ),
        )

    if not redirect_uri:
        # Infer from the incoming Host header so dev + prod both work.
        base = str(request.base_url).rstrip("/")
        redirect_uri = f"{base}/auth/tiktok/callback"

    state = secrets.token_urlsafe(32)
    await cache_set_json(
        _state_key(state),
        {"user_id": current_user.id, "redirect_uri": redirect_uri},
        ttl=_STATE_TTL,
    )

    params = {
        "client_key": _client_key(),
        "scope": _TIKTOK_SCOPES,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    from urllib.parse import urlencode
    auth_url = f"{_TIKTOK_AUTH_URL}?{urlencode(params)}"

    logger.info("tiktok_auth.start", user_id=current_user.id)
    return TikTokAuthURL(auth_url=auth_url, state=state)


@router.get("/auth/tiktok/callback")
async def tiktok_callback(
    request: Request,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    error_description: Optional[str] = Query(default=None),
):
    """Handle TikTok OAuth callback.

    Exchanges the auth code for access + refresh tokens, fetches the
    user's TikTok profile, and upserts a ``ConnectedAccount`` row.
    """
    frontend_base = settings.frontend_url or "http://localhost:5173"
    error_redirect = f"{frontend_base}/dashboard/distribution?tiktok_error=true"

    if error or not code or not state:
        logger.warning(
            "tiktok_auth.callback_error",
            error=error,
            desc=error_description,
        )
        return RedirectResponse(url=error_redirect)

    cached = await cache_get_json(_state_key(state))
    if not cached:
        logger.warning("tiktok_auth.state_expired_or_invalid", state=state[:8])
        return RedirectResponse(url=error_redirect)

    await cache_delete(_state_key(state))
    user_id: int = cached["user_id"]
    redirect_uri: str = cached["redirect_uri"]

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            # Exchange code for tokens.
            token_resp = await client.post(
                _TIKTOK_TOKEN_URL,
                data={
                    "client_key": _client_key(),
                    "client_secret": _client_secret(),
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

        access_token: str = token_data["access_token"]
        refresh_token: Optional[str] = token_data.get("refresh_token")
        expires_in: int = token_data.get("expires_in", 86400)
        open_id: str = token_data["open_id"]

        # Fetch user profile.
        async with httpx.AsyncClient(timeout=15) as client:
            user_resp = await client.get(
                _TIKTOK_USER_URL,
                params={"fields": "open_id,union_id,avatar_url,display_name,follower_count"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_resp.raise_for_status()
            user_info = user_resp.json().get("data", {}).get("user", {})

        handle = user_info.get("display_name") or f"tiktok_{open_id[:8]}"
        avatar_url = user_info.get("avatar_url")
        follower_count = int(user_info.get("follower_count") or 0)
        token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        async with get_async_session() as session:
            existing = (
                await session.execute(
                    select(ConnectedAccount).where(
                        ConnectedAccount.user_id == user_id,
                        ConnectedAccount.platform == "tiktok",
                        ConnectedAccount.platform_account_id == open_id,
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                account = ConnectedAccount(
                    user_id=user_id,
                    platform="tiktok",
                    platform_account_id=open_id,
                    handle=handle,
                    display_name=handle,
                    avatar_url=avatar_url,
                    follower_count=follower_count,
                    token_expires_at=token_expires_at,
                )
                account.access_token = access_token
                if refresh_token:
                    account.refresh_token = refresh_token
                session.add(account)
            else:
                existing.access_token = access_token
                if refresh_token:
                    existing.refresh_token = refresh_token
                existing.handle = handle
                existing.display_name = handle
                existing.avatar_url = avatar_url
                existing.follower_count = follower_count
                existing.token_expires_at = token_expires_at
                existing.is_active = True

            await session.commit()

        logger.info("tiktok_auth.connected", user_id=user_id, open_id=open_id[:8])
        return RedirectResponse(
            url=f"{frontend_base}/dashboard/distribution?tiktok_connected=true"
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("tiktok_auth.callback_failed", user_id=user_id, error=str(exc))
        return RedirectResponse(url=error_redirect)


@router.delete("/auth/tiktok/{account_id}")
@limiter.limit(Tier.WRITE)
async def disconnect_tiktok(
    request: Request,
    account_id: int,
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a TikTok ConnectedAccount row."""
    async with get_async_session() as session:
        account = (
            await session.execute(
                select(ConnectedAccount).where(
                    ConnectedAccount.id == account_id,
                    ConnectedAccount.user_id == current_user.id,
                    ConnectedAccount.platform == "tiktok",
                )
            )
        ).scalar_one_or_none()

        if not account:
            raise HTTPException(status_code=404, detail="TikTok account not found")

        account.is_active = False
        await session.commit()

    logger.info("tiktok_auth.disconnected", user_id=current_user.id, account_id=account_id)
    return {"ok": True}
