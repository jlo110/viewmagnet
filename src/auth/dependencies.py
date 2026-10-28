"""FastAPI authentication dependencies.

Provides:
- ``get_current_user``: required-auth dependency that 401s on missing/invalid tokens
- ``get_current_user_optional``: never-throws variant that returns ``None`` instead

Both dependencies accept TWO kinds of bearer credential:

1. **JWT access tokens** issued by ``/auth/login`` / ``/auth/refresh``. These
   carry a ``ver`` claim that must match the user's stored
   ``token_version``; bumping the version invalidates every outstanding JWT
   for that user (logout, password change, etc.).
2. **Personal Access Tokens (PATs)** issued by ``/auth/tokens`` and used by
   the ``viewmagnet-mcp`` server. Format: ``vm_pat_<8 hex>_<32 char secret>``.
   The credential is recognized by its ``vm_pat_`` prefix; we look up the
   row by prefix (indexed) and verify ``sha256(secret)`` matches
   ``token_hash``. Revoked or expired PATs 401.

DEV_MODE
--------
When ``DEV_MODE=true`` and ``ENVIRONMENT != production`` a per-process random
mock token is generated at import time and printed once. Pass it as a Bearer
token to act as a built-in demo user without going through signup/login.

Hard-gating: if ``DEV_MODE=true`` in production the process refuses to start
(see :func:`src.config.Settings.validate_required_in_production`).
"""
import hashlib
import secrets
from datetime import datetime
from typing import Optional

import structlog
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.auth.jwt import verify_token
from src.config import get_settings
from src.database.connection import get_session
from src.database.models import PersonalAccessToken, User

load_dotenv()
logger = structlog.get_logger(__name__)

security = HTTPBearer(auto_error=False)

# DEV MODE configuration -------------------------------------------------------

_settings = get_settings()
DEV_MODE = _settings.dev_mode and not _settings.is_production

# Hard fail-fast if DEV_MODE was accidentally enabled in production. This is a
# belt-and-braces check on top of the Settings validator.
if _settings.dev_mode and _settings.is_production:
    raise RuntimeError(
        "DEV_MODE must NOT be true in production. "
        "DEV_MODE bypasses authentication and is for local development only."
    )

if DEV_MODE:
    # Per-process random secret so a leaked DEV_MODE token from one machine
    # cannot be reused against another.
    MOCK_TOKEN: Optional[str] = secrets.token_urlsafe(32)
    logger.warning(
        "auth.dev_mode_enabled",
        message="DEV_MODE active: pass this token to bypass auth as a demo user",
        mock_token=MOCK_TOKEN,
    )
else:
    MOCK_TOKEN = None


def _get_mock_user() -> User:
    """Build the in-memory demo user used by DEV_MODE flows."""
    mock = User()
    mock.id = 1
    mock.email = "demo@viewmagnet.io"
    mock.name = "Demo User"
    mock.plan = "pro"
    mock.avatar_url = None
    mock.token_version = 0
    return mock


def _verify_token_version(token_ver: Optional[int], user: User) -> bool:
    """Token-version match check (allows missing claim for legacy tokens)."""
    if token_ver is None:
        # Legacy token issued before versioning -- allow but log so we can spot
        # when callers are still presenting these.
        logger.debug("auth.legacy_token", user_id=user.id)
        return True
    return token_ver == getattr(user, "token_version", 0)


# Personal Access Tokens carry this literal prefix so the auth dependency
# can branch without first trying (and failing) JWT decode on every
# request. Layout: ``vm_pat_<8 hex prefix>_<32 char secret>``.
PAT_PREFIX_LITERAL = "vm_pat_"


