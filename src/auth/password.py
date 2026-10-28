"""Password hashing utilities.

Uses the ``bcrypt`` library directly instead of ``passlib``: passlib is
unmaintained and incompatible with bcrypt >=4.1 (its self-test probe passes
a >72-byte secret and modern bcrypt raises rather than silently truncating).

bcrypt itself has a hard 72-byte limit. We pre-truncate so callers don't
need to think about it, matching the previous behaviour.
"""
from __future__ import annotations

import bcrypt

# Default cost factor — bumped from the bcrypt default (12) keeps roughly
# 250–500 ms per hash on modern hardware. Matches what passlib used.
_ROUNDS = 12
_MAX_BYTES = 72  # bcrypt's hard limit on input length


def _truncate(password: str) -> bytes:
    """Encode and clip a password to bcrypt's 72-byte limit."""
    return password.encode("utf-8")[:_MAX_BYTES]


def hash_password(password: str) -> str:
    """Hash a password using bcrypt. Returns a string suitable for DB storage."""
    hashed = bcrypt.hashpw(_truncate(password), bcrypt.gensalt(rounds=_ROUNDS))
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(_truncate(plain_password), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False
