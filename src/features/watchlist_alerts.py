"""Email alerts for breakouts on users' watchlist channels.

Runs on a schedule: detect breakouts across the tracked set once, fan them out to
the users watching those channels, dedup against ``WatchlistAlertSent`` so we
never email twice for the same video, and send one digest email per user via the
provider-pluggable ``notifications.send_email`` (console backend until
``EMAIL_PROVIDER`` is configured — so no real mail goes out until you opt in).
"""
from __future__ import annotations

from collections import defaultdict

import structlog

logger = structlog.get_logger(__name__)

# Only alert on reasonably-confident calls (false alerts kill trust).
ALERT_MIN_PROBABILITY = 0.75
ALERT_CHECKPOINT = "6h"
MAX_ITEMS_PER_EMAIL = 8


def _render(user_name: str, items: list[dict]) -> tuple[str, str, str]:
    n = len(items)
    subject = f"🚀 {n} breakout{'s' if n != 1 else ''} on your watchlist"
    lines, html_rows = [], []
    for it in items:
        pct = round((it.get("probability") or 0) * 100)
        dur = (it.get("durability") or {}).get("label", "")
        dur_txt = {"likely_to_sustain": " · likely to sustain", "could_flash": " · could flash"}.get(dur, "")
        lines.append(f"• [{pct}%] {it.get('title','')}{dur_txt}\n  {it.get('watch_url','')}")
        html_rows.append(
            f"<li><strong>{pct}% breakout</strong>{dur_txt} — "
            f"<a href=\"{it.get('watch_url','')}\">{it.get('title','')}</a></li>"
        )
    text = (f"Hi {user_name},\n\nNew breakouts on channels you're watching:\n\n"
            + "\n\n".join(lines)
            + "\n\nWe flag these early — packaging doesn't predict, early velocity does. "
              "The durability note is our best read on whether it'll last.\n")
    html = (f"<p>Hi {user_name},</p><p>New breakouts on channels you're watching:</p>"
            f"<ul>{''.join(html_rows)}</ul>"
            "<p style='color:#888;font-size:12px'>Flagged early from live velocity. "
            "Durability is our best read on staying power.</p>")
    return subject, text, html


def send_watchlist_alerts(session, max_users: int = 200) -> dict:
    """Detect breakouts on watched channels, email each user the NEW ones (deduped)."""
    from src.database.models import User, WatchlistAlertSent, WatchlistChannel
    from src.features.breakout_detector import detect_live_breakouts
    from src.features.durability_grader import grade
    from src.features.notifications import send_email, send_webhook

    watchers = session.query(WatchlistChannel.user_id, WatchlistChannel.channel_id).all()
    if not watchers:
        return {"users_alerted": 0, "emails_sent": 0}
    channel_watchers: dict = defaultdict(set)
    for uid, cid in watchers:
        channel_watchers[cid].add(uid)

    items = detect_live_breakouts(
        session, checkpoint=ALERT_CHECKPOINT, min_probability=ALERT_MIN_PROBABILITY,
        max_age_hours=72.0, min_views=500.0, limit=500,
    )
    items = [it for it in items if it.get("channel_id") in channel_watchers]
    if not items:
        return {"users_alerted": 0, "emails_sent": 0, "breakouts": 0}

    grades = grade(session, [it["video_id"] for it in items], checkpoint=ALERT_CHECKPOINT)
    for it in items:
        it["durability"] = grades.get(it["video_id"], {})

    # Fan out to users, then dedup against what we've already sent.
    per_user: dict = defaultdict(list)
    for it in items:
        for uid in channel_watchers[it["channel_id"]]:
            per_user[uid].append(it)

    uids = list(per_user)[:max_users]
    sent_pairs = {
        (r.user_id, r.video_id)
        for r in session.query(WatchlistAlertSent).filter(WatchlistAlertSent.user_id.in_(uids)).all()
    }
    # Email opt-in gates the email; the webhook is delivered independently (an
    # agency may want only the war-room feed, not inbox mail). All matched users
    # are loaded so a webhook fires even when email is opted out.
    users = {u.id: u for u in session.query(User).filter(User.id.in_(uids)).all()}

    emails_sent = 0
    webhooks_sent = 0
    for uid in uids:
        new_items = [it for it in per_user[uid] if (uid, it["video_id"]) not in sent_pairs][:MAX_ITEMS_PER_EMAIL]
        user = users.get(uid)
        if not new_items or not user:
            continue
        wants_email = bool(getattr(user, "watchlist_email_alerts", True) and user.email)
        webhook_url = getattr(user, "alert_webhook_url", None)
        if not wants_email and not webhook_url:
            continue  # no delivery channel — don't burn the dedup record on it
        subject, text, html = _render(getattr(user, "name", None) or "there", new_items)
        if wants_email and send_email(user.email, subject, text, html):
            emails_sent += 1
        if webhook_url and send_webhook(webhook_url, f"*{subject}*\n\n{text}"):
            webhooks_sent += 1
        for it in new_items:
            session.add(WatchlistAlertSent(user_id=uid, video_id=it["video_id"], channel_id=it.get("channel_id")))
        session.commit()
    logger.info("watchlist_alerts.sent", emails_sent=emails_sent,
                webhooks_sent=webhooks_sent, breakouts=len(items))
    return {"users_alerted": emails_sent, "emails_sent": emails_sent,
            "webhooks_sent": webhooks_sent, "breakouts": len(items)}
