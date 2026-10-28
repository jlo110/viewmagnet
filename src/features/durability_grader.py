"""Serve the breakout DURABILITY grader (sustain vs flash) on live videos.

Stage 2 of Breakout Radar. Detection (the channel-relative residual) tells you a
video is breaking out; this tells you whether it's likely to SUSTAIN or just
flash — the multi-signal signal validated 2026-06-21 (24h→7d grader AUC 0.823,
no longer provisional; memory: velocity-models-no-lift).

Serving == training: we reuse the exact feature transforms the grader was trained
on (``build_features`` + ``add_channel_features``); only the data LOAD is swapped
for a channel-filtered query (the training loader pulls the whole 208k-row set).
Fails soft everywhere — a missing artifact / thin data yields no badge, never an
error.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# One grader per early checkpoint (each predicts sustain-to-7d from that horizon).
_ARTIFACTS = {
    "6h": Path("data/models/sustain_grader_6h_7d.pkl"),
    "24h": Path("data/models/sustain_grader_24h_7d.pkl"),
}
_graders: dict = {}  # from_cp -> {"model", "feature_cols", ...} | False


def _load(from_cp: str = "24h") -> Optional[dict]:
    """Load the grader for the given early checkpoint (cached). Falls back to the
    24h grader if the requested one is missing (1h breakouts use the 6h grader)."""
    key = "6h" if from_cp in ("1h", "6h") else "24h"
    if key not in _graders:
        try:
            import pickle

            p = _ARTIFACTS[key]
            g = pickle.loads(p.read_bytes()) if p.exists() else False
            if g:
                logger.info("durability.loaded", from_cp=key, cv_auc=g.get("cv_auc"),
                            provisional=g.get("provisional"))
            _graders[key] = g
        except Exception as e:  # noqa: BLE001
            logger.warning("durability.load_failed", from_cp=key, error=str(e)[:120])
            _graders[key] = False
    g = _graders.get(key)
    if not g and key != "24h":  # fall back to the 24h grader
        return _load("24h")
    return g or None


def _label(prob: float) -> str:
    if prob >= 0.6:
        return "likely_to_sustain"
    if prob < 0.4:
        return "could_flash"
    return "uncertain"


def _load_channel_frame(session, channel_ids: list[str]):
    """Filtered mirror of scripts.evaluate_models.load_tracked_data — only the
    given channels' videos, so per-channel baselines are still correct."""
    import numpy as np
    import pandas as pd
    from sqlalchemy import func

    from src.database.models import ChannelSnapshot, TrackedVideo, VideoSnapshot

    vids = [r[0] for r in session.query(TrackedVideo.video_id).filter(
        TrackedVideo.channel_id.in_(channel_ids)).all()]
    if not vids:
        return pd.DataFrame()
    snaps = session.query(
        VideoSnapshot.video_id, VideoSnapshot.checkpoint, VideoSnapshot.view_count,
        VideoSnapshot.like_count, VideoSnapshot.comment_count, VideoSnapshot.views_per_hour,
    ).filter(VideoSnapshot.video_id.in_(vids)).all()
    videos = session.query(
        TrackedVideo.video_id, TrackedVideo.channel_id, TrackedVideo.published_at,
    ).filter(TrackedVideo.channel_id.in_(channel_ids)).all()
    subs = session.query(
        ChannelSnapshot.channel_id, func.max(ChannelSnapshot.subscriber_count),
    ).filter(ChannelSnapshot.channel_id.in_(channel_ids)).group_by(ChannelSnapshot.channel_id).all()

    snap_df = pd.DataFrame(snaps, columns=["video_id", "checkpoint", "views", "likes", "comments", "vph"])
    if snap_df.empty:
        return snap_df
    video_df = pd.DataFrame(videos, columns=["video_id", "channel_id", "published_at"])
    video_df["channel_id"] = video_df["channel_id"].astype(str)
    pub = pd.to_datetime(video_df["published_at"], errors="coerce")
    video_df["upload_hour_sin"] = np.sin(2 * np.pi * pub.dt.hour / 24)
    video_df["upload_hour_cos"] = np.cos(2 * np.pi * pub.dt.hour / 24)
    video_df["upload_dow"] = pub.dt.dayofweek.astype(float)
    video_df = video_df.sort_values("published_at")
    gap = video_df.groupby("channel_id")["published_at"].diff().dt.total_seconds() / 3600
    video_df["log_upload_gap_hours"] = np.log1p(gap)
    video_df = video_df.drop(columns=["published_at"])

    pivot = snap_df.pivot_table(index="video_id", columns="checkpoint",
                                values=["views", "likes", "comments", "vph"], aggfunc="first")
    pivot.columns = [f"{c[0]}_{c[1]}" for c in pivot.columns]
    pivot = pivot.reset_index().merge(video_df, on="video_id", how="left")
    subs_df = pd.DataFrame(subs, columns=["channel_id", "subscribers"])
    subs_df["channel_id"] = subs_df["channel_id"].astype(str)
    pivot = pivot.merge(subs_df, on="channel_id", how="left")
    pivot["duration_seconds"] = np.nan
    return pivot


def grade(session, video_ids: list[str], checkpoint: str = "24h") -> dict:
    """{video_id: {"probability", "label"}} for videos that have reached the
    grader's from-checkpoint; "too_early" for younger ones. {} if no model.
    ``checkpoint`` selects the grader (6h breakouts use the 6h→7d grader)."""
    g = _load(checkpoint)
    if not g or not video_ids:
        return {}
    from_cp = g.get("from_cp", "24h")
    from_views = f"views_{from_cp}"
    try:
        import numpy as np

        from src.database.models import TrackedVideo
        from src.ml.velocity_features import add_channel_features, build_features

        targets = set(video_ids)
        ch_rows = session.query(TrackedVideo.channel_id).filter(
            TrackedVideo.video_id.in_(list(targets))).distinct().all()
        channel_ids = [c[0] for c in ch_rows if c[0]]
        if not channel_ids:
            return {}
        df = add_channel_features(build_features(_load_channel_frame(session, channel_ids)))
        if df.empty:
            return {}
        feat_cols = [c for c in g["feature_cols"] if c in df.columns]
        sub = df[df["video_id"].isin(targets)]
        out: dict = {}
        for _, row in sub.iterrows():
            vid = row["video_id"]
            if from_views not in df.columns or row.get(from_views) != row.get(from_views) or not row.get(from_views):
                out[vid] = {"probability": None, "label": "too_early"}
                continue
            x = np.asarray([[float(row.get(c) or 0) for c in feat_cols]], dtype=float)
            x = np.nan_to_num(x, posinf=0.0, neginf=0.0)
            prob = float(g["model"].predict_proba(x)[0, 1])
            out[vid] = {"probability": round(prob, 3), "label": _label(prob)}
        # Targets not in the frame at all → too early / not collected yet.
        for vid in targets:
            out.setdefault(vid, {"probability": None, "label": "too_early"})
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("durability.grade_failed", error=str(e)[:160])
        return {}
