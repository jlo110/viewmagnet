"""WebSub callback for YouTube push notifications (plan 7.5).

The hub calls GET to verify a subscription (echo ``hub.challenge``) and POSTs
Atom XML when a tracked channel uploads. Notifications enroll the video into
velocity tracking immediately — the same enrollment polling discovery does,
minus the quota and the up-to-an-hour delay. Unauthenticated by design (the
hub is the caller); protected by topic validation + optional HMAC signature.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from fastapi import APIRouter, Query, Request, Response

from src.database.connection import get_session
from src.database.models import TrackedChannel, TrackedVideo, WebSubSubscription
from src.tracking.websub import channel_id_from_topic, parse_notification, verify_signature

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["websub"])

MAX_VIDEO_AGE = timedelta(days=3)  # ignore notifications for old (edited) videos


@router.get("/websub/youtube")
async def websub_verify(
    request: Request,  # noqa: ARG001
    mode: str = Query(default="", alias="hub.mode"),
    topic: str = Query(default="", alias="hub.topic"),
    challenge: str = Query(default="", alias="hub.challenge"),
    lease_seconds: int = Query(default=0, alias="hub.lease_seconds"),
):
    """Hub subscription verification: echo the challenge for known channels."""
    channel_id = channel_id_from_topic(topic)
    if mode not in ("subscribe", "unsubscribe") or not challenge or not channel_id:
        return Response(status_code=404)

    if mode == "subscribe":
        with get_session() as db:
            sub = db.query(WebSubSubscription).filter_by(channel_id=channel_id).one_or_none()
            if sub is None:
                # Verification for a channel we never asked about — refuse.
                return Response(status_code=404)
            sub.status = "verified"
            if lease_seconds:
                sub.lease_expires_at = datetime.utcnow() + timedelta(seconds=lease_seconds)
            db.commit()
        logger.info("websub.verified", channel_id=channel_id, lease=lease_seconds)
    return Response(content=challenge, media_type="text/plain")


@router.post("/websub/youtube")
async def websub_notify(request: Request):
    """Upload notification: enroll new videos from tracked channels."""
    from src.config import get_settings

    body = await request.body()
    if not verify_signature(
        body, request.headers.get("X-Hub-Signature"), get_settings().websub_secret
    ):
        logger.warning("websub.bad_signature")
        return Response(status_code=202)  # 2xx per spec; don't invite retries

    entries = parse_notification(body)
    if not entries:
        return Response(status_code=204)

    now = datetime.utcnow()
    enrolled = 0
    with get_session() as db:
        for e in entries:
            pub = e["published_at"]
            if pub is None or now - pub > MAX_VIDEO_AGE:
                continue  # edits/old videos; reconciliation handles stragglers
            channel = (
                db.query(TrackedChannel)
                .filter_by(channel_id=e["channel_id"], is_active=True)
                .one_or_none()
            )
            if channel is None:
                continue
            if db.query(TrackedVideo).filter_by(video_id=e["video_id"]).one_or_none():
                continue
            db.add(
                TrackedVideo(
                    video_id=e["video_id"],
                    channel_id=e["channel_id"],
                    title=(e["title"] or "")[:500],
                    published_at=pub,
                )
            )
            enrolled += 1
            sub = db.query(WebSubSubscription).filter_by(channel_id=e["channel_id"]).one_or_none()
            if sub:
                sub.last_notified_at = now
                sub.notification_count += 1
        db.commit()

    if enrolled:
        logger.info("websub.enrolled", videos=enrolled)
    return Response(status_code=204)
