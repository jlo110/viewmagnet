"""Instagram OAuth via Facebook Login (Business Login API).

Uses the standard Facebook/Instagram Graph API OAuth 2.0 flow:
  https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login

Required env vars:
  INSTAGRAM_APP_ID       — from Meta Developer portal app
  INSTAGRAM_APP_SECRET   — from Meta Developer portal app

Scopes requested: instagram_business_basic, instagram_business_manage_messages,
instagram_business_content_publish (for future publishing).

On success the callback writes a ``ConnectedAccount`` row (platform=instagram)
with encrypted tokens and redirects the user back to the Distribution Hub.
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
router = APIRouter(tags=["instagram-oauth"])

_STATE_TTL = 600
_FB_AUTH_URL = "https://www.facebook.com/v20.0/dialog/oauth"
_FB_TOKEN_URL = "https://graph.facebook.com/v20.0/oauth/access_token"
_IG_ME_URL = "https://graph.instagram.com/v20.0/me"
_IG_SCOPES = (
    "instagram_business_basic,"
    "instagram_business_manage_messages,"
    "instagram_business_content_publish"
)


def _state_key(state: str) -> str:
    return f"oauth:instagram:state:{state}"


def _app_id() -> Optional[str]:
    return os.environ.get("INSTAGRAM_APP_ID")


def _app_secret() -> Optional[str]:
    return os.environ.get("INSTAGRAM_APP_SECRET")


def _is_configured() -> bool:
    return bool(_app_id() and _app_secret())


class InstagramAuthURL(BaseModel):
    auth_url: str
    state: str


@router.get("/auth/instagram", response_model=InstagramAuthURL)
@limiter.limit(Tier.AUTH)
async def start_instagram_auth(
    request: Request,
    current_user: User = Depends(get_current_user),
    redirect_uri: str = Query(
        default="",
        description="OAuth callback URL — defaults to <origin>/auth/instagram/callback",
    ),
):
    """Begin the Instagram Business Login OAuth flow.

    Returns ``auth_url`` the frontend should redirect the user to.
    """
    if not _is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Instagram OAuth is not configured. "
                "Set INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET."
            ),
        )

    if not redirect_uri:
        base = str(request.base_url).rstrip("/")
        redirect_uri = f"{base}/auth/instagram/callback"

    state = secrets.token_urlsafe(32)
    await cache_set_json(
        _state_key(state),
        {"user_id": current_user.id, "redirect_uri": redirect_uri},
        ttl=_STATE_TTL,
    )

    from urllib.parse import urlencode
    params = {
        "client_id": _app_id(),
        "redirect_uri": redirect_uri,
        "scope": _IG_SCOPES,
        "response_type": "code",
        "state": state,
    }
    auth_url = f"{_FB_AUTH_URL}?{urlencode(params)}"

    logger.info("instagram_auth.start", user_id=current_user.id)
    return InstagramAuthURL(auth_url=auth_url, state=state)


@router.get("/auth/instagram/callback")
async def instagram_callback(
    request: Request,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    error_description: Optional[str] = Query(default=None),
):
    """Handle Instagram / Meta OAuth callback.

    Exchanges the short-lived code for a long-lived token (60-day),
    fetches the Instagram Business account info, and upserts a
    ``ConnectedAccount`` row.
    """
    frontend_base = settings.frontend_url or "http://localhost:5173"
    error_redirect = f"{frontend_base}/dashboard/distribution?instagram_error=true"

    if error or not code or not state:
        logger.warning(
            "instagram_auth.callback_error",
            error=error,
            desc=error_description,
        )
        return RedirectResponse(url=error_redirect)

    cached = await cache_get_json(_state_key(state))
    if not cached:
        logger.warning("instagram_auth.state_expired", state=state[:8])
        return RedirectResponse(url=error_redirect)

    await cache_delete(_state_key(state))
    user_id: int = cached["user_id"]
    redirect_uri: str = cached["redirect_uri"]

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            # Exchange code for short-lived token.
            token_resp = await client.get(
                _FB_TOKEN_URL,
                params={
                    "client_id": _app_id(),
                    "client_secret": _app_secret(),
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

        short_token: str = token_data["access_token"]

        # Exchange short-lived token for long-lived token (60 days).
        async with httpx.AsyncClient(timeout=15) as client:
            ll_resp = await client.get(
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": _app_secret(),
                    "access_token": short_token,
                },
            )
            ll_resp.raise_for_status()
            ll_data = ll_resp.json()

        long_token: str = ll_data.get("access_token", short_token)
        expires_in: int = ll_data.get("expires_in", 5_184_000)  # 60 days

        # Fetch IG user profile.
        async with httpx.AsyncClient(timeout=15) as client:
            me_resp = await client.get(
                _IG_ME_URL,
                params={
                    "fields": "id,username,name,profile_picture_url,followers_count",
                    "access_token": long_token,
                },
            )
            me_resp.raise_for_status()
            me = me_resp.json()

        ig_user_id: str = me["id"]
        handle: str = me.get("username") or f"ig_{ig_user_id[:8]}"
        display_name: str = me.get("name") or handle
        avatar_url: Optional[str] = me.get("profile_picture_url")
        follower_count: int = int(me.get("followers_count") or 0)
        token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        async with get_async_session() as session:
            existing = (
                await session.execute(
                    select(ConnectedAccount).where(
                        ConnectedAccount.user_id == user_id,
                        ConnectedAccount.platform == "instagram",
                        ConnectedAccount.platform_account_id == ig_user_id,
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                account = ConnectedAccount(
                    user_id=user_id,
                    platform="instagram",
                    platform_account_id=ig_user_id,
                    handle=handle,
                    display_name=display_name,
                    avatar_url=avatar_url,
                    follower_count=follower_count,
                    token_expires_at=token_expires_at,
                )
                account.access_token = long_token
                session.add(account)
            else:
                existing.access_token = long_token
                existing.handle = handle
                existing.display_name = display_name
                existing.avatar_url = avatar_url
                existing.follower_count = follower_count
                existing.token_expires_at = token_expires_at
                existing.is_active = True

            await session.commit()

        logger.info("instagram_auth.connected", user_id=user_id, ig_id=ig_user_id[:8])
        return RedirectResponse(
            url=f"{frontend_base}/dashboard/distribution?instagram_connected=true"
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("instagram_auth.callback_failed", user_id=user_id, error=str(exc))
        return RedirectResponse(url=error_redirect)


@router.delete("/auth/instagram/{account_id}")
@limiter.limit(Tier.WRITE)
async def disconnect_instagram(
    request: Request,
    account_id: int,
    current_user: User = Depends(get_current_user),
):
    """Soft-delete an Instagram ConnectedAccount row."""
    async with get_async_session() as session:
        account = (
            await session.execute(
                select(ConnectedAccount).where(
                    ConnectedAccount.id == account_id,
                    ConnectedAccount.user_id == current_user.id,
                    ConnectedAccount.platform == "instagram",
                )
            )
        ).scalar_one_or_none()

        if not account:
            raise HTTPException(status_code=404, detail="Instagram account not found")

        account.is_active = False
        await session.commit()

    logger.info("instagram_auth.disconnected", user_id=current_user.id, account_id=account_id)
    return {"ok": True}
