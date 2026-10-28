"""WebSub (PubSubHubbub) push discovery for YouTube uploads (plan 7.5).

Polling discovery (`playlistItems.list` across ~4.8k channels hourly) is 99.5%
of our entire YouTube quota and detects uploads with up-to-an-hour latency.
YouTube's hub pushes upload notifications to a callback instead: **zero quota,
~minutes latency**. Polling stays as a slow reconciliation sweep.

Flow:
  - :func:`subscribe_channel` POSTs to the hub for one channel's feed topic.
  - The hub verifies via GET to our callback (`src/api/routers/websub.py`),
    which confirms the lease; the row flips to ``verified``.
  - Upload notifications POST Atom XML to the callback;
    :func:`parse_notification` extracts entries and the router enrolls them.
  - :func:`renew_due_subscriptions` (scheduler job) subscribes new tracked
    channels and re-subscribes leases nearing expiry, batch-capped.

Pure helpers (parse/HMAC/topic) are separated for unit testing.
"""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Optional

import structlog

logger = structlog.get_logger(__name__)

HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"
RENEW_BEFORE = timedelta(days=2)  # re-subscribe when this close to lease expiry

_ATOM = "{http://www.w3.org/2005/Atom}"
_YT = "{http://www.youtube.com/xml/schemas/2015}"


def topic_url(channel_id: str) -> str:
    return f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}"


def channel_id_from_topic(topic: str) -> Optional[str]:
    if "channel_id=" not in (topic or ""):
        return None
    return topic.split("channel_id=")[-1].split("&")[0] or None


def verify_signature(body: bytes, signature_header: Optional[str], secret: Optional[str]) -> bool:
    """Validate the hub's ``X-Hub-Signature`` (sha1=<hex>) HMAC of the body.

    No secret configured → accept (signature unused). Secret configured but
    header missing/mismatched → reject.
    """
    if not secret:
        return True
    if not signature_header or "=" not in signature_header:
        return False
    algo, _, their_hex = signature_header.partition("=")
    if algo not in ("sha1", "sha256", "sha384", "sha512"):
        return False
    digest = hmac_mod.new(secret.encode(), body, getattr(hashlib, algo)).hexdigest()
    return hmac_mod.compare_digest(digest, their_hex.strip())


def parse_notification(body: bytes) -> List[dict]:
    """Extract upload entries from a WebSub Atom notification (pure).

    Returns ``[{video_id, channel_id, title, published_at}]``; deleted-entry
    notices and malformed bodies return ``[]``.
    """
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    out: List[dict] = []
    for entry in root.findall(f"{_ATOM}entry"):
        vid = entry.findtext(f"{_YT}videoId")
        ch = entry.findtext(f"{_YT}channelId")
        if not vid or not ch:
            continue
        published = None
        raw = entry.findtext(f"{_ATOM}published")
        if raw:
            try:
                published = datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass
        out.append(
            {
                "video_id": vid,
                "channel_id": ch,
                "title": entry.findtext(f"{_ATOM}title") or "",
                "published_at": published,
            }
        )
    return out


def subscribe_channel(channel_id: str, callback_url: str, secret: Optional[str], lease_seconds: int) -> bool:
    """Ask the hub to (re)subscribe one channel. True = hub accepted (202)."""
    import requests

    data = {
        "hub.mode": "subscribe",
        "hub.topic": topic_url(channel_id),
        "hub.callback": f"{callback_url.rstrip('/')}/websub/youtube",
        "hub.lease_seconds": str(lease_seconds),
        "hub.verify": "async",
    }
    if secret:
        data["hub.secret"] = secret
    try:
        r = requests.post(HUB_URL, data=data, timeout=15)
        return r.status_code in (202, 204)
    except Exception as e:
        logger.debug("websub.subscribe_failed", channel_id=channel_id, error=str(e)[:100])
        return False


def renew_due_subscriptions(session, batch: int = 600) -> dict:
    """Subscribe unsubscribed tracked channels + renew leases nearing expiry.

    Bounded per run; at 600/run every 6h the full ~4.8k set enrolls in ~2 days
    and steady-state renewals (~10-day leases) are a few hundred a day.
    """
    from sqlalchemy import select

    from src.config import get_settings
    from src.database.models import TrackedChannel, WebSubSubscription

    s = get_settings()
    if not s.websub_callback_url:
        return {"disabled": True}

    now = datetime.utcnow()
    existing = {
        r.channel_id: r for r in session.query(WebSubSubscription).all()
    }
    tracked = [
        r[0]
        for r in session.execute(
            select(TrackedChannel.channel_id).where(TrackedChannel.is_active == True)  # noqa: E712
        ).all()
    ]

    todo: List[str] = []
    for ch in tracked:
        sub = existing.get(ch)
        if sub is None:
            todo.append(ch)
        elif sub.status == "verified":
            # Renew only near lease expiry.
            if sub.lease_expires_at is None or sub.lease_expires_at - now < RENEW_BEFORE:
                todo.append(ch)
        else:
            # pending/failed: retry unless we asked very recently (hub
            # verification can lag a few minutes — don't hammer).
            if sub.last_subscribed_at is None or now - sub.last_subscribed_at > timedelta(hours=1):
                todo.append(ch)
        if len(todo) >= batch:
            break

    # COMMIT the rows BEFORE asking the hub: its verification GET hits the API
    # within ~a second of each subscribe request, and the API can only see
    # committed rows — flush-then-commit-at-the-end 404'd every verification
    # (observed live 2026-06-12).
    for ch in todo:
        if ch not in existing:
            sub = WebSubSubscription(channel_id=ch, status="pending")
            session.add(sub)
            existing[ch] = sub
    session.commit()

    requested = accepted = 0
    for ch in todo:
        requested += 1
        ok = subscribe_channel(ch, s.websub_callback_url, s.websub_secret, s.websub_lease_seconds)
        sub = existing[ch]
        sub.last_subscribed_at = now
        if ok:
            accepted += 1
            # Lease is set authoritatively by the hub's verification GET
            # (websub_verify); only mark failures here.
            if sub.status == "failed":
                sub.status = "pending"
        else:
            sub.status = "failed"
        session.commit()
    return {"requested": requested, "accepted": accepted, "tracked": len(tracked)}
