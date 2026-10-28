"""Outbound notifications wrapper (Week 8 — Cloud renders + queue UI).

Lightweight, provider-pluggable email sender. Two real backends
(``smtp`` + ``resend``) and a ``console`` backend that just logs the
rendered email body so dev / CI / tests don't need credentials.

Design rules:

* **Default to console.** Setting ``EMAIL_PROVIDER`` is opt-in; the
  app boots and renders happily without any mail config. Logging the
  payload at ``info`` makes the "did we attempt to send the email"
  signal show up in `dev.sh` output without an SMTP round trip.
* **Fail-open everywhere.** A failed mail send NEVER propagates back
  into the render pipeline — the render already shipped; missing
  the notification is a degradation, not a failure. Errors are
  logged at ``warning`` so we can grep for `notifications.send_failed`
  in prod.
* **User-respecting.** :func:`notify_render_complete` /
  :func:`notify_render_failed` check the user's
  ``notify_on_render_done`` preference (defaulting to True) before
  the provider is even resolved. No "did you mean to suppress this?"
  — if the user opted out, we don't send.
* **Per-user throttling.** Free-plan users frequently queue several
  short renders back-to-back; spamming their inbox is the fastest
  way to get marked as spam. A simple per-process LRU enforces "at
  most one render notification per 1 hour per user" without needing
  a Redis quota.
* **No template engine.** The email bodies are small, fixed-shape
  strings — Jinja / Mako would be overkill. Keep them inline so the
  format is grep-able and easy to update.
"""
from __future__ import annotations

import os
import smtplib
import time
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Literal, Optional

import structlog

from src.database.connection import get_session
from src.database.models import User

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Provider config
# ---------------------------------------------------------------------------

EmailProvider = Literal["console", "smtp", "resend"]


def _get_provider() -> EmailProvider:
    """Resolve the active provider from env, defaulting to ``console``.

    Unknown values fall back to ``console`` (logged once) so a typo
    never silently drops mail in production.
    """
    raw = (os.environ.get("EMAIL_PROVIDER") or "console").strip().lower()
    if raw in ("console", "smtp", "resend"):
        return raw  # type: ignore[return-value]
    logger.warning("notifications.unknown_provider", provider=raw)
    return "console"


def _get_from_address() -> str:
    """Sender address. Default value is intentionally obvious so any
    accidental real send from a misconfigured environment shows up
    in the recipient's UI as clearly non-production."""
    return os.environ.get("EMAIL_FROM") or "noreply@viewmagnet.local"


# ---------------------------------------------------------------------------
# Per-process throttle (free-tier hygiene)
# ---------------------------------------------------------------------------

# Maps user_id -> unix-ts of last send. 1h throttle is intentionally
# coarse — if a worker restarts we may double-send once, which is
# preferable to maintaining a Redis sorted set for one notification
# type. Production-grade throttling would move this to Redis with a
# per-user EXPIRE, but it's not the blocker today.
_THROTTLE_SECONDS = 60 * 60
_last_sent: dict[int, float] = {}


def _is_throttled(user_id: int) -> bool:
    """True iff we sent the user a render notification in the last hour."""
    last = _last_sent.get(user_id)
    if last is None:
        return False
    return (time.time() - last) < _THROTTLE_SECONDS


def _record_send(user_id: int) -> None:
    _last_sent[user_id] = time.time()


# ---------------------------------------------------------------------------
# Email shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Email:
    """A simple plaintext + HTML email payload. Providers translate
    this to whatever shape they require."""

    to: str
    subject: str
    text: str
    html: str


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


def _send_console(email: Email) -> bool:
    """Log the rendered email so dev / tests can verify content."""
    logger.info(
        "notifications.console_send",
        to=email.to,
        subject=email.subject,
        text_preview=email.text[:200],
    )
    return True


