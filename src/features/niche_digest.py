"""Weekly digest email — a low-frequency roundup of the week's biggest breakouts
on each user's watchlist.

Distinct from ``watchlist_alerts`` (real-time, per-video, sent within hours of a
breakout): this is a once-a-week "here's what broke out in your competitive set"
roundup — the B2B retention hook that re-engages even in a quiet week. Opt-in
(``users.weekly_digest``), ranks the week's breakouts by durability (the ones
that actually stuck), and is windowed strictly to the last 7 days so each run
covers a fresh week (no per-video dedup table needed).
"""
from __future__ import annotations

from collections import defaultdict

import structlog

logger = structlog.get_logger(__name__)

DIGEST_CHECKPOINT = "6h"
DIGEST_WINDOW_HOURS = 168.0  # 7 days
DIGEST_MIN_PROBABILITY = 0.7
MAX_ITEMS_PER_DIGEST = 10


def _durability_rank(item: dict) -> tuple[float, float]:
    """Sort key: the ones that stuck first (durability), then strongest breakout."""
    dur = (item.get("durability") or {}).get("probability")
    return (dur if dur is not None else -1.0, item.get("probability") or 0.0)


def _render(user_name: str, items: list[dict]) -> tuple[str, str, str]:
    n = len(items)
    subject = f"📊 Your week in breakouts — {n} on your watchlist"
    lines, html_rows = [], []
    for it in items:
        pct = round((it.get("probability") or 0) * 100)
        dur = (it.get("durability") or {}).get("label", "")
        dur_txt = {"likely_to_sustain": " · stuck", "could_flash": " · flashed"}.get(dur, "")
        chan = it.get("channel_title") or ""
        chan_txt = f" ({chan})" if chan else ""
        lines.append(f"• [{pct}%]{dur_txt} {it.get('title','')}{chan_txt}\n  {it.get('watch_url','')}")
        html_rows.append(
            f"<li><strong>{pct}%</strong>{dur_txt} — "
            f"<a href=\"{it.get('watch_url','')}\">{it.get('title','')}</a>"
            f"<span style='color:#888'>{chan_txt}</span></li>"
        )
    text = (f"Hi {user_name},\n\nThe biggest breakouts on the channels you watch this week, "
            "ranked by whether they stuck:\n\n"
            + "\n\n".join(lines)
            + "\n\nWe detect these early from live velocity — packaging doesn't predict, "
              "early velocity does. The 'stuck/flashed' note is our best read on staying power.\n")
    html = (f"<p>Hi {user_name},</p><p>The biggest breakouts on the channels you watch this "
            "week, ranked by whether they stuck:</p>"
            f"<ul>{''.join(html_rows)}</ul>"
            "<p style='color:#888;font-size:12px'>Detected early from live velocity. "
            "'Stuck/flashed' is our best read on staying power.</p>")
    return subject, text, html


def send_niche_digests(session, max_users: int = 500) -> dict:
    """Email each opted-in user a weekly roundup of their watchlist's top breakouts."""
    from src.database.models import User, WatchlistChannel
    from src.features.breakout_detector import detect_live_breakouts
    from src.features.durability_grader import grade
    from src.features.notifications import send_email

    # Only opted-in users with at least one watched channel.
    opted_in = {u.id: u for u in session.query(User).filter(
        User.weekly_digest.is_(True)).all() if u.email}
    if not opted_in:
        return {"users_digested": 0, "breakouts": 0}

    watchers = session.query(WatchlistChannel.user_id, WatchlistChannel.channel_id,
                             WatchlistChannel.channel_title).filter(
        WatchlistChannel.user_id.in_(list(opted_in))).all()
    if not watchers:
        return {"users_digested": 0, "breakouts": 0}
    channel_watchers: dict = defaultdict(set)
    channel_title: dict = {}
    for uid, cid, title in watchers:
        channel_watchers[cid].add(uid)
        if title:
            channel_title[cid] = title

    items = detect_live_breakouts(
        session, checkpoint=DIGEST_CHECKPOINT, min_probability=DIGEST_MIN_PROBABILITY,
        max_age_hours=DIGEST_WINDOW_HOURS, min_views=500.0, limit=2000,
    )
    items = [it for it in items if it.get("channel_id") in channel_watchers]
    if not items:
        return {"users_digested": 0, "breakouts": 0}

    grades = grade(session, [it["video_id"] for it in items], checkpoint=DIGEST_CHECKPOINT)
    for it in items:
        it["durability"] = grades.get(it["video_id"], {})
        it["channel_title"] = channel_title.get(it["channel_id"])
        it["watch_url"] = it.get("watch_url") or f"https://www.youtube.com/watch?v={it['video_id']}"

    per_user: dict = defaultdict(list)
    for it in items:
        for uid in channel_watchers[it["channel_id"]]:
            per_user[uid].append(it)

    digested = 0
    for uid in list(per_user)[:max_users]:
        user = opted_in.get(uid)
        if not user:
            continue
        ranked = sorted(per_user[uid], key=_durability_rank, reverse=True)[:MAX_ITEMS_PER_DIGEST]
        if not ranked:
            continue
        subject, text, html = _render(getattr(user, "name", None) or "there", ranked)
        if send_email(user.email, subject, text, html):
            digested += 1
    logger.info("niche_digest.sent", users_digested=digested, breakouts=len(items))
    return {"users_digested": digested, "breakouts": len(items)}
