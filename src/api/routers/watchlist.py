"""Competitive Watchlist — track any public channel, get honest breakout +
durability alerts (the wedge Studio can't match: it's your-channel-only).

Adding a channel enrolls it into collection (TrackedChannel + WebSub) so we
sample its uploads going forward, then ``GET /watchlist/breakouts`` runs the
validated detector on the user's watched channels and attaches a durability
badge (sustain vs flash). In-app/poll MVP — no push/email yet.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_session
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["watchlist"])

_CHANNEL_RE = re.compile(r"/channel/(UC[a-zA-Z0-9_-]{22})")
_BARE_ID_RE = re.compile(r"^(UC[a-zA-Z0-9_-]{22})$")
_HANDLE_RE = re.compile(r"@([a-zA-Z0-9._-]+)")


class AddChannelBody(BaseModel):
    url: str
    label: Optional[str] = None


class WatchlistSettingsBody(BaseModel):
    email_alerts: Optional[bool] = None
    weekly_digest: Optional[bool] = None
    alert_webhook_url: Optional[str] = None  # "" clears it


def resolve_channel_id(client, url_or_handle: str) -> tuple[Optional[str], Optional[str]]:
    """(channel_id, title) from a /channel/UC… URL, a bare UC… id, or an
    @handle / name (resolved via search). (None, None) if unresolvable."""
    s = (url_or_handle or "").strip()
    m = _CHANNEL_RE.search(s) or _BARE_ID_RE.match(s)
    if m:
        return m.group(1), None
    handle = _HANDLE_RE.search(s)
    query = handle.group(1) if handle else s
    try:
        resp = client.search_channels(query=query, max_results=1)
        for item in resp.get("items", []):
            cid = (item.get("id") or {}).get("channelId")
            if cid:
                return cid, (item.get("snippet") or {}).get("title")
    except Exception as e:  # noqa: BLE001
        logger.warning("watchlist.resolve_failed", query=query[:60], error=str(e)[:80])
    return None, None


def _enroll_for_collection(db, channel_id: str) -> None:
    """Ensure the channel is tracked + WebSub-subscribed (best-effort)."""
    from src.config import get_settings
    from src.database.models import TrackedChannel

    existing = db.query(TrackedChannel).filter_by(channel_id=channel_id).first()
    if existing is None:
        db.add(TrackedChannel(
            channel_id=channel_id, recent_video_count=0, is_active=True,
            source="watchlist", enrolled_via="user",
        ))
    elif not existing.is_active:
        existing.is_active = True  # re-activate if it was pruned
    db.commit()
    try:
        from src.tracking.websub import subscribe_channel
        s = get_settings()
        if s.websub_callback_url:
            subscribe_channel(channel_id, s.websub_callback_url, s.websub_secret, s.websub_lease_seconds)
    except Exception as e:  # noqa: BLE001
        logger.warning("watchlist.websub_failed", channel=channel_id, error=str(e)[:80])


@router.post("/watchlist")
@limiter.limit(Tier.MEDIA_HEAVY)
async def add_to_watchlist(
    request: Request,  # noqa: ARG001
    body: AddChannelBody,
    current_user: User = Depends(get_current_user),
):
    """Add a public channel (URL / @handle / UC… id) to the user's watchlist."""
    from src.database.models import WatchlistChannel
    from src.youtube.client import YouTubeClient

    channel_id, title = resolve_channel_id(YouTubeClient(), body.url)
    if not channel_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Couldn't resolve that to a YouTube channel.")
    with get_session() as db:
        _enroll_for_collection(db, channel_id)
        existing = db.query(WatchlistChannel).filter_by(
            user_id=current_user.id, channel_id=channel_id).first()
        if existing is None:
            db.add(WatchlistChannel(
                user_id=current_user.id, channel_id=channel_id,
                channel_title=title, label=body.label,
            ))
            db.commit()
        return {"channel_id": channel_id, "channel_title": title, "added": existing is None}


