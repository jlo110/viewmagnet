"""Measured view-trajectory benchmarks per niche and format.

"How is my video actually doing?" answered with description rather than
prediction: at each checkpoint, what view counts did the 10th..99th percentile
video in this niche actually reach. Computed from collected snapshots only —
no model, no forecast, nothing to overfit.

Replaces the previous /benchmarks endpoint, which returned invented constants
(``pct_with_face: 78``, ``optimal_upload_hour: 14``) whenever its lookup failed.

Shorts and long-form are always kept separate: their curves differ by an order
of magnitude, so pooling them makes every percentile meaningless.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# A cell needs at least this many videos before its percentiles are published;
# below it the tails are noise and would read as authoritative.
MIN_SAMPLE = 200
CHECKPOINTS = ["1h", "6h", "24h", "3d", "7d", "14d", "30d"]
_PCTS = [0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]


def compute_benchmarks(session, min_sample: int = MIN_SAMPLE) -> dict:
    """Recompute every (niche, is_short, checkpoint) percentile cell.

    One pass over video_snapshots; ``youtube_category_id`` and ``is_short`` live
    on the snapshot rows, so no join is needed. Writes one batch stamped
    ``computed_at``; reads always take the newest batch."""
    from sqlalchemy import text

    from src.database.models import NicheBenchmark

    now = datetime.utcnow()
    rows = session.execute(text("""
        SELECT youtube_category_id AS niche,
               is_short,
               checkpoint,
               count(*) AS n,
               percentile_cont(0.10) WITHIN GROUP (ORDER BY view_count) AS p10,
               percentile_cont(0.25) WITHIN GROUP (ORDER BY view_count) AS p25,
               percentile_cont(0.50) WITHIN GROUP (ORDER BY view_count) AS p50,
               percentile_cont(0.75) WITHIN GROUP (ORDER BY view_count) AS p75,
               percentile_cont(0.90) WITHIN GROUP (ORDER BY view_count) AS p90,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY view_count) AS p95,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY view_count) AS p99
        FROM video_snapshots
        WHERE view_count IS NOT NULL AND is_short IS NOT NULL
        GROUP BY GROUPING SETS ((youtube_category_id, is_short, checkpoint),
                                (is_short, checkpoint))
    """)).all()

    written = 0
    for r in rows:
        if (r.n or 0) < min_sample or r.checkpoint not in CHECKPOINTS:
            continue
        session.add(NicheBenchmark(
            computed_at=now, niche=r.niche, is_short=bool(r.is_short),
            checkpoint=r.checkpoint, n_videos=int(r.n),
            p10=float(r.p10 or 0), p25=float(r.p25 or 0), p50=float(r.p50 or 0),
            p75=float(r.p75 or 0), p90=float(r.p90 or 0), p95=float(r.p95 or 0),
            p99=float(r.p99 or 0),
        ))
        written += 1
    session.commit()
    logger.info("niche_benchmarks.computed", cells=written)
    return {"cells": written, "computed_at": now.isoformat()}


def percentile_for(p10, p25, p50, p75, p90, p95, p99, views: float) -> int:
    """Approximate percentile of ``views`` by linear interpolation between the
    stored breakpoints. Pure — unit-testable, no DB."""
    pts = [(0.0, 0), (p10, 10), (p25, 25), (p50, 50),
           (p75, 75), (p90, 90), (p95, 95), (p99, 99)]
    if views <= pts[0][0]:
        return 0
    for (lo_v, lo_p), (hi_v, hi_p) in zip(pts, pts[1:]):
        if views <= hi_v:
            if hi_v <= lo_v:
                return hi_p
            frac = (views - lo_v) / (hi_v - lo_v)
            return int(round(lo_p + frac * (hi_p - lo_p)))
    return 99


def get_benchmark(session, niche: Optional[str], is_short: bool,
                  checkpoint: str) -> Optional[dict]:
    """Newest published cell for this niche/format/checkpoint.

    Falls back to the all-niches cell (niche IS NULL) when the specific niche
    lacks a large enough sample — never to invented numbers."""
    from sqlalchemy import select

    from src.database.models import NicheBenchmark

    latest = session.execute(
        select(NicheBenchmark.computed_at)
        .order_by(NicheBenchmark.computed_at.desc()).limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return None

    def _fetch(n):
        return session.execute(
            select(NicheBenchmark).where(
                NicheBenchmark.computed_at == latest,
                NicheBenchmark.niche.is_(None) if n is None else NicheBenchmark.niche == n,
                NicheBenchmark.is_short.is_(is_short),
                NicheBenchmark.checkpoint == checkpoint)
        ).scalars().first()

    row = _fetch(niche) or (_fetch(None) if niche is not None else None)
    if row is None:
        return None
    return {
        "niche": row.niche, "is_short": row.is_short, "checkpoint": row.checkpoint,
        "n_videos": row.n_videos, "computed_at": row.computed_at.isoformat() + "Z",
        "pooled": row.niche is None and niche is not None,
        "percentiles": {"p10": row.p10, "p25": row.p25, "p50": row.p50,
                        "p75": row.p75, "p90": row.p90, "p95": row.p95, "p99": row.p99},
    }


def rank_video(session, views: float, niche: Optional[str], is_short: bool,
               checkpoint: str) -> Optional[dict]:
    """Where ``views`` sits against this niche/format at this checkpoint."""
    b = get_benchmark(session, niche, is_short, checkpoint)
    if b is None:
        return None
    p = b["percentiles"]
    pct = percentile_for(p["p10"], p["p25"], p["p50"], p["p75"],
                         p["p90"], p["p95"], p["p99"], views)
    return {**b, "views": views, "percentile": pct,
            "vs_median": round(views / p["p50"], 2) if p["p50"] else None}