def _send_smtp(email: Email) -> bool:
    """Send via SMTP using ``SMTP_HOST`` / ``SMTP_PORT`` / ``SMTP_USER`` /
    ``SMTP_PASSWORD``. Connects with STARTTLS when possible."""
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT") or 587)
    user = os.environ.get("SMTP_USER")
    pw = os.environ.get("SMTP_PASSWORD")
    if not host:
        logger.warning("notifications.smtp_no_host")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = email.subject
    msg["From"] = _get_from_address()
    msg["To"] = email.to
    msg.attach(MIMEText(email.text, "plain"))
    msg.attach(MIMEText(email.html, "html"))

    try:
        with smtplib.SMTP(host, port, timeout=10) as conn:
            conn.ehlo()
            try:
                conn.starttls()
                conn.ehlo()
            except smtplib.SMTPException:
                # Some servers don't support STARTTLS (or it's already TLS).
                # Continue with the plain connection rather than failing the
                # whole send.
                pass
            if user and pw:
                conn.login(user, pw)
            conn.sendmail(_get_from_address(), [email.to], msg.as_string())
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("notifications.smtp_send_failed", to=email.to, error=str(exc))
        return False


def _send_resend(email: Email) -> bool:
    """Send via Resend's REST API. Requires ``RESEND_API_KEY``."""
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        logger.warning("notifications.resend_no_key")
        return False
    try:
        import httpx

        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "from": _get_from_address(),
                "to": [email.to],
                "subject": email.subject,
                "text": email.text,
                "html": email.html,
            },
            timeout=10.0,
        )
        if resp.status_code >= 400:
            logger.warning(
                "notifications.resend_send_failed",
                to=email.to,
                status=resp.status_code,
                body=resp.text[:200],
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("notifications.resend_send_failed", to=email.to, error=str(exc))
        return False


def _dispatch(email: Email) -> bool:
    """Route to the active provider; fail-open on errors."""
    provider = _get_provider()
    try:
        if provider == "smtp":
            return _send_smtp(email)
        if provider == "resend":
            return _send_resend(email)
        return _send_console(email)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "notifications.send_failed",
            provider=provider,
            to=email.to,
            error=str(exc),
        )
        return False


def send_email(to: str, subject: str, text: str, html: str) -> bool:
    """Send a one-off transactional email via the configured provider.

    Public, provider-agnostic entry point used by auth flows (verification,
    password reset) — distinct from the render-notification helpers below,
    which carry their own throttling + opt-out logic. This function does NOT
    throttle: callers are responsible for rate-limiting (the auth routes are
    already behind the shared limiter).

    Returns True on a successful send (or a console-logged send in dev).
    Never raises — a mail failure must not break signup/reset.
    """
    return _dispatch(Email(to=to, subject=subject, text=text, html=html))


# ---------------------------------------------------------------------------
# War-room webhook delivery (2.2) — Slack / Discord incoming webhooks
# ---------------------------------------------------------------------------