@router.get("/watchlist/settings")
@limiter.limit(Tier.READ)
async def get_watchlist_settings(
    request: Request,  # noqa: ARG001
    current_user: User = Depends(get_current_user),
):
    return {"email_alerts": bool(getattr(current_user, "watchlist_email_alerts", True)),
            "weekly_digest": bool(getattr(current_user, "weekly_digest", False)),
            "alert_webhook_url": getattr(current_user, "alert_webhook_url", None) or ""}


@router.patch("/watchlist/settings")
@limiter.limit(Tier.READ)
async def update_watchlist_settings(
    request: Request,  # noqa: ARG001
    body: WatchlistSettingsBody,
    current_user: User = Depends(get_current_user),
):
    with get_session() as db:
        u = db.query(User).filter_by(id=current_user.id).first()
        if u:
            if body.email_alerts is not None:
                u.watchlist_email_alerts = body.email_alerts
            if body.weekly_digest is not None:
                u.weekly_digest = body.weekly_digest
            if body.alert_webhook_url is not None:
                cleaned = body.alert_webhook_url.strip()
                if cleaned and not cleaned.startswith("https://"):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                        detail="Webhook URL must be an https:// Slack or Discord URL.")
                u.alert_webhook_url = cleaned or None
            db.commit()
        return {"email_alerts": bool(getattr(u, "watchlist_email_alerts", True)),
                "weekly_digest": bool(getattr(u, "weekly_digest", False)),
                "alert_webhook_url": getattr(u, "alert_webhook_url", None) or ""}


@router.get("/watchlist")
@limiter.limit(Tier.READ)
async def get_watchlist(
    request: Request,  # noqa: ARG001
    current_user: User = Depends(get_current_user),
):
    from src.database.models import WatchlistChannel

    with get_session() as db:
        rows = db.query(WatchlistChannel).filter_by(user_id=current_user.id).order_by(
            WatchlistChannel.added_at.desc()).all()
        return {"channels": [
            {"channel_id": r.channel_id, "channel_title": r.channel_title,
             "label": r.label, "added_at": r.added_at.isoformat() + "Z"}
            for r in rows
        ]}


@router.delete("/watchlist/{channel_id}")
@limiter.limit(Tier.READ)
async def remove_from_watchlist(
    request: Request,  # noqa: ARG001
    channel_id: str,
    current_user: User = Depends(get_current_user),
):
    from src.database.models import WatchlistChannel

    with get_session() as db:
        deleted = db.query(WatchlistChannel).filter_by(
            user_id=current_user.id, channel_id=channel_id).delete()
        db.commit()
        return {"removed": bool(deleted)}


# Alert modes (from the precision/lead-time eval): trade catch-rate for trust.
#   precise   → only high-confidence calls (fewer, ~85%+ precision)
#   balanced  → the default
#   sensitive → catch more, lower precision
_MODE_THRESHOLD = {"precise": 0.85, "balanced": 0.6, "sensitive": 0.4}


