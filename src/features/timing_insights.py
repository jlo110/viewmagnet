"""Measured publish-timing effects and topic-wave duration.

Two descriptive findings from the collected set, both deliberately modest:

**Publish timing** — for each channel we rank its own videos by 24h views, call
the top 20% a "hit", then ask how the hit rate varies by publish hour. Ranking
*within channel* means channel size cannot confound it. Measured over 254k
videos the spread is ~5 points (best hour ~24%, worst ~19%) against a 20%
baseline: real at this sample size, but far smaller than the "best time to post"
claims the industry sells. It is also **correlational** — channels do not
randomise their publish times, so off-hour uploads may simply be different
content (premieres, event coverage). This replaces the fabricated
``optimal_upload_hour: 14`` the old benchmarks endpoint used to serve.

**Topic waves** — topics are chained across momentum batches by membership
overlap (labels drift as the leader video changes, so label matching splits one
topic into several). Median observed wave lasts ~0.8 days, p90 ~3.3: if a topic
is rising you have about a day, not a week. Note the topic clusterer uses a 48h
window, which bounds how long a wave can be *observed* — long-lived values mean
new uploads kept joining.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# A channel needs this many tracked videos before its internal ranking is
# meaningful; a bucket needs this many videos before it is published.
MIN_VIDEOS_PER_CHANNEL = 10
MIN_BUCKET_SAMPLE = 300
HIT_PERCENTILE = 0.8  # top 20% of a channel's own videos
# Chaining threshold for "same topic across batches".
WAVE_MIN_JACCARD = 0.2


def compute_timing_benchmarks(session, min_sample: int = MIN_BUCKET_SAMPLE) -> dict:
    """Recompute hour-of-day and day-of-week hit rates, per niche and pooled."""
    from sqlalchemy import text

    from src.database.models import TimingBenchmark

    now = datetime.utcnow()
    rows = session.execute(text(f"""
        WITH v AS (
          SELECT tv.channel_id,
                 s.youtube_category_id AS niche,
                 s.is_short,
                 extract(hour FROM tv.published_at)::int AS hour_b,
                 extract(dow  FROM tv.published_at)::int AS dow_b,
                 percent_rank() OVER (PARTITION BY tv.channel_id
                                      ORDER BY s.view_count) AS pr
          FROM video_snapshots s
          JOIN tracked_videos tv ON tv.video_id = s.video_id
          WHERE s.checkpoint = '24h' AND s.view_count > 0 AND s.is_short IS NOT NULL
        ),
        ch AS (
          SELECT channel_id FROM v GROUP BY channel_id
          HAVING count(*) >= {MIN_VIDEOS_PER_CHANNEL}
        ),
        f AS (SELECT v.* FROM v JOIN ch USING (channel_id))
        SELECT 'hour' AS dim, hour_b AS bucket, niche, is_short,
               count(*) AS n, avg((pr >= {HIT_PERCENTILE})::int) AS hit
        FROM f GROUP BY GROUPING SETS ((hour_b, niche, is_short), (hour_b, is_short))
        UNION ALL
        SELECT 'dow', dow_b, niche, is_short,
               count(*), avg((pr >= {HIT_PERCENTILE})::int)
        FROM f GROUP BY GROUPING SETS ((dow_b, niche, is_short), (dow_b, is_short))
    """)).all()

    written = 0
    for r in rows:
        if (r.n or 0) < min_sample:
            continue
        session.add(TimingBenchmark(
            computed_at=now, dimension=r.dim, bucket=int(r.bucket),
            niche=r.niche, is_short=bool(r.is_short),
            n_videos=int(r.n), hit_rate=round(float(r.hit or 0), 4)))
        written += 1
    session.commit()
    logger.info("timing_benchmarks.computed", cells=written)
    return {"cells": written, "computed_at": now.isoformat()}


def get_timing(session, dimension: str = "hour", niche: Optional[str] = None,
               is_short: bool = False) -> Optional[dict]:
    """Newest measured hit-rate curve for a dimension, with its caveats attached."""
    from sqlalchemy import select

    from src.database.models import TimingBenchmark

    latest = session.execute(
        select(TimingBenchmark.computed_at)
        .order_by(TimingBenchmark.computed_at.desc()).limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return None

    def _fetch(n):
        return session.execute(
            select(TimingBenchmark).where(
                TimingBenchmark.computed_at == latest,
                TimingBenchmark.dimension == dimension,
                TimingBenchmark.is_short.is_(is_short),
                TimingBenchmark.niche.is_(None) if n is None
                else TimingBenchmark.niche == n)
            .order_by(TimingBenchmark.bucket)
        ).scalars().all()

    rows = _fetch(niche) or (_fetch(None) if niche is not None else [])
    if not rows:
        return None
    buckets = [{"bucket": r.bucket, "n": r.n_videos,
                "hit_rate": r.hit_rate} for r in rows]
    best = max(buckets, key=lambda b: b["hit_rate"])
    worst = min(buckets, key=lambda b: b["hit_rate"])
    return {
        "dimension": dimension, "niche": rows[0].niche, "is_short": is_short,
        "pooled": rows[0].niche is None and niche is not None,
        "computed_at": latest.isoformat() + "Z",
        "baseline_hit_rate": round(1 - HIT_PERCENTILE, 2),
        "buckets": buckets,
        "best": best, "worst": worst,
        "spread_points": round(100 * (best["hit_rate"] - worst["hit_rate"]), 1),
        "caveat": ("Correlational, not causal: channels don't randomise publish "
                   "times, so off-hour uploads may simply be different content. "
                   "Hours are UTC. Measured within each channel, so channel size "
                   "cannot confound it."),
    }


def wave_stats(session, min_jaccard: float = WAVE_MIN_JACCARD) -> Optional[dict]:
    """How long a topic wave lasts, from the momentum history.

    Topics are chained across batches by membership overlap — labels drift when
    the leader video changes, which would split one wave into several."""
    from sqlalchemy import select

    from src.database.models import TopicMomentum

    rows = session.execute(
        select(TopicMomentum.computed_at, TopicMomentum.video_ids)
        .order_by(TopicMomentum.computed_at)
    ).all()
    if not rows:
        return None

    batches: dict = {}
    for ts, vids in rows:
        batches.setdefault(ts, []).append(set(json.loads(vids or "[]")))

    chains: list = []
    active: list = []
    for ts in sorted(batches):
        used, nxt = set(), []
        for vids in batches[ts]:
            best, best_j = None, 0.0
            for a in active:
                inter = len(vids & a["vids"])
                if not inter:
                    continue
                j = inter / max(1, len(vids | a["vids"]))
                if j > best_j:
                    best, best_j = a, j
            if best is not None and best_j >= min_jaccard and id(best) not in used:
                best.update(vids=vids, last=ts, n=best["n"] + 1)
                used.add(id(best))
                nxt.append(best)
            else:
                nxt.append({"vids": vids, "first": ts, "last": ts, "n": 1})
        chains.extend(a for a in active if a not in nxt)
        active = nxt
    chains.extend(active)

    lives = sorted((c["last"] - c["first"]).total_seconds() / 86400
                   for c in chains if c["n"] >= 2)
    if not lives:
        return None
    n = len(lives)
    return {
        "waves_tracked": len(chains),
        "waves_lasting_multiple_batches": n,
        "median_days": round(lives[n // 2], 1),
        "p75_days": round(lives[int(n * 0.75)], 1),
        "p90_days": round(lives[int(n * 0.90)], 1),
        "max_days": round(lives[-1], 1),
        "caveat": ("The topic clusterer uses a 48h window, so a long-lived wave "
                   "means new uploads kept joining it. Most waves are short: act "
                   "within about a day, not a week."),
    }