def _hash_pat_secret(secret: str) -> str:
    """sha256 of the secret half of a PAT (hex-encoded, 64 chars).

    Kept identical to the hashing used in
    :mod:`src.api.routers.api_tokens` at creation time so the
    auth path can match by hash without importing that router.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _resolve_pat(credential: str) -> Optional[User]:
    """If ``credential`` looks like a PAT, look it up and return the user.

    Returns ``None`` for anything that doesn't parse as a PAT (so callers
    can fall through to the JWT path), and for PATs that are invalid /
    revoked / expired / unknown. We deliberately do NOT raise here —
    distinguishing "wrong shape" from "right shape but invalid" lets the
    JWT branch handle the former silently while the latter still 401s
    via the caller.

    Side effect: on a successful match we bump ``last_used_at`` so the
    dashboard can show "last seen N minutes ago".
    """
    # Expected layout: ``vm_pat_<8 hex>_<32 char secret>`` ⇒ 3 underscore parts
    parts = credential.split("_", 3)
    if len(parts) != 4 or f"{parts[0]}_{parts[1]}_" != PAT_PREFIX_LITERAL:
        # Caller can't tell us this from a JWT just by shape — defer.
        return None
    # parts now = ["vm", "pat", "<prefix-hex>", "<secret>"]
    prefix = f"{parts[0]}_{parts[1]}_{parts[2]}"
    secret = parts[3]
    if not prefix or not secret:
        return None

    secret_hash = _hash_pat_secret(secret)
    now = datetime.utcnow()

    with get_session() as session:
        row = (
            session.query(PersonalAccessToken)
            .filter(
                PersonalAccessToken.prefix == prefix,
                PersonalAccessToken.token_hash == secret_hash,
            )
            .first()
        )
        if not row:
            return None
        if row.revoked_at is not None:
            return None
        if row.expires_at is not None and row.expires_at <= now:
            return None

        user = session.query(User).filter(User.id == row.user_id).first()
        if not user:
            return None

        # Best-effort touch; a write failure here must never block the
        # actual request, so we swallow exceptions after logging. The
        # subsequent ``refresh`` is necessary because SQLAlchemy expires
        # every instance attached to the session on commit by default
        # — without it the User object would lazy-load (and fail) on
        # the caller's first attribute access after we expunge.
        try:
            row.last_used_at = now
            session.commit()
            session.refresh(user)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "auth.pat_last_used_update_failed",
                prefix=prefix,
                error=str(exc),
            )
            session.rollback()

        session.expunge(user)
        return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """Required-auth dependency. Raises HTTP 401 on missing/invalid tokens.

    Accepts JWTs **or** Personal Access Tokens (``vm_pat_...``). The
    branch is decided by the literal credential prefix, so the JWT
    path stays exactly as fast as before for the common case.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    credential = credentials.credentials

    # DEV MODE: accept the per-process mock token.
    if DEV_MODE and MOCK_TOKEN and credential == MOCK_TOKEN:
        return _get_mock_user()

    # Personal Access Token path (MCP server / scripts).
    if credential.startswith(PAT_PREFIX_LITERAL):
        user = _resolve_pat(credential)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid, revoked, or expired API token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    # JWT path (browser / dashboard).
    payload = verify_token(credential, token_type="access")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = int(payload.get("sub"))
    token_ver = payload.get("ver")

    with get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not _verify_token_version(token_ver, user):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

        session.expunge(user)
        return user


async def get_current_user_ws(token: Optional[str]) -> Optional[User]:
    """WebSocket auth helper (Week 8).

    Browsers can't set an ``Authorization`` header on a ``new
    WebSocket()`` handshake, so the WS endpoints accept the access
    token via the ``?token=`` query string instead. This helper
    returns the matching :class:`User` or ``None`` so the endpoint
    can ``ws.close(code=1008)`` without leaking exception details.

    Mirrors :func:`get_current_user`'s validation rules (DEV_MODE
    bypass, token version check) so the WS auth surface is the same
    as HTTP — no separate token type, no separate revocation
    semantics.
    """
    if not token:
        return None

    if DEV_MODE and MOCK_TOKEN and token == MOCK_TOKEN:
        return _get_mock_user()

    payload = verify_token(token, token_type="access")
    if not payload:
        return None

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    token_ver = payload.get("ver")

    with get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()
        if user is None:
            return None
        if not _verify_token_version(token_ver, user):
            return None
        session.expunge(user)
        return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[User]:
    """Optional-auth dependency. Returns ``None`` for missing/invalid tokens.

    Same JWT-or-PAT branching as :func:`get_current_user`, but returns
    ``None`` instead of raising — used by endpoints that show a
    richer response when the caller is authenticated but still work
    anonymously.
    """
    if not credentials:
        return None

    credential = credentials.credentials

    if DEV_MODE and MOCK_TOKEN and credential == MOCK_TOKEN:
        return _get_mock_user()

    if credential.startswith(PAT_PREFIX_LITERAL):
        return _resolve_pat(credential)

    payload = verify_token(credential, token_type="access")
    if not payload:
        return None

    user_id = int(payload.get("sub"))
    token_ver = payload.get("ver")

    with get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()
        if user:
            if not _verify_token_version(token_ver, user):
                return None
            session.expunge(user)
        return user
