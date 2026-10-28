"""Tracked-set expansion from mostPopular charts (plan 8.11).

Shared by the manual `scripts/expand_tracked_channels.py` and the weekly
scheduler job (`expand_tracked_set_job`). Sweeps the mostPopular chart per
(region × category) — 1 quota unit/call, niche-stratified by construction —
and enrolls channels not already tracked. English-speaking regions by default
(the product is English-first; plan 8.12). Diminishing per run: repeat sweeps
mostly re-see already-tracked channels.

Lives in src/ (not scripts/) so the scheduler image — which ships only src/ —
can import it.
"""
from __future__ import annotations

from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# English-speaking regions only (plan 8.12). Override for an intl expansion.
DEFAULT_REGIONS = ["US", "GB", "CA", "AU", "NZ", "IE"]
# Broad-creator-activity categories (None = the overall chart).
DEFAULT_CATEGORIES = [None, "1", "10", "17", "20", "22", "23", "24", "25", "26", "27", "28"]
CATEGORY_NAMES = {
    None: "all", "1": "film", "10": "music", "17": "sports", "20": "gaming",
    "22": "people-blogs", "23": "comedy", "24": "entertainment", "25": "news",
    "26": "howto", "27": "education", "28": "science-tech",
}


def fetch_popular_channels(client, regions, categories) -> dict:
    """Sweep mostPopular charts → {channel_id: category_name_first_seen}.

    Uses the client's quota-rotating ``get_most_popular`` (raw API access
    bypasses key rotation and 403s forever after one key exhausts).
    """
    from src.features.language import is_probably_english

    found: dict = {}
    calls = 0
    skipped = 0
    for region in regions:
        for cat in categories:
            try:
                for info in client.get_most_popular(region_code=region, video_category_id=cat):
                    if info.channel_id and info.channel_id not in found:
                        # English-first (8.12): don't enroll channels whose chart
                        # video isn't English — keeps the tracked set from skewing
                        # international as it grows.
                        if not is_probably_english(getattr(info, "title", None), getattr(info, "default_audio_language", None)):
                            skipped += 1
                            continue
                        found[info.channel_id] = CATEGORY_NAMES.get(cat, cat or "all")
                calls += 1
            except Exception as e:
                logger.debug("expand.chart_failed", region=region, category=cat, error=str(e)[:80])
    logger.info("expand.sweep_done", calls=calls, channels=len(found), skipped_nonenglish=skipped)
    return found


def expand_tracked_set(
    session,
    client,
    regions=None,
    categories=None,
    limit: Optional[int] = None,
) -> dict:
    """Enroll currently-popular channels not already tracked. Returns stats."""
    from src.database.models import TrackedChannel

    regions = regions or DEFAULT_REGIONS
    categories = categories if categories is not None else DEFAULT_CATEGORIES

    found = fetch_popular_channels(client, regions, categories)
    already = {r[0] for r in session.query(TrackedChannel.channel_id).all()}
    new = [(ch, cat) for ch, cat in found.items() if ch not in already]
    if limit:
        new = new[:limit]
    for ch, cat in new:
        session.add(TrackedChannel(
            channel_id=ch,
            recent_video_count=1,   # on the chart now → active by definition
            is_active=True,
            source=f"chart:{cat}"[:20],  # column is String(20)
            enrolled_via="chart",       # enrollment channel (chart|search|graph|user)
        ))
    session.commit()
    total = session.query(TrackedChannel).filter_by(is_active=True).count()
    return {"swept": len(found), "enrolled": len(new), "total_active": total}


# Prune knobs (English-first lifecycle, plan 8.12).
PRUNE_MIN_SAMPLE = 3       # need >= this many collected videos to judge a channel
PRUNE_NON_EN_FRAC = 0.5    # channel is non-English if < this share of its videos are English
PRUNE_MAX_SHARE = 0.6      # safety: never deactivate > this share of the active set in one run


def prune_non_english_channels(session) -> dict:
    """Deactivate tracked channels whose collected uploads are predominantly
    non-English (plan 8.12, English-first).

    The enrollment gate only filters channels added *after* it shipped; this is
    the retroactive + ongoing counterpart. It **deactivates** (``is_active=False``)
    — never deletes — so it's fully reversible and keeps the history. Channels
    without enough collected signal yet are left active (judged later, once they
    upload). A safety abort refuses to act if the language signal looks broken
    (would deactivate most of the set), so a wiped snapshot table can't nuke
    collection.
    """
    from collections import defaultdict

    from sqlalchemy import func, select

    from src.database.models import TrackedChannel, TrackedVideo, VideoSnapshot
    from src.features.language import is_probably_english

    # Language per video = max default_audio_language across its snapshots.
    lang = dict(
        session.execute(
            select(VideoSnapshot.video_id, func.max(VideoSnapshot.default_audio_language))
            .group_by(VideoSnapshot.video_id)
        ).all()
    )
    tally: dict = defaultdict(lambda: [0, 0])  # channel -> [english, total]
    for ch, vid, title in session.execute(
        select(TrackedVideo.channel_id, TrackedVideo.video_id, TrackedVideo.title)
    ).all():
        tally[ch][1] += 1
        if is_probably_english(title or "", lang.get(vid)):
            tally[ch][0] += 1

    non_english = [
        ch for ch, (en, tot) in tally.items()
        if tot >= PRUNE_MIN_SAMPLE and (en / tot) < PRUNE_NON_EN_FRAC
    ]

    active_total = session.query(TrackedChannel).filter_by(is_active=True).count()
    if active_total and len(non_english) > PRUNE_MAX_SHARE * active_total:
        logger.error(
            "prune.aborted_suspicious",
            would_deactivate=len(non_english), active=active_total,
        )
        return {"deactivated": 0, "aborted": True, "candidates": len(non_english)}

    deactivated = 0
    # Chunk the IN() so the bound-parameter count stays under sqlite's 999 limit.
    for i in range(0, len(non_english), 500):
        batch = non_english[i:i + 500]
        deactivated += (
            session.query(TrackedChannel)
            .filter(TrackedChannel.channel_id.in_(batch), TrackedChannel.is_active.is_(True))
            .update({TrackedChannel.is_active: False}, synchronize_session=False)
        )
    if deactivated:
        session.commit()
    logger.info(
        "prune.non_english_done",
        deactivated=deactivated, candidates=len(non_english), active_before=active_total,
    )
    return {"deactivated": deactivated, "candidates": len(non_english), "active_before": active_total}


