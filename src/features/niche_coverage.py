"""Per-niche tracking coverage (spec: docs/specs/stratified-expansion.md).

Answers "are we tracking enough channels?" niche by niche, not globally. The
measurement half of stratified expansion: it flags which niches are too thin to
surface live signal (the Format Radar needs density), and those flags drive the
next expansion sweep.

Key trick: a channel's niche is *derived* from the modal ``youtube_category_id``
of its tracked videos — zero API quota — so coverage works on existing data
before any subscriber-count enrichment runs.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# Niches we report on (the categories we already map elsewhere).
NICHES = ["1", "10", "17", "19", "20", "22", "23", "24", "25", "26", "27", "28"]
NICHE_NAMES = {
    "1": "Film", "2": "Autos", "10": "Music", "15": "Pets", "17": "Sports",
    "19": "Travel", "20": "Gaming", "22": "People & Blogs", "23": "Comedy",
    "24": "Entertainment", "25": "News", "26": "Howto", "27": "Education",
    "28": "Science & Tech", "29": "Nonprofit",
}

# Per-niche channel target + tier weighting (spec §4). Tuned later from observed
# breakout density; the point now is to have a deficit signal to expand against.
TARGET_PER_NICHE = 3300
TIER_WEIGHTS = {"nano": 0.15, "micro": 0.40, "mid": 0.35, "large": 0.10}

# A niche is "starved" if any holds.
MIN_BREAKOUTS_7D = 5
MIN_CHANNELS_FOR_SIGNAL = 200


def classify_tier(subscriber_count: Optional[int]) -> Optional[str]:
    """Map a subscriber count to a size tier (None if unknown)."""
    if subscriber_count is None:
        return None
    if subscriber_count < 10_000:
        return "nano"
    if subscriber_count < 100_000:
        return "micro"
    if subscriber_count < 1_000_000:
        return "mid"
    return "large"


def is_starved(tracked_channels: int, breakouts_7d: int, active_formats: int, deficit: int) -> bool:
    """Whether a niche needs expansion priority."""
    return (
        tracked_channels < MIN_CHANNELS_FOR_SIGNAL
        or breakouts_7d < MIN_BREAKOUTS_7D
        or active_formats == 0
        or deficit > 0
    )


def _derive_channel_niches(session) -> dict[str, str]:
    """channel_id -> modal youtube_category_id, from the channel's tracked videos.

    Zero API quota. One grouped query over (TrackedVideo.channel_id, snapshot
    category) keeps the channel's dominant niche. Channels with no categorized
    snapshots are simply absent (counted as 'unknown').
    """
    from sqlalchemy import func, select

    from src.database.models import TrackedVideo, VideoSnapshot

    rows = session.execute(
        select(
            TrackedVideo.channel_id,
            VideoSnapshot.youtube_category_id,
            func.count().label("n"),
        )
        .join(VideoSnapshot, VideoSnapshot.video_id == TrackedVideo.video_id)
        .where(VideoSnapshot.youtube_category_id.isnot(None))
        .group_by(TrackedVideo.channel_id, VideoSnapshot.youtube_category_id)
    ).all()
    best: dict[str, tuple[str, int]] = {}
    for ch, cat, n in rows:
        if ch not in best or n > best[ch][1]:
            best[ch] = (cat, n)
    return {ch: cat for ch, (cat, _) in best.items()}


def compute_niche_coverage(session) -> dict:
    """Recompute per-niche coverage. Upserts one NicheCoverage row per niche."""
    from sqlalchemy import select

    from src.database.models import (
        EmergingFormat,
        NicheCoverage,
        TrackedChannel,
    )
    from src.features.breakout_detector import detect_live_breakouts

    now = datetime.utcnow()
    niche_of = _derive_channel_niches(session)

    # tier per channel (only where enriched); else "unknown"
    tier_of = dict(
        session.execute(
            select(TrackedChannel.channel_id, TrackedChannel.size_tier)
            .where(TrackedChannel.is_active.is_(True))
        ).all()
    )

    # roll up channels -> per niche counts + tier mix
    per_niche: dict[str, dict] = {n: {"channels": 0, "tiers": {"nano": 0, "micro": 0, "mid": 0, "large": 0, "unknown": 0}} for n in NICHES}
    for ch, tier in tier_of.items():
        cat = niche_of.get(ch)
        if cat not in per_niche:
            continue
        per_niche[cat]["channels"] += 1
        per_niche[cat]["tiers"][tier or "unknown"] += 1

    # breakouts in the last 7d, bucketed by the breaking video's niche
    breakout_counts: dict[str, int] = {n: 0 for n in NICHES}
    try:
        breakouts = detect_live_breakouts(
            session, checkpoint="6h", min_probability=0.6,
            max_age_hours=7 * 24, limit=3000, min_views=1000.0,
        )
        bvids = [b["video_id"] for b in breakouts]
        if bvids:
            from sqlalchemy import func, select

            from src.database.models import VideoSnapshot
            bcat = dict(
                session.execute(
                    select(VideoSnapshot.video_id, func.max(VideoSnapshot.youtube_category_id))
                    .where(VideoSnapshot.video_id.in_(bvids))
                    .group_by(VideoSnapshot.video_id)
                ).all()
            )
            for vid in bvids:
                c = bcat.get(vid)
                if c in breakout_counts:
                    breakout_counts[c] += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("coverage.breakouts_failed", error=str(exc))

    # active Format Radar patterns per niche
    fmt_counts: dict[str, int] = {n: 0 for n in NICHES}
    try:
        from sqlalchemy import func, select
        for niche, cnt in session.execute(
            select(EmergingFormat.niche, func.count()).group_by(EmergingFormat.niche)
        ).all():
            if niche in fmt_counts:
                fmt_counts[niche] += cnt
    except Exception as exc:  # noqa: BLE001
        logger.warning("coverage.formats_failed", error=str(exc))

    session.query(NicheCoverage).delete()
    starved_n = 0
    for niche in NICHES:
        tracked = per_niche[niche]["channels"]
        b7 = breakout_counts[niche]
        af = fmt_counts[niche]
        deficit = max(0, TARGET_PER_NICHE - tracked)
        starved = is_starved(tracked, b7, af, deficit)
        starved_n += int(starved)
        session.add(NicheCoverage(
            niche=niche, tracked_channels=tracked,
            tier_mix=json.dumps(per_niche[niche]["tiers"]),
            breakouts_7d=b7, active_formats=af,
            target_channels=TARGET_PER_NICHE, deficit=deficit,
            starved=starved, computed_at=now,
        ))
    session.commit()
    logger.info("coverage.complete", niches=len(NICHES), starved=starved_n)
    return {"niches": len(NICHES), "starved": starved_n}


def get_coverage(session) -> dict:
    """Read the latest coverage batch for the admin endpoint."""
    from src.database.models import NicheCoverage

    rows = session.query(NicheCoverage).order_by(NicheCoverage.deficit.desc()).all()

    def row(r) -> dict:
        return {
            "niche": r.niche,
            "niche_name": NICHE_NAMES.get(r.niche, r.niche),
            "tracked_channels": r.tracked_channels,
            "tier_mix": json.loads(r.tier_mix) if r.tier_mix else {},
            "breakouts_7d": r.breakouts_7d,
            "active_formats": r.active_formats,
            "target_channels": r.target_channels,
            "deficit": r.deficit,
            "starved": r.starved,
        }

    updated = max((r.computed_at for r in rows), default=None)
    return {
        "niches": len(rows),
        "starved": sum(1 for r in rows if r.starved),
        "tracked_total": sum(r.tracked_channels for r in rows),
        "updated_at": (updated.isoformat() + "Z") if updated else None,
        "coverage": [row(r) for r in rows],
    }


def enrich_pending_channels(session, client, limit: int = 200) -> dict:
    """Backfill subscriber_count + size_tier for channels missing them.

    Gradual: each run enriches up to ``limit`` un-enriched active channels via
    ``get_channel_details`` (1 quota unit / 50). Also stamps ``category`` from
    the derived niche. New channels get picked up here over time, so the backfill
    and steady-state share one path.
    """
    from src.database.models import TrackedChannel

    pending = (
        session.query(TrackedChannel)
        .filter(TrackedChannel.is_active.is_(True), TrackedChannel.subscriber_count.is_(None))
        .limit(limit)
        .all()
    )
    if not pending:
        return {"enriched": 0}

    niche_of = _derive_channel_niches(session)
    ids = [c.channel_id for c in pending]
    infos = {info.channel_id: info for info in client.get_channel_details(ids)}
    enriched = 0
    for ch in pending:
        info = infos.get(ch.channel_id)
        if not info:
            continue
        ch.subscriber_count = info.subscriber_count
        ch.size_tier = classify_tier(info.subscriber_count)
        ch.category = niche_of.get(ch.channel_id)
        enriched += 1
    session.commit()
    logger.info("coverage.enriched", enriched=enriched, requested=len(pending))
    return {"enriched": enriched}