@router.get("/watchlist/breakouts")
@limiter.limit(Tier.READ)
async def watchlist_breakouts(
    request: Request,  # noqa: ARG001
    checkpoint: str = Query(default="6h", pattern="^(1h|6h|24h)$"),
    mode: str = Query(default="balanced", pattern="^(precise|balanced|sensitive)$"),
    max_age_hours: float = Query(default=168.0, ge=1.0, le=336.0),
    limit: int = Query(default=40, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    """Breakouts detected on the user's watched channels, with a durability badge.

    ``mode`` tunes the precision/recall trade-off (precise = only sure things;
    sensitive = catch more).
    """
    min_probability = _MODE_THRESHOLD.get(mode, 0.6)
    from src.database.models import WatchlistChannel
    from src.features.breakout_detector import detect_live_breakouts
    from src.features.topic_saturation import annotate_with_topics

    with get_session() as db:
        watched = {r[0] for r in db.query(WatchlistChannel.channel_id).filter_by(
            user_id=current_user.id).all()}
        if not watched:
            return {"checkpoint": checkpoint, "count": 0, "breakouts": [],
                    "updated_at": datetime.utcnow().isoformat() + "Z"}
        try:
            items = detect_live_breakouts(
                db, checkpoint=checkpoint, min_probability=min_probability,
                max_age_hours=max_age_hours, min_views=500.0, limit=500,
            )
            items = [it for it in items if it.get("channel_id") in watched][:limit]
            items = annotate_with_topics(db, items)
            # niche + detection-confidence (same annotation the radar uses) — without
            # this each item's `confidence` is undefined in the UI.
            from src.api.routers.breakouts import _annotate_niche
            items = _annotate_niche(db, items)
            # Durability badge (sustain vs flash) on each.
            from src.features.durability_grader import grade
            grades = grade(db, [it["video_id"] for it in items], checkpoint=checkpoint)
            for it in items:
                it["durability"] = grades.get(it["video_id"], {"label": "too_early", "probability": None})
        except Exception as exc:  # noqa: BLE001
            logger.warning("watchlist.breakouts_failed", error=str(exc))
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail=f"watchlist breakouts failed: {exc}")
    return {"checkpoint": checkpoint, "count": len(items), "breakouts": items,
            "updated_at": datetime.utcnow().isoformat() + "Z"}


@router.get("/watchlist/leaderboard")
@limiter.limit(Tier.READ)
async def watchlist_leaderboard(
    request: Request,  # noqa: ARG001
    window_days: int = Query(default=30, ge=7, le=90),
    checkpoint: str = Query(default="6h", pattern="^(1h|6h|24h)$"),
    current_user: User = Depends(get_current_user),
):
    """Which watched channels break out most often — who's worth studying.

    Runs the validated detector over a ``window_days`` window, keeps the user's
    watched channels, and ranks them by breakout count (with average durability,
    so a channel of flashes ranks below one whose hits actually stick).
    """
    from src.database.models import WatchlistChannel
    from src.features.breakout_detector import detect_live_breakouts
    from src.features.durability_grader import grade

    with get_session() as db:
        watched = dict(db.query(WatchlistChannel.channel_id, WatchlistChannel.channel_title)
                       .filter_by(user_id=current_user.id).all())
        if not watched:
            return {"window_days": window_days, "channels": [],
                    "updated_at": datetime.utcnow().isoformat() + "Z"}
        try:
            items = detect_live_breakouts(
                db, checkpoint=checkpoint, min_probability=0.6,
                max_age_hours=float(window_days * 24), min_views=500.0, limit=2000,
            )
            items = [it for it in items if it.get("channel_id") in watched]
            grades = grade(db, [it["video_id"] for it in items], checkpoint=checkpoint)

            agg: dict = {}
            for it in items:
                cid = it["channel_id"]
                row = agg.setdefault(cid, {
                    "channel_id": cid, "channel_title": watched.get(cid) or cid,
                    "breakout_count": 0, "_durs": [], "top_video": None, "_top_p": -1.0,
                })
                row["breakout_count"] += 1
                g = grades.get(it["video_id"])
                if g and g.get("probability") is not None:
                    row["_durs"].append(g["probability"])
                p = it.get("probability") or 0.0
                if p > row["_top_p"]:
                    row["_top_p"] = p
                    row["top_video"] = {
                        "video_id": it["video_id"], "title": it.get("title"),
                        "probability": p,
                        "watch_url": f"https://www.youtube.com/watch?v={it['video_id']}",
                    }
            channels = []
            for row in agg.values():
                durs = row.pop("_durs")
                row.pop("_top_p", None)
                row["avg_durability"] = round(sum(durs) / len(durs), 3) if durs else None
                channels.append(row)
            # Most prolific breakers first; ties broken by how well their hits sustain.
            channels.sort(key=lambda r: (r["breakout_count"], r["avg_durability"] or 0), reverse=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("watchlist.leaderboard_failed", error=str(exc))
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail=f"watchlist leaderboard failed: {exc}")
    return {"window_days": window_days, "channels": channels,
            "updated_at": datetime.utcnow().isoformat() + "Z"}
