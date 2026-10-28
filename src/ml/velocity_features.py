"""Velocity feature transforms — the single source of truth shared by the
training scripts AND live serving (durability grader).

These were defined in ``scripts/`` (train_all_velocity_models / evaluate_models),
but the prod Docker image ships only ``src/`` + ``scripts/fetch_ml_artifacts.py``
— so serving code that imported them crashed with ``No module named
'scripts.evaluate_models'``. Living in ``src/`` fixes that and guarantees
serving == training (same transforms). The scripts now re-export from here.
"""
from __future__ import annotations

import numpy as np

CHECKPOINTS = ["1h", "6h", "24h", "3d", "7d", "14d", "30d"]


def get_features_for_stage(df, from_checkpoint: str) -> list:
    """Feature column names legitimately available at ``from_checkpoint``."""
    from_idx = CHECKPOINTS.index(from_checkpoint)
    available = CHECKPOINTS[: from_idx + 1]
    features: list = []
    for cp in available:
        features.extend([f"views_{cp}", f"vph_{cp}", f"likes_{cp}", f"comments_{cp}"])
    prev = None
    for cp in available:
        if prev:
            features.append(f"growth_{prev}_{cp}")
            features.append(f"vph_decay_{prev}_{cp}")
        prev = cp
    if "1h" in available and from_checkpoint != "1h":
        features.append(f"growth_1h_{from_checkpoint}")
    for cp in available:
        features.extend([f"like_rate_{cp}", f"comment_rate_{cp}"])
    for cp in available:
        features.extend([f"log_views_{cp}", f"log_vph_{cp}"])
    features.extend(["log_subscribers", f"views_per_sub_{from_checkpoint}", "duration_seconds"])
    return features


def build_features(df):
    """Derive growth/decay/engagement/log + channel features on the snapshot pivot."""
    df = df.copy()
    for i, cp in enumerate(CHECKPOINTS[1:], 1):
        prev = CHECKPOINTS[i - 1]
        views_col, prev_views = f"views_{cp}", f"views_{prev}"
        vph_col, prev_vph = f"vph_{cp}", f"vph_{prev}"
        if views_col in df.columns and prev_views in df.columns:
            df[f"growth_{prev}_{cp}"] = df[views_col] / df[prev_views].clip(lower=1)
        if vph_col in df.columns and prev_vph in df.columns:
            df[f"vph_decay_{prev}_{cp}"] = df[vph_col] / df[prev_vph].clip(lower=0.01)
    for cp in CHECKPOINTS[1:]:
        views_col = f"views_{cp}"
        if views_col in df.columns and "views_1h" in df.columns:
            df[f"growth_1h_{cp}"] = df[views_col] / df["views_1h"].clip(lower=1)
    for cp in CHECKPOINTS:
        views_col, likes_col, comments_col = f"views_{cp}", f"likes_{cp}", f"comments_{cp}"
        if views_col in df.columns:
            if likes_col in df.columns:
                df[f"like_rate_{cp}"] = df[likes_col] / df[views_col].clip(lower=1)
            if comments_col in df.columns:
                df[f"comment_rate_{cp}"] = df[comments_col] / df[views_col].clip(lower=1)
    for cp in CHECKPOINTS:
        for metric in ["views", "vph"]:
            col = f"{metric}_{cp}"
            if col in df.columns:
                df[f"log_{col}"] = np.log1p(df[col])
    df["log_subscribers"] = np.log1p(df["subscribers"].fillna(0)) if "subscribers" in df.columns else 0.0
    for cp in CHECKPOINTS:
        views_col = f"views_{cp}"
        if views_col in df.columns and "subscribers" in df.columns:
            df[f"views_per_sub_{cp}"] = df[views_col] / df["subscribers"].clip(lower=1)
    return df


def add_channel_features(df):
    """Leave-one-out per-channel baseline (grouped-CV safe): for each checkpoint,
    the mean of log-views over the channel's OTHER videos, and this video's
    residual vs that baseline (``views_vs_chanbase_*``)."""
    df = df.copy()
    for cp in CHECKPOINTS:
        col = f"views_{cp}"
        if col not in df.columns:
            continue
        logv = np.log1p(df[col].astype(float))
        grp = logv.groupby(df["channel_id"])
        cnt = grp.transform("count")
        tot = grp.transform("sum")
        loo = (tot - logv) / (cnt - 1).clip(lower=1)
        loo = loo.where(cnt > 1, logv)
        df[f"chanbase_logviews_{cp}"] = loo
        df[f"views_vs_chanbase_{cp}"] = logv - loo
    return df
