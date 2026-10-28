"""JWT token creation and verification with revocation support.

Every token embeds a ``ver`` (token_version) claim. The version must match the
current ``User.token_version`` for the token to be accepted. Bumping
``User.token_version`` (e.g. on logout, password change, account compromise)
invalidates every outstanding access + refresh token for that user.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import jwt

from src.config import get_settings


def create_access_token(
    user_id: int,
    email: str,
    token_version: int = 0,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a JWT access token."""
    settings = get_settings()
    
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "ver": token_version,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    
    if extra_claims:
        payload.update(extra_claims)
    
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: int, token_version: int = 0) -> str:
    """Create a JWT refresh token."""
    settings = get_settings()
    
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "ver": token_version,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days),
    }
    
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_token(token: str, token_type: str = "access") -> Optional[Dict[str, Any]]:
    """Decode and verify a JWT token's signature and type.
    
    Note: this does NOT validate ``ver`` against the live user. That check
    happens in :func:`src.auth.dependencies.get_current_user` so the JWT module
    stays DB-free.
    """
    settings = get_settings()
    
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        
        if payload.get("type") != token_type:
            return None
        
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
