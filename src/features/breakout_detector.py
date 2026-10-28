"""Breakout detector (remediation 7.3) — productionizes the validated approach.

`scripts/evaluate_breakout.py` showed that whether a video **breaks out**
(top-quartile channel-relative overperformance at 24h) is highly predictable from
early signals — channel-grouped CV AUC **0.94 at 6h, 0.86 at 1h** — and that
~all of the signal is *"is this video outpacing its channel's own norm early."*
A single feature (early views vs the channel baseline) already gives AUC 0.85–0.93;
a full XGBoost adds only +0.01–0.016.

So the served detector is deliberately **simple and explainable**:

    score = log1p(views_at_checkpoint) − channel_baseline_log_views

where the channel baseline is the leave-one-out mean of the channel's other
tracked videos' log-views at the same checkpoint. A saved **isotonic calibration**
(fit on real outcomes by ``scripts/train_breakout_calibrator.py``) maps that score
to an honest **P(breakout)** — no heavy model, ~99% of the achievable AUC, and a
probability we can actually show a user (remediation 6.3).

The engine is channel-source-agnostic: callers supply the baseline (or use
``channel_baseline_logviews`` for tracked channels), so it works for both the
collection's tracked channels and a connected user's own video history.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_CALIBRATOR = Path("data/models/breakout_calibrator.json")

# Default checkpoint the detector scores at — 6h is the validated sweet spot
# (AUC ~0.94); 1h gives an earlier, slightly-less-certain call.
DEFAULT_CHECKPOINT = "6h"


def calibrator_path(checkpoint: str) -> Path:
    """Per-checkpoint calibrator artifact; the 6h default keeps its legacy name.

    Score→probability mapping differs by checkpoint (a 2x-the-norm signal at 1h
    is weaker evidence than at 6h), so each early checkpoint gets its own
    isotonic fit (``scripts/train_breakout_calibrator.py --from <cp>``).
    """
    if checkpoint == DEFAULT_CHECKPOINT:
        return DEFAULT_CALIBRATOR
    return Path(f"data/models/breakout_calibrator_{checkpoint}.json")


def breakout_score(views: float, baseline_log_views: float) -> float:
    """How far the video is outpacing its channel's norm, in log-views.

    Positive = ahead of the channel's typical early performance; the single
    feature that carries the breakout signal.
    """
    return math.log1p(max(0.0, float(views))) - float(baseline_log_views)


def channel_baseline_logviews(
    session,
    channel_id: str,
    checkpoint: str,
    exclude_video_id: Optional[str] = None,
) -> Optional[float]:
    """Leave-one-out mean of the channel's tracked videos' log-views at ``checkpoint``.

    Returns ``None`` when the channel has no other sampled videos at that
    checkpoint (can't form a baseline). Sync DB.
    """
    import numpy as np
    from sqlalchemy import select

    from src.database.models import TrackedVideo, VideoSnapshot

    rows = session.execute(
        select(VideoSnapshot.video_id, VideoSnapshot.view_count)
        .join(TrackedVideo, TrackedVideo.video_id == VideoSnapshot.video_id)
        .where(
            TrackedVideo.channel_id == channel_id,
            VideoSnapshot.checkpoint == checkpoint,
        )
    ).all()
    vals = [
        math.log1p(max(0, vc))
        for vid, vc in rows
        if exclude_video_id is None or vid != exclude_video_id
    ]
    if not vals:
        return None
    return float(np.mean(vals))


@dataclass
class BreakoutCalibrator:
    """Isotonic score→probability mapping, stored as interpolation knots.

    Loading needs no sklearn (just ``np.interp``); fitting (in the trainer) uses
    ``sklearn.isotonic``. ``meta`` records what it was fit on (checkpoints,
    breakout quantile, AUC, n) for provenance.
    """

    x: List[float]  # ascending score knots
    y: List[float]  # P(breakout) at each knot, non-decreasing in [0, 1]
    meta: dict

    @classmethod
    def load(cls, path: Path = DEFAULT_CALIBRATOR) -> Optional["BreakoutCalibrator"]:
        p = Path(path)
        if not p.exists():
            logger.info("breakout.calibrator_missing", path=str(p))
            return None
        d = json.loads(p.read_text())
        return cls(x=d["x"], y=d["y"], meta=d.get("meta", {}))

    def probability(self, score: float) -> float:
        import numpy as np

        if not self.x:
            return float("nan")
        return float(np.clip(np.interp(score, self.x, self.y), 0.0, 1.0))

    def save(self, path: Path = DEFAULT_CALIBRATOR) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"x": self.x, "y": self.y, "meta": self.meta}, indent=1))


# Measured within-niche grouped-CV AUC of the early breakout signal
# (scripts/evaluate_breakout_by_niche.py, 2026-06-13). Breakout is NOT
# niche-invariant: News is highly callable early (0.96), Gaming much less
# (0.84). We DON'T build per-niche models (the channel-relative score is
# near-ceiling) — we surface this as detection *confidence* so a Gaming flag is
# qualified differently from a News flag. Keyed by youtube_category_id.
NICHE_DETECTION_AUC = {
    "25": 0.958,  # News
    "17": 0.938,  # Sports
    "22": 0.918,  # People & Blogs
    "24": 0.915,  # Entertainment
    "26": 0.890,  # Howto & Style
    "27": 0.873,  # Education
    "28": 0.859,  # Science & Tech
    "20": 0.843,  # Gaming
}
GLOBAL_DETECTION_AUC = 0.933


def detection_confidence(category_id: Optional[str]) -> dict:
    """How reliable the early breakout call is for this niche (measured AUC).

    ``level``: high (AUC ≥ 0.92) / moderate (≥ 0.87) / lower (< 0.87). Falls
    back to the global AUC for unknown/missing categories.
    """
    auc = NICHE_DETECTION_AUC.get(category_id or "", GLOBAL_DETECTION_AUC)
    level = "high" if auc >= 0.92 else ("moderate" if auc >= 0.87 else "lower")
    return {"detection_auc": auc, "confidence": level}


# Probability bands for the user-facing alert. Tuned conservative — "breakout"
# should mean "act now" (make a Short, pin a comment, promote).
def classify(probability: float) -> str:
    if probability != probability:  # NaN
        return "unknown"
    if probability >= 0.70:
        return "breakout"
    if probability >= 0.40:
        return "heating_up"
    return "normal"


@dataclass
class BreakoutAssessment:
    score: float
    probability: Optional[float]
    level: str
    checkpoint: str
    baseline_log_views: float
    views: float


def assess(
    views: float,
    baseline_log_views: float,
    checkpoint: str = DEFAULT_CHECKPOINT,
    calibrator: Optional[BreakoutCalibrator] = None,
) -> BreakoutAssessment:
    """Score a video's early performance against its channel baseline → assessment.

    If no calibrator is available, returns the raw score with ``probability=None``
    and a level derived from the score sign (still useful, just uncalibrated).
    """
    score = breakout_score(views, baseline_log_views)
    if calibrator is not None:
        prob = calibrator.probability(score)
        level = classify(prob)
    else:
        prob = None
        # Uncalibrated fallback: score > ~0.7 (≈2x the channel norm) = heating up.
        level = "breakout" if score >= 1.2 else ("heating_up" if score >= 0.5 else "normal")
    return BreakoutAssessment(
        score=score,
        probability=prob,
        level=level,
        checkpoint=checkpoint,
        baseline_log_views=float(baseline_log_views),
        views=float(views),
    )


# ---------------------------------------------------------------------------
# Batch detection over the tracked set (live, no users required)
# ---------------------------------------------------------------------------
def rank_breakouts(
    rows: list,
    checkpoint: str,
    calibrator: Optional[BreakoutCalibrator],
    min_probability: float = 0.5,
    limit: int = 100,
    min_views: float = 1000.0,
    min_channel_videos: int = 3,
) -> List[dict]:
    """Score + rank videos for breakout from ``(video_id, channel_id, title,
    views, age_hours)`` rows, building per-channel leave-one-out baselines.

    Pure (no DB) so it's testable. Sanity gates that keep the feed meaningful:
    ``min_views`` (a channel-relative spike on 33 views isn't a real breakout —
    require absolute traction) and ``min_channel_videos`` (need a stable baseline,
    not 1–2 noisy siblings). Sorted by P(breakout) desc; uncalibrated → score desc.
    """
    import math
    from collections import defaultdict

    csum: dict = defaultdict(float)
    ccount: dict = defaultdict(int)
    logv: dict = {}
    for vid, ch, _title, views, _age in rows:
        lv = math.log1p(max(0.0, float(views)))
        logv[vid] = lv
        csum[ch] += lv
        ccount[ch] += 1

    out: List[dict] = []
    for vid, ch, title, views, age in rows:
        if ccount[ch] < max(2, min_channel_videos):
            continue
        if float(views) < min_views:
            continue
        baseline = (csum[ch] - logv[vid]) / (ccount[ch] - 1)
        a = assess(views, baseline, checkpoint=checkpoint, calibrator=calibrator)
        if a.probability is not None and a.probability < min_probability:
            continue
        out.append(
            {
                "video_id": vid,
                "channel_id": ch,
                "title": title,
                "views": float(views),
                "age_hours": round(float(age), 1) if age is not None else None,
                "score": round(a.score, 3),
                "probability": round(a.probability, 3) if a.probability is not None else None,
                "level": a.level,
            }
        )
    # Sort by P(breakout) then score — score breaks ties when probabilities
    # saturate at the calibrator's top knot (so the biggest spikes rank first).
    out.sort(
        key=lambda r: (r["probability"] if r["probability"] is not None else -1.0, r["score"]),
        reverse=True,
    )
    return out[:limit]


def detect_live_breakouts(
    session,
    checkpoint: str = DEFAULT_CHECKPOINT,
    min_probability: float = 0.5,
    max_age_hours: float = 48.0,
    limit: int = 100,
    min_views: float = 1000.0,
    min_channel_videos: int = 3,
    exclude_shorts: bool = True,
    calibrator: Optional[BreakoutCalibrator] = None,
) -> List[dict]:
    """Find tracked videos breaking out *now* — recent uploads whose ``checkpoint``
    performance is far above their channel's norm.

    Works entirely on the tracked collection (no users needed): a trend/competitor
    breakout feed. Recent = published within ``max_age_hours`` so the call is still
    actionable. One query builds the rows; per-channel baselines + sanity gates
    (``min_views``, ``min_channel_videos``) are applied in ``rank_breakouts``.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import select

    from src.database.models import TrackedVideo, VideoSnapshot

    if calibrator is None:
        calibrator = BreakoutCalibrator.load(calibrator_path(checkpoint))
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    records = session.execute(
        select(
            VideoSnapshot.video_id,
            TrackedVideo.channel_id,
            TrackedVideo.title,
            VideoSnapshot.view_count,
            TrackedVideo.published_at,
            VideoSnapshot.is_short,
            VideoSnapshot.duration_seconds,
        )
        .join(TrackedVideo, TrackedVideo.video_id == VideoSnapshot.video_id)
        .where(VideoSnapshot.checkpoint == checkpoint)
    ).all()

    now = datetime.utcnow()
    rows = [
        (
            vid,
            ch,
            title,
            vc,
            (now - pub).total_seconds() / 3600 if pub else None,
        )
        for vid, ch, title, vc, pub, is_short, dur in records
        if pub is not None and pub >= cutoff
        # Exclude Shorts from the feed AND the per-channel baseline: their early-view
        # dynamics differ and a flood of low-view Shorts drags the baseline down,
        # surfacing media-promo Shorts as false "breakouts" (and inflating scores).
        and not (exclude_shorts and (bool(is_short) or (dur is not None and dur < 60)))
    ]
    return rank_breakouts(
        rows, checkpoint=checkpoint, calibrator=calibrator,
        min_probability=min_probability, limit=limit,
        min_views=min_views, min_channel_videos=min_channel_videos,
    )
