"""Transactional auth emails: email verification + password reset.

Thin layer over :func:`src.features.notifications.send_email`. Builds the
verification + reset links from ``FRONTEND_URL`` and the single-use token,
renders a small plaintext + HTML body, and dispatches via whatever
``EMAIL_PROVIDER`` is configured (``console`` in dev, ``smtp`` in prod).

Fail-open: a mail failure is logged and swallowed so signup / reset never
500s because the mailer is down. The caller decides what user-facing
message to return.
"""
from __future__ import annotations

import os
from urllib.parse import quote

import structlog

from src.features.notifications import send_email

logger = structlog.get_logger(__name__)


def _frontend_url() -> str:
    return (os.getenv("FRONTEND_URL") or "http://localhost:3000").rstrip("/")


def _wrap_html(heading: str, body_html: str, button_label: str, link: str) -> str:
    """Minimal branded HTML shell shared by both emails."""
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:480px;margin:0 auto;color:#0f172a;">'
        f'<h2 style="color:#0891b2;margin-bottom:8px;">{heading}</h2>'
        f"{body_html}"
        f'<p style="margin:24px 0;">'
        f'<a href="{link}" style="background:#06b6d4;color:#0a0a0a;text-decoration:none;'
        'padding:12px 20px;border-radius:8px;font-weight:600;display:inline-block;">'
        f"{button_label}</a></p>"
        '<p style="color:#64748b;font-size:12px;">If the button doesn\'t work, copy and '
        f'paste this link into your browser:<br><span style="word-break:break-all;">{link}</span></p>'
        '<p style="color:#64748b;font-size:12px;">— ViewMagnet</p>'
        "</div>"
    )


def send_verification_email(to: str, token: str, display_name: str | None = None) -> bool:
    """Send the "confirm your email" message with a verification link."""
    name = display_name or "there"
    link = f"{_frontend_url()}/verify-email?token={quote(token)}"
    subject = "Verify your ViewMagnet email"
    text = (
        f"Hi {name},\n\n"
        "Welcome to ViewMagnet! Please confirm your email address by opening "
        f"this link:\n\n{link}\n\n"
        "If you didn't create a ViewMagnet account, you can ignore this email.\n\n"
        "— ViewMagnet\n"
    )
    html = _wrap_html(
        "Confirm your email",
        f"<p>Hi {name},</p><p>Welcome to ViewMagnet! Confirm your email address "
        "to unlock everything on your account.</p>",
        "Verify email",
        link,
    )
    ok = send_email(to=to, subject=subject, text=text, html=html)
    logger.info("auth.email.verification_sent", to=to, ok=ok)
    return ok


def send_password_reset_email(to: str, token: str, display_name: str | None = None) -> bool:
    """Send the password-reset message with a single-use reset link."""
    name = display_name or "there"
    link = f"{_frontend_url()}/reset-password?token={quote(token)}"
    subject = "Reset your ViewMagnet password"
    text = (
        f"Hi {name},\n\n"
        "We received a request to reset your ViewMagnet password. Open this "
        f"link to choose a new one (it expires in 1 hour):\n\n{link}\n\n"
        "If you didn't request this, you can safely ignore this email — your "
        "password won't change.\n\n"
        "— ViewMagnet\n"
    )
    html = _wrap_html(
        "Reset your password",
        f"<p>Hi {name},</p><p>We received a request to reset your password. "
        "This link expires in 1 hour.</p>",
        "Reset password",
        link,
    )
    ok = send_email(to=to, subject=subject, text=text, html=html)
    logger.info("auth.email.password_reset_sent", to=to, ok=ok)
    return ok
