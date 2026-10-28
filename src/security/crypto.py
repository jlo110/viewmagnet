"""Fernet-based at-rest encryption for OAuth tokens and other secrets.

Uses ``ENCRYPTION_KEY`` from environment (a 32-byte url-safe base64 Fernet key).
In development a fixed dev key is used so the same DB row decrypts across
restarts; in production the key is required.

Public API:
    encrypt(plaintext: str | None) -> str | None
    decrypt(ciphertext: str | None) -> str | None
    mask_token(token: str | None) -> str   # for logs

Both functions are idempotent: ``encrypt(encrypt(x))`` raises (caller bug),
``decrypt(plaintext)`` returns the input unchanged when it cannot be decoded
(treated as already-decrypted legacy data).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

import structlog
from cryptography.fernet import Fernet, InvalidToken

from src.config import get_settings

logger = structlog.get_logger(__name__)

# Fixed development key so dev DBs remain readable across restarts.
# This MUST NOT match anything used in production.
_DEV_KEY = b"dev-encryption-key-not-prod-X9z1A0Sg2J5oTqf7HpN2W7QrUk3LmV8Y="

# Marker prefix for encrypted ciphertext. Legacy plaintext rows do not have it,
# so ``decrypt`` returns them as-is to allow gradual migration.
_PREFIX = "enc:"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.encryption_key
    if not key:
        if settings.is_production:
            raise RuntimeError(
                "ENCRYPTION_KEY is required in production. "
                "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        key = _DEV_KEY.decode()
        logger.warning(
            "encryption.using_dev_key",
            message="No ENCRYPTION_KEY set; using fixed development key (NOT SAFE FOR PRODUCTION)",
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a plaintext string. Returns ``None`` for ``None`` input."""
    if plaintext is None or plaintext == "":
        return plaintext
    if plaintext.startswith(_PREFIX):
        # Already encrypted -- return as-is so re-saving a loaded model does not
        # double-encrypt.
        return plaintext
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"{_PREFIX}{token}"


def decrypt(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a ciphertext produced by :func:`encrypt`.

    For backwards compatibility, values without the ``enc:`` prefix are
    returned unchanged (treated as legacy plaintext awaiting migration).
    """
    if ciphertext is None or ciphertext == "":
        return ciphertext
    if not ciphertext.startswith(_PREFIX):
        # Legacy plaintext row -- return as-is.
        return ciphertext
    payload = ciphertext[len(_PREFIX):]
    try:
        return _fernet().decrypt(payload.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("encryption.decrypt_failed", reason="invalid_token")
        return None


def mask_token(token: Optional[str]) -> str:
    """Return a log-safe masked representation of a token."""
    if not token:
        return "<empty>"
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


def scrub_tokens_processor(_, __, event_dict: dict) -> dict:
    """structlog processor that masks well-known sensitive keys in log events."""
    sensitive_keys = {
        "access_token", "refresh_token", "token", "password",
        "client_secret", "api_key", "secret",
    }
    for key in list(event_dict.keys()):
        if key.lower() in sensitive_keys and isinstance(event_dict[key], str):
            event_dict[key] = mask_token(event_dict[key])
    return event_dict
