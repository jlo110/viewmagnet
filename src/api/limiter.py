"""Shared rate limiter used by all API routers and the auth router.

Single ``Limiter`` instance per process. Configured with Redis storage when
``REDIS_URL`` is set (so limits apply across all worker processes); falls back
to in-memory storage in development.

Use the ``Tier`` enum + ``Tier.limit("LLM_HEAVY")`` helper to apply consistent
rate limits across the API:

    @app.post("/titles/generate")
    @limiter.limit(Tier.LLM_HEAVY)
    async def generate_titles(request: Request, ...): ...
"""
from __future__ import annotations

import os
from enum import Enum

from slowapi import Limiter
from slowapi.util import get_remote_address

from src.config import get_settings

_settings = get_settings()


def _key_func(request) -> str:
    """Rate-limit key: prefer JWT user id, else remote address.

    Uses the user attached to ``request.state`` if a dependency populated it,
    otherwise falls back to client IP.
    """
    user = getattr(request.state, "current_user", None)
    if user is not None and getattr(user, "id", None) is not None:
        return f"user:{user.id}"
    return get_remote_address(request)


_storage_uri = _settings.redis_url if _settings.redis_url else "memory://"

_testing = bool(os.environ.get("TESTING"))

limiter = Limiter(
    key_func=_key_func,
    storage_uri=_storage_uri,
    default_limits=[f"{_settings.rate_limit_requests}/{_settings.rate_limit_period}seconds"],
    enabled=not _testing,
)


class Tier(str, Enum):
    """Rate-limit tiers applied per route class.

    Pass directly to ``@limiter.limit(...)`` since ``Tier`` inherits from str.
    """
    LLM_HEAVY = "5/minute"     # LLM-driven generation (scripts, titles, hooks, descriptions)
    MEDIA_HEAVY = "3/minute"   # ffmpeg / yt-dlp / whisper (shorts, loop, pacing, captions)
    READ = "60/minute"         # Cheap read endpoints (lists, history)
    WRITE = "30/minute"        # Standard write endpoints (settings, account updates)
    AUTH = "5/minute"          # Login, signup, refresh
