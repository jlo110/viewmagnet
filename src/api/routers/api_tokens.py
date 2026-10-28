"""Personal Access Token (PAT) CRUD endpoints.

These power both the dashboard's `/settings/tokens` page and the
``viewmagnet-mcp`` MCP server installer. A PAT lets an agent (or any
script) call the API on the user's behalf without ever holding their
password — exactly the auth model the Vugola MCP server uses.

Token format
------------
Issued tokens look like ``vm_pat_<8 hex prefix>_<32 char secret>``.
Only the prefix is searchable; the secret half is sha256-hashed and
discarded after creation. The plaintext is shown to the user **once**
in the create response and never reconstructable thereafter.

Routes
------
``POST   /auth/tokens``      — create a new PAT (rate-limited; returns plaintext once)
``GET    /auth/tokens``      — list my PATs (metadata only, never the secret)
``DELETE /auth/tokens/{id}`` — revoke (soft-delete; row stays for audit)

Auth on these routes deliberately uses :func:`get_current_user`, which
accepts BOTH JWTs and PATs. A PAT-authenticated request can therefore
list and revoke its own family of tokens — useful for "rotate every
30 days" automation — without needing a JWT round-trip.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.audit import record_audit_event
from src.auth.dependencies import get_current_user
from src.database.connection import get_session
from src.database.models import PersonalAccessToken, User

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth/tokens", tags=["API Tokens"])


# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

TOKEN_PREFIX_LITERAL = "vm_pat"
# 8 hex chars after the literal; cheap to index and read.
TOKEN_PREFIX_HEX_LEN = 8
# Secret half: 32 hex chars = 128 bits of entropy (parity with the
# GitHub PAT format). We intentionally use hex rather than base64url
# so the resulting token contains no underscores; the auth path can
# then split on ``_`` with maxsplit=3 and be confident the secret
# half is exactly parts[3].
TOKEN_SECRET_HEX_LEN = 32
# Hard cap so the table can't be DoS'd by one user generating millions
# of PATs. Per-tier limits land alongside the subscription rework.
MAX_ACTIVE_TOKENS_PER_USER = 50

VALID_SCOPES = {"read", "write", "admin"}


def _hash_secret(secret: str) -> str:
    """sha256 of the secret half. Hex-encoded (64 chars)."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _generate_token() -> tuple[str, str, str]:
    """Return ``(plaintext, prefix, secret_hash)`` for a fresh PAT.

    Plaintext layout: ``vm_pat_<8 hex>_<32 hex secret>``.
    Only the plaintext is ever shown to the user; we keep the prefix
    (indexed) and the sha256 of the secret half (lookup key).
    """
    prefix_hex = secrets.token_hex(TOKEN_PREFIX_HEX_LEN // 2)  # 4 bytes → 8 hex
    prefix = f"{TOKEN_PREFIX_LITERAL}_{prefix_hex}"
    secret = secrets.token_hex(TOKEN_SECRET_HEX_LEN // 2)  # 16 bytes → 32 hex
    plaintext = f"{prefix}_{secret}"
    return plaintext, prefix, _hash_secret(secret)


def _normalize_scopes(scopes: Optional[list[str]]) -> list[str]:
    """Coerce input scopes into the validated, ordered, deduped form
    we store on the row. Empty list defaults to ``["read"]`` so a
    careless caller can't accidentally mint a no-op token."""
    if not scopes:
        return ["read"]
    cleaned: list[str] = []
    seen: set[str] = set()
    for scope in scopes:
        s = scope.strip().lower()
        if s and s in VALID_SCOPES and s not in seen:
            cleaned.append(s)
            seen.add(s)
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No valid scopes provided. Valid scopes: "
                + ", ".join(sorted(VALID_SCOPES))
            ),
        )
    return cleaned


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TokenCreateRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=120,
        description="Human-readable label, e.g. 'MacBook Claude'.",
    )
    scopes: Optional[list[str]] = Field(
        default=None,
        description=(
            "Subset of ['read', 'write', 'admin']. Defaults to ['read'] "
            "if omitted — the safest default for an agent that just "
            "needs to call analysis tools."
        ),
    )
    expires_in_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=365 * 5,
        description="Optional hard expiry in days. Omit for a never-expiring token.",
    )


