"""Collection QA: window hit-rate monitoring (remediation 7.6).

The velocity collector honestly *skips* checkpoint windows it can't sample in
time (no row rather than a mislabelled one) — correct, but it means quota
exhaustion or a stalled scheduler silently erodes the dataset with no alarm:
every job can report "success" while sampling late or never. This module makes
that visible.

The honest metric is **hit-rate over *eligible* windows**: of the checkpoint
windows that (a) have fully closed and (b) the video was already being tracked
before they closed, what fraction did we actually capture. Late-discovered
videos (never eligible for an early window) are excluded so they don't inflate
the miss rate. A drop in the *recent* hit-rate is the early-warning signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Tuple

from src.tracking.video_tracker import CHECKPOINT_WINDOWS


@dataclass
class VideoWindowRow:
    """The minimal per-video fields needed to score window hit-rate."""

    published_at: datetime
    tracking_started: datetime
    flags: Dict[str, bool]  # checkpoint key -> captured?


def summarize_collection_health(
    rows: Iterable[VideoWindowRow],
    now: datetime,
    recent_hours: float = 168.0,  # 7 days
    windows: List[Tuple[str, float, float]] = CHECKPOINT_WINDOWS,
) -> dict:
    """Per-checkpoint eligible/hit/hit-rate over all rows + a recent slice.

    Pure (no DB) so it's unit-testable. ``recent_hours`` defines the trailing
    window — by window *close* time — used for the early-degradation slice.
    """
    per_cp: Dict[str, Dict[str, int]] = {
        key: {"eligible": 0, "hit": 0, "recent_eligible": 0, "recent_hit": 0}
        for key, _t, _g in windows
    }

    for row in rows:
        for key, target, grace in windows:
            close = row.published_at + timedelta(hours=target + grace)
            if now < close:
                continue  # window hasn't closed yet — undecided
            # Eligible only if we were tracking before the window closed.
            if row.tracking_started > close:
                continue
            captured = bool(row.flags.get(key))
            cp = per_cp[key]
            cp["eligible"] += 1
            cp["hit"] += int(captured)
            if (now - close) <= timedelta(hours=recent_hours):
                cp["recent_eligible"] += 1
                cp["recent_hit"] += int(captured)

    checkpoints = []
    for key, _t, _g in windows:
        cp = per_cp[key]
        checkpoints.append(
            {
                "checkpoint": key,
                "eligible": cp["eligible"],
                "hit": cp["hit"],
                "hit_rate": round(cp["hit"] / cp["eligible"], 4) if cp["eligible"] else None,
                "recent_eligible": cp["recent_eligible"],
                "recent_hit": cp["recent_hit"],
                "recent_hit_rate": round(cp["recent_hit"] / cp["recent_eligible"], 4)
                if cp["recent_eligible"]
                else None,
            }
        )

    tot_elig = sum(c["eligible"] for c in checkpoints)
    tot_hit = sum(c["hit"] for c in checkpoints)
    rec_elig = sum(c["recent_eligible"] for c in checkpoints)
    rec_hit = sum(c["recent_hit"] for c in checkpoints)
    return {
        "checkpoints": checkpoints,
        "overall_hit_rate": round(tot_hit / tot_elig, 4) if tot_elig else None,
        "overall_eligible": tot_elig,
        "recent_overall_hit_rate": round(rec_hit / rec_elig, 4) if rec_elig else None,
        "recent_overall_eligible": rec_elig,
        "recent_hours": recent_hours,
    }


def evaluate_health_alert(
    summary: dict, min_hit_rate: float, min_sample: int = 50
) -> List[dict]:
    """Flag checkpoints whose *recent* hit-rate fell below ``min_hit_rate``.

    Only checkpoints with at least ``min_sample`` recent eligible windows are
    judged (a handful of misses on a tiny sample isn't signal).
    """
    alerts = []
    for cp in summary.get("checkpoints", []):
        rate = cp.get("recent_hit_rate")
        if (
            rate is not None
            and cp.get("recent_eligible", 0) >= min_sample
            and rate < min_hit_rate
        ):
            alerts.append(
                {
                    "checkpoint": cp["checkpoint"],
                    "recent_hit_rate": rate,
                    "recent_eligible": cp["recent_eligible"],
                }
            )
    return alerts


CHECKPOINT_ORDER = ["1h", "6h", "24h", "3d", "7d", "14d", "30d"]


def summarize_view_monotonicity(rows: list) -> dict:
    """Count view-count *decreases* between consecutive captured checkpoints.

    ``rows`` = (video_id, checkpoint, view_count). Views can legitimately drop
    (YouTube purges bot views), so isolated decreases are signal, not bugs —
    but a *spike* in the decrease rate means either a platform-wide purge or a
    data bug (mislabeled checkpoints, ID collisions). Pure — unit-testable.
    """
    order = {cp: i for i, cp in enumerate(CHECKPOINT_ORDER)}
    by_video: dict = {}
    for vid, cp, views in rows:
        if cp in order and views is not None:
            by_video.setdefault(vid, []).append((order[cp], views))

    pairs = decreases = 0
    worst: list = []
    for vid, seq in by_video.items():
        seq.sort()
        for (_, v1), (_, v2) in zip(seq, seq[1:]):
            pairs += 1
            if v2 < v1:
                decreases += 1
                drop = (v1 - v2) / v1 if v1 > 0 else 0.0
                if len(worst) < 5:
                    worst.append({"video_id": vid, "from": int(v1), "to": int(v2),
                                  "drop_pct": round(drop * 100, 1)})
    return {
        "checkpoint_pairs": pairs,
        "view_decreases": decreases,
        "decrease_rate": round(decreases / pairs, 4) if pairs else None,
        "examples": worst,
    }


def get_stream_anomalies(session, lookback_days: int = 7) -> dict:
    """View-monotonicity check over recent snapshots (7.6 stream sanity)."""
    from datetime import datetime, timedelta

    from src.database.models import VideoSnapshot

    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    recent_vids = {
        r[0]
        for r in session.query(VideoSnapshot.video_id)
        .filter(VideoSnapshot.captured_at >= cutoff)
        .distinct()
        .all()
    }
    if not recent_vids:
        return summarize_view_monotonicity([])
    rows = (
        session.query(
            VideoSnapshot.video_id, VideoSnapshot.checkpoint, VideoSnapshot.view_count
        )
        .filter(VideoSnapshot.video_id.in_(recent_vids))
        .all()
    )
    return summarize_view_monotonicity([(r[0], r[1], r[2]) for r in rows])


def get_collection_health(session, lookback_days: int = 40, recent_days: int = 7) -> dict:
    """Load recent tracked videos and score window hit-rate (sync DB)."""
    from src.database.models import TrackedVideo

    now = datetime.utcnow()
    cutoff = now - timedelta(days=lookback_days)
    records = (
        session.query(
            TrackedVideo.published_at,
            TrackedVideo.tracking_started,
            TrackedVideo.checkpoint_1h,
            TrackedVideo.checkpoint_6h,
            TrackedVideo.checkpoint_24h,
            TrackedVideo.checkpoint_3d,
            TrackedVideo.checkpoint_7d,
            TrackedVideo.checkpoint_14d,
            TrackedVideo.checkpoint_30d,
        )
        .filter(TrackedVideo.published_at >= cutoff)
        .all()
    )
    keys = ["1h", "6h", "24h", "3d", "7d", "14d", "30d"]
    rows = [
        VideoWindowRow(
            published_at=r[0],
            tracking_started=r[1] or r[0],
            flags=dict(zip(keys, r[2:9])),
        )
        for r in records
        if r[0] is not None
    ]
    summary = summarize_collection_health(rows, now=now, recent_hours=recent_days * 24)
    summary["videos_considered"] = len(rows)
    summary["lookback_days"] = lookback_days
    return summary