# ---------------------------------------------------------------------------
# Search-based discovery (plan 8.11, ``enrolled_via='search'``)
# ---------------------------------------------------------------------------
# The mostPopular chart over-indexes already-huge channels; breakouts are most
# detectable in the mid-tail. This fills *starved* niches (per NicheCoverage) by
# searching English keywords — search.list is 100 quota units/call, so it's
# bounded per run and pointed only where coverage is thin (not a firehose).
NICHE_SEARCH_QUERIES: dict[str, list[str]] = {
    "1":  ["film analysis", "movie review", "video essay film"],
    "10": ["music cover", "music producer", "song breakdown"],
    "17": ["sports analysis", "fitness workout", "training tips"],
    "19": ["travel vlog", "budget travel guide", "solo travel"],
    "20": ["gaming walkthrough", "indie game review", "lets play"],
    "22": ["lifestyle vlog", "daily vlog", "productivity routine"],
    "23": ["comedy sketch", "stand up comedy", "funny commentary"],
    "24": ["reaction channel", "pop culture commentary", "entertainment news"],
    "25": ["news explained", "current events analysis", "politics explained"],
    "26": ["how to tutorial", "diy project", "home improvement guide"],
    "27": ["explained educational", "study tips", "science explainer"],
    "28": ["technology review", "gadget review", "science and tech explained"],
}


def _starved_niches(session) -> list[str]:
    """Niches flagged starved in the latest coverage batch, neediest first.

    Falls back to the full query set when coverage hasn't been computed yet, so
    discovery still works on a cold start.
    """
    from src.database.models import NicheCoverage

    try:
        rows = (
            session.query(NicheCoverage.niche)
            .filter(NicheCoverage.starved.is_(True))
            .order_by(NicheCoverage.deficit.desc())
            .all()
        )
        niches = [r[0] for r in rows if r[0] in NICHE_SEARCH_QUERIES]
        if niches:
            return niches
    except Exception as e:  # coverage table may not exist yet
        logger.debug("search.coverage_unavailable", error=str(e)[:80])
    return list(NICHE_SEARCH_QUERIES)


def discover_channels_by_search(
    session,
    client,
    max_queries: int = 6,
    per_query: int = 50,
    limit: Optional[int] = None,
) -> dict:
    """Enroll English channels in starved niches via keyword search.

    One ``search.list`` call (100 quota units) per starved niche, capped at
    ``max_queries`` per run. The keyword rotates by day so repeat runs probe
    different slices instead of re-fetching the same top results. English-gated
    on the channel title; enrolls only channels not already tracked.
    """
    from datetime import datetime

    from src.database.models import TrackedChannel
    from src.features.language import is_probably_english

    niches = _starved_niches(session)[:max_queries]
    if not niches:
        return {"queries": 0, "found": 0, "enrolled": 0}

    day = datetime.utcnow().timetuple().tm_yday
    already = {r[0] for r in session.query(TrackedChannel.channel_id).all()}
    found: dict[str, str] = {}   # channel_id -> niche
    queries = 0
    for i, niche in enumerate(niches):
        kws = NICHE_SEARCH_QUERIES.get(niche) or []
        if not kws:
            continue
        query = kws[day % len(kws)]                       # rotate keyword by day
        region = DEFAULT_REGIONS[(day + i) % len(DEFAULT_REGIONS)]
        try:
            resp = client.search_channels(
                query=query, max_results=per_query, region_code=region, relevance_language="en",
            )
            queries += 1
        except Exception as e:
            logger.warning("search.query_failed", niche=niche, query=query, error=str(e)[:80])
            continue
        for item in resp.get("items", []):
            ch = (item.get("id") or {}).get("channelId")
            title = (item.get("snippet") or {}).get("title") or ""
            if not ch or ch in already or ch in found:
                continue
            if not is_probably_english(title, None):      # script-based English gate
                continue
            found[ch] = niche

    new = list(found.items())
    if limit:
        new = new[:limit]
    for ch, niche in new:
        session.add(TrackedChannel(
            channel_id=ch,
            recent_video_count=0,                         # activity unknown until collected
            is_active=True,
            source=f"search:{niche}"[:20],
            enrolled_via="search",
        ))
    session.commit()
    total = session.query(TrackedChannel).filter_by(is_active=True).count()
    logger.info(
        "search.discovery_done",
        queries=queries, found=len(found), enrolled=len(new), niches=niches[:max_queries],
    )
    return {"queries": queries, "found": len(found), "enrolled": len(new), "total_active": total}