def send_webhook(url: str, text: str) -> bool:
    """POST a plain-text message to a Slack or Discord incoming webhook.

    Both accept a simple JSON body; the field name differs (Slack ``text``,
    Discord ``content``), so we pick by host. Fail-open — a broken webhook must
    never break the alert pipeline. Returns True on a 2xx response."""
    if not url:
        return False
    try:
        import httpx

        host = url.split("/")[2].lower() if "//" in url else url.lower()
        is_discord = "discord.com" in host or "discordapp.com" in host
        payload = {"content": text[:1900]} if is_discord else {"text": text}
        resp = httpx.post(url, json=payload, timeout=10.0)
        if resp.status_code >= 300:
            logger.warning("notifications.webhook_failed", host=host,
                           status=resp.status_code, body=resp.text[:200])
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("notifications.webhook_failed", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# User-preference lookup
# ---------------------------------------------------------------------------


def _user_wants_notifications(
    user_id: int,
) -> Optional[tuple[str, str, str]]:
    """Return ``(email, display_name, plan)`` if the user has opted in, else None.

    The ``plan`` field is surfaced so the throttle logic can let Pro
    and Enterprise users receive every render notification without
    the 1h coarse gate that hides cheap dev SMTP costs on free.

    Reads the columns via ``getattr`` because older deployments may
    not have the ``notify_on_render_done`` boolean yet (a follow-on
    migration adds it). When the column is missing we default to
    True — better to notify once than to silently never send.
    """
    with get_session() as db:
        user = db.get(User, user_id)
        if user is None or not user.email:
            return None
        opted_in = getattr(user, "notify_on_render_done", True)
        if opted_in is False:
            return None
        display = (
            getattr(user, "name", None)
            or getattr(user, "full_name", None)
            or user.email
        )
        plan = (getattr(user, "plan", None) or "free").lower()
        return (user.email, display, plan)


# ---------------------------------------------------------------------------
# Public API used by the render jobs
# ---------------------------------------------------------------------------

RenderKind = Literal["session", "project"]


def notify_render_complete(
    user_id: int,
    kind: RenderKind,
    render_id: int,
    download_url: Optional[str],
) -> None:
    """Send the "your render is ready" email. Never raises."""
    try:
        contact = _user_wants_notifications(user_id)
        if contact is None:
            return
        email_addr, display_name, plan = contact
        # Paid plans bypass the per-user hourly throttle. The throttle
        # exists to bound free-tier email cost; paying users explicitly
        # opted into render notifications and would call it broken if
        # they got 1 email per hour while running back-to-back renders.
        if plan == "free" and _is_throttled(user_id):
            logger.info(
                "notifications.render_complete.throttled",
                user_id=user_id,
                kind=kind,
                render_id=render_id,
            )
            return
        label = "project" if kind == "project" else "clip"
        link = download_url or "(no download URL — open the editor)"
        subject = f"Your {label} render is ready"
        text = (
            f"Hi {display_name},\n\n"
            f"Your {label} (#{render_id}) just finished rendering.\n\n"
            f"Download: {link}\n\n"
            "You can also open the Renders page in the dashboard to manage all "
            "of your renders in one place.\n\n"
            "— ViewMagnet\n"
        )
        html = (
            f"<p>Hi {display_name},</p>"
            f"<p>Your {label} (#{render_id}) just finished rendering.</p>"
            f'<p><a href="{link}">Download the output</a></p>'
            "<p>Or open the <strong>Renders</strong> page in your dashboard to "
            "manage all of your renders in one place.</p>"
            "<p>— ViewMagnet</p>"
        )
        if _dispatch(Email(to=email_addr, subject=subject, text=text, html=html)):
            _record_send(user_id)
            logger.info(
                "notifications.render_complete.sent",
                user_id=user_id,
                kind=kind,
                render_id=render_id,
            )
            # Structured telemetry (Week 8 Day 6.1): captures every
            # successful send so we can tie open-rate back to the
            # render funnel. ``outcome="success"`` distinguishes from
            # the failure-mail path below.
            try:
                from src.queue.telemetry import record_render_email_sent
                record_render_email_sent(
                    user_id=user_id,
                    render_kind=kind,
                    render_id=render_id,
                    outcome="success",
                    email=email_addr,
                )
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "notifications.render_complete.failed",
            user_id=user_id,
            kind=kind,
            render_id=render_id,
            error=str(exc),
        )


def notify_render_failed(
    user_id: int,
    kind: RenderKind,
    render_id: int,
    error_message: str,
) -> None:
    """Send the "your render failed" email. Never raises.

    Failure notifications bypass the 1h throttle — a creator hitting
    a wall needs to know immediately so they can re-run, not in an
    hour. The dispatch path is still fail-open so a broken mail
    provider doesn't surface as a render error.
    """
    try:
        contact = _user_wants_notifications(user_id)
        if contact is None:
            return
        email_addr, display_name, _plan = contact
        label = "project" if kind == "project" else "clip"
        snippet = (error_message or "").strip()[:240] or "unknown error"
        subject = f"Your {label} render failed"
        text = (
            f"Hi {display_name},\n\n"
            f"Your {label} (#{render_id}) render didn't complete.\n\n"
            f"Reason: {snippet}\n\n"
            "Open the editor to try again or reach out to support if this keeps "
            "happening.\n\n"
            "— ViewMagnet\n"
        )
        html = (
            f"<p>Hi {display_name},</p>"
            f"<p>Your {label} (#{render_id}) render didn't complete.</p>"
            f"<p><strong>Reason:</strong> {snippet}</p>"
            "<p>Open the editor to try again or reach out to support if this "
            "keeps happening.</p>"
            "<p>— ViewMagnet</p>"
        )
        if _dispatch(Email(to=email_addr, subject=subject, text=text, html=html)):
            logger.info(
                "notifications.render_failed.sent",
                user_id=user_id,
                kind=kind,
                render_id=render_id,
            )
            try:
                from src.queue.telemetry import record_render_email_sent
                record_render_email_sent(
                    user_id=user_id,
                    render_kind=kind,
                    render_id=render_id,
                    outcome="failure",
                    email=email_addr,
                )
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "notifications.render_failed.send_failed",
            user_id=user_id,
            kind=kind,
            render_id=render_id,
            error=str(exc),
        )


# Exported so tests can reset between runs.
def _reset_throttle() -> None:
    _last_sent.clear()