class TokenMetadata(BaseModel):
    """Token row as returned by the list endpoint. Never includes the
    plaintext secret — that's only ever in the create response."""

    id: int
    name: str
    prefix: str  # full prefix e.g. "vm_pat_a1b2c3d4"
    scopes: list[str]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class TokenCreateResponse(TokenMetadata):
    """Sole place the plaintext token ever appears. The frontend
    surfaces this in a "copy now, you won't see it again" panel."""

    token: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _row_to_metadata(row: PersonalAccessToken) -> TokenMetadata:
    try:
        scopes = json.loads(row.scopes) if row.scopes else []
    except (TypeError, ValueError):
        scopes = []
    return TokenMetadata(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        scopes=scopes,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


@router.post(
    "",
    response_model=TokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(Tier.WRITE)
async def create_token(
    request: Request,
    body: TokenCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """Mint a new PAT and return the plaintext **once**."""
    scopes = _normalize_scopes(body.scopes)
    expires_at: Optional[datetime] = None
    if body.expires_in_days is not None:
        expires_at = datetime.utcnow() + timedelta(days=body.expires_in_days)

    plaintext, prefix, secret_hash = _generate_token()

    with get_session() as session:
        active_count = (
            session.query(PersonalAccessToken)
            .filter(
                PersonalAccessToken.user_id == current_user.id,
                PersonalAccessToken.revoked_at.is_(None),
            )
            .count()
        )
        if active_count >= MAX_ACTIVE_TOKENS_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"You already have {active_count} active tokens. "
                    f"Revoke unused ones before creating more "
                    f"(limit: {MAX_ACTIVE_TOKENS_PER_USER})."
                ),
            )

        row = PersonalAccessToken(
            user_id=current_user.id,
            name=body.name.strip(),
            prefix=prefix,
            token_hash=secret_hash,
            scopes=json.dumps(scopes),
            expires_at=expires_at,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        meta = _row_to_metadata(row)

    record_audit_event(
        "pat_created",
        user_id=current_user.id,
        request=request,
        details={"prefix": prefix, "scopes": scopes, "name": body.name},
    )
    logger.info(
        "auth.pat_created",
        user_id=current_user.id,
        prefix=prefix,
        scopes=scopes,
    )

    return TokenCreateResponse(token=plaintext, **meta.model_dump())


@router.get("", response_model=list[TokenMetadata])
@limiter.limit(Tier.READ)
async def list_tokens(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """List every PAT belonging to the caller, newest first.

    Revoked tokens are included so the UI can render the historical
    list with a "revoked" badge; the frontend filters them out by
    default. Never returns the plaintext secret.
    """
    with get_session() as session:
        rows = (
            session.query(PersonalAccessToken)
            .filter(PersonalAccessToken.user_id == current_user.id)
            .order_by(PersonalAccessToken.created_at.desc())
            .all()
        )
        return [_row_to_metadata(r) for r in rows]


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(Tier.WRITE)
async def revoke_token(
    request: Request,
    token_id: int,
    current_user: User = Depends(get_current_user),
):
    """Revoke a PAT. Idempotent — re-revoking a revoked token is a no-op."""
    with get_session() as session:
        row = (
            session.query(PersonalAccessToken)
            .filter(
                PersonalAccessToken.id == token_id,
                PersonalAccessToken.user_id == current_user.id,
            )
            .first()
        )
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token not found",
            )
        if row.revoked_at is None:
            row.revoked_at = datetime.utcnow()
            session.commit()
            record_audit_event(
                "pat_revoked",
                user_id=current_user.id,
                request=request,
                details={"prefix": row.prefix, "token_id": row.id},
            )
            logger.info(
                "auth.pat_revoked",
                user_id=current_user.id,
                prefix=row.prefix,
            )
    return None
