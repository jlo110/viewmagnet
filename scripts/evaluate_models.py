"""Honest evaluation harness for the velocity models.

Why this exists
---------------
The existing trainers (``train_velocity_model.py``, ``train_all_velocity_models.py``)
report "accuracy" as ``100 - MAPE`` and a very high R² obtained from a plain
``train_test_split(random_state=42)``. Two problems make those numbers
misleading:

1. **Channel leakage.** A random split puts videos from the *same channel* in
   both train and test. With channel-context features (subscribers, etc.) the
   model partly memorizes per-channel baselines, inflating the score. Real
   traffic includes brand-new channels. This harness splits with
   ``GroupKFold`` grouped by ``channel_id`` so a channel is never in both sides.

2. **No baseline.** Predicting day-30 views from day-7 views is dominated by
   autocorrelation — views barely change. A naive "persistence" predictor
   (tomorrow ≈ today) already scores a high R². So a model is only worth its
   complexity if it beats that baseline. This harness reports **lift over the
   naive baseline** alongside MAPE.

What it reports, per ``from_cp → to_cp`` horizon
------------------------------------------------
- grouped-CV **MAPE** and **R²** for the model
- naive-baseline MAPE (persistence: ``views_to ≈ views_from``)
- a smarter baseline (persistence × median historical growth from train folds)
- **lift** = (baseline_MAPE − model_MAPE) / baseline_MAPE  (higher is better;
  ≤ 0 means the model does not beat the baseline)
- with ``--compare-splits``: random-CV MAPE vs grouped-CV MAPE, so the
  leakage gap is visible

Usage
-----
    python -m scripts.evaluate_models                 # grouped CV + baselines
    python -m scripts.evaluate_models --compare-splits
    python -m scripts.evaluate_models --folds 5

Requires the training database (``DATABASE_URL``) to contain VideoSnapshot
data. With an empty/dev DB it prints "insufficient data" per horizon and exits
cleanly. The pure metric/baseline helpers are unit-tested in
``tests/test_ml/test_evaluate_models.py`` so the logic is verified without a DB.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

# Reuse the exact feature construction the trainers use so the evaluation
# reflects the production pipeline (import-safe: their main() is guarded).
from scripts.train_all_velocity_models import (
    build_features,
    get_features_for_stage,
    load_all_data,
)

CHECKPOINTS = ["1h", "6h", "24h", "3d", "7d", "14d", "30d"]
MIN_SAMPLES = 100
MIN_GROUPS = 5


def load_tracked_data():
    """Load velocity pairs from the rebuilt collection (tracked_videos + snapshots).

    The original ``load_all_data`` sources ``channel_id`` from the ``Video``
    benchmark table, but the rebuilt velocity videos live in ``tracked_videos`` —
    so ``channel_id`` came back NaN and the grouped-CV mask dropped every row
    (the bug flagged in remediation 2.1). This sources ``channel_id`` from
    ``tracked_videos``, where it actually exists, and pivots all checkpoints
    (incl. 1h/6h) so the early, upload-time-useful horizons can be evaluated.
    Subscriber/duration joins are left NaN for now (``build_features`` tolerates
    it); the early-engagement features are what carry these horizons.
    """
    from sqlalchemy import func

    from src.database.connection import get_session
    from src.database.models import ChannelSnapshot, TrackedVideo, VideoSnapshot

    with get_session() as session:
        snapshots = session.query(
            VideoSnapshot.video_id,
            VideoSnapshot.checkpoint,
            VideoSnapshot.view_count,
            VideoSnapshot.like_count,
            VideoSnapshot.comment_count,
            VideoSnapshot.views_per_hour,
        ).all()
        videos = session.query(
            TrackedVideo.video_id, TrackedVideo.channel_id, TrackedVideo.published_at
        ).all()
        # Subscriber count per channel (max across the daily snapshots ≈ current).
        subs = (
            session.query(
                ChannelSnapshot.channel_id,
                func.max(ChannelSnapshot.subscriber_count),
            )
            .group_by(ChannelSnapshot.channel_id)
            .all()
        )

    snap_df = pd.DataFrame(
        snapshots, columns=["video_id", "checkpoint", "views", "likes", "comments", "vph"]
    )
    print(f"   Total snapshots: {len(snap_df):,}")
    if snap_df.empty:
        return snap_df
    video_df = pd.DataFrame(videos, columns=["video_id", "channel_id", "published_at"])
    video_df["channel_id"] = video_df["channel_id"].astype(str)
    # Derived upload-timing features (8.5): hour-of-day and day-of-week are
    # known pre-upload, so they're legitimate at every horizon. Cyclic-encode
    # the hour so 23h and 0h are neighbors.
    pub = pd.to_datetime(video_df["published_at"], errors="coerce")
    video_df["upload_hour_sin"] = np.sin(2 * np.pi * pub.dt.hour / 24)
    video_df["upload_hour_cos"] = np.cos(2 * np.pi * pub.dt.hour / 24)
    video_df["upload_dow"] = pub.dt.dayofweek.astype(float)
    # Gap since the channel's previous upload (hours, log1p). Cadence is both
    # a channel trait and a per-video signal ("first upload in 3 weeks" lands
    # differently than "4th today"). Left-censored early in collection (a
    # channel's first tracked video has no previous one -> NaN -> filled 0).
    video_df = video_df.sort_values("published_at")
    gap = video_df.groupby("channel_id")["published_at"].diff().dt.total_seconds() / 3600
    video_df["log_upload_gap_hours"] = np.log1p(gap)
    video_df = video_df.drop(columns=["published_at"])

    pivot = snap_df.pivot_table(
        index="video_id",
        columns="checkpoint",
        values=["views", "likes", "comments", "vph"],
        aggfunc="first",
    )
    pivot.columns = [f"{c[0]}_{c[1]}" for c in pivot.columns]
    pivot = pivot.reset_index()
    pivot = pivot.merge(video_df, on="video_id", how="left")
    subs_df = pd.DataFrame(subs, columns=["channel_id", "subscribers"])
    subs_df["channel_id"] = subs_df["channel_id"].astype(str)
    pivot = pivot.merge(subs_df, on="channel_id", how="left")
    pivot["duration_seconds"] = np.nan
    print(f"   Total videos with snapshots: {len(pivot):,}")
    print(f"   With channel_id: {pivot['channel_id'].notna().sum():,}")
    print(f"   With subscribers: {pivot['subscribers'].notna().sum():,}")
    return pivot


def add_channel_features(df):
    """Leave-one-out channel-baseline features (grouped-CV safe).

    For each checkpoint, the mean of log-views over the channel's *other* tracked
    videos — the dominant "how big does this channel usually get" signal, which
    is legitimately available at real inference (you know a channel's history).
    LOO excludes the video itself so it can't predict its own target; under
    GroupKFold the channel is never in train+test, so this isn't leakage. Mildly
    optimistic in that it uses contemporaneous (not strictly past) siblings — fine
    for a first experiment.
    """
    df = df.copy()
    for cp in ["1h", "6h", "24h", "3d", "7d", "14d", "30d"]:
        col = f"views_{cp}"
        if col not in df.columns:
            continue
        logv = np.log1p(df[col].astype(float))
        grp = logv.groupby(df["channel_id"])
        cnt = grp.transform("count")
        tot = grp.transform("sum")
        loo = (tot - logv) / (cnt - 1).clip(lower=1)
        loo = loo.where(cnt > 1, logv)  # single-video channel: fall back to self
        df[f"chanbase_logviews_{cp}"] = loo
        df[f"views_vs_chanbase_{cp}"] = logv - loo  # how this video beats its channel
    return df


# Channel-baseline feature names available at a given from-checkpoint.
def _channel_feature_cols(from_cp: str) -> list:
    return [f"chanbase_logviews_{from_cp}", f"views_vs_chanbase_{from_cp}"]


# Upload-timing features (8.5) — known pre-upload, valid at every horizon.
TIMING_FEATURES = [
    "upload_hour_sin",
    "upload_hour_cos",
    "upload_dow",
    "log_upload_gap_hours",
]


# ---------------------------------------------------------------------------
# Pure metric / baseline helpers (unit-tested, no DB)
# ---------------------------------------------------------------------------
def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean absolute percentage error (%), ignoring zero-truth rows."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = y_true > 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Coefficient of determination."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    if ss_tot == 0:
        return float("nan")
    return float(1 - ss_res / ss_tot)


def lift(baseline_mape: float, model_mape: float) -> float:
    """Fractional MAPE reduction of the model vs the baseline.

    1.0 = perfect, 0.0 = no better than baseline, < 0 = worse than baseline.
    """
    if not baseline_mape or np.isnan(baseline_mape):
        return float("nan")
    return float((baseline_mape - model_mape) / baseline_mape)


def naive_persistence(views_from: np.ndarray, growth: float = 1.0) -> np.ndarray:
    """Baseline prediction: future views ≈ current views × ``growth``.

    ``growth=1.0`` is pure persistence ("views won't change"); a value > 1
    applies a fixed historical growth multiplier (the median train-fold ratio).
    """
    return np.asarray(views_from, dtype=float) * growth


# ---------------------------------------------------------------------------
# Per-horizon evaluation
# ---------------------------------------------------------------------------
def _prepare_xy(df: pd.DataFrame, from_cp: str, to_cp: str, channel_features: bool = False):
    """Return (X, y_views, views_from, groups) for one horizon, or None."""
    target_col = f"views_{to_cp}"
    from_col = f"views_{from_cp}"
    if from_col not in df.columns or target_col not in df.columns:
        return None

    # Dedupe preserving order: get_features_for_stage can emit the same column
    # twice (e.g. growth_1h_6h from both the consecutive- and overall-growth
    # blocks at the 6h stage). Duplicate names make subset[feature_cols] a
    # DataFrame on X[col], crashing the dtype check.
    candidates = list(get_features_for_stage(df, from_cp)) + list(TIMING_FEATURES)
    if channel_features:
        candidates += _channel_feature_cols(from_cp)
    feature_cols = list(dict.fromkeys(c for c in candidates if c in df.columns))
    mask = df[from_col].notna() & df[target_col].notna() & df["channel_id"].notna()
    subset = df[mask].copy()
    if len(subset) < MIN_SAMPLES or subset["channel_id"].nunique() < MIN_GROUPS:
        return None

    X = subset[feature_cols].fillna(0).replace([np.inf, -np.inf], 0)
    for col in X.columns:
        if X[col].dtype in ("object", "bool"):
            X[col] = X[col].astype(float)

    y_views = subset[target_col].to_numpy(dtype=float)
    views_from = subset[from_col].to_numpy(dtype=float)
    groups = subset["channel_id"].astype(str).to_numpy()
    return X, y_views, views_from, groups, feature_cols


def _oof_predictions(X, y_views, groups, splitter):
    """Out-of-fold model predictions (views space) under the given splitter."""
    from xgboost import XGBRegressor

    oof = np.full(len(y_views), np.nan)
    y_log = np.log1p(y_views)
    for train_idx, test_idx in splitter.split(X, y_log, groups):
        model = XGBRegressor(
            n_estimators=400,
            learning_rate=0.05,
            max_depth=7,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbosity=0,
        )
        model.fit(X.iloc[train_idx], y_log[train_idx])
        oof[test_idx] = np.expm1(model.predict(X.iloc[test_idx]))
    return oof


def evaluate_horizon(df, from_cp, to_cp, folds, compare_splits, channel_features=False):
    from sklearn.model_selection import GroupKFold, KFold

    prepared = _prepare_xy(df, from_cp, to_cp, channel_features=channel_features)
    if prepared is None:
        return None
    X, y_views, views_from, groups, feature_cols = prepared

    n_groups = len(set(groups))
    n_splits = min(folds, n_groups)

    # Smarter baseline multiplier: median realized growth from→to.
    median_growth = float(np.median(y_views / np.clip(views_from, 1, None)))

    grouped = _oof_predictions(X, y_views, groups, GroupKFold(n_splits=n_splits))
    base_persist = naive_persistence(views_from, 1.0)
    base_growth = naive_persistence(views_from, median_growth)

    result = {
        "horizon": f"{from_cp}→{to_cp}",
        "n": len(y_views),
        "n_channels": n_groups,
        "model_mape": mape(y_views, grouped),
        "model_r2": r2(y_views, grouped),
        "baseline_persist_mape": mape(y_views, base_persist),
        "baseline_growth_mape": mape(y_views, base_growth),
        "median_growth": median_growth,
    }
    # Lift is computed against the stronger (lower-MAPE) baseline.
    best_baseline = min(result["baseline_persist_mape"], result["baseline_growth_mape"])
    result["lift_vs_baseline"] = lift(best_baseline, result["model_mape"])

    if compare_splits:
        random_oof = _oof_predictions(
            X, y_views, groups, KFold(n_splits=n_splits, shuffle=True, random_state=42)
        )
        result["random_split_mape"] = mape(y_views, random_oof)
        result["leakage_gap_mape"] = result["model_mape"] - result["random_split_mape"]

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folds", type=int, default=5, help="CV folds (capped by #channels)")
    parser.add_argument(
        "--compare-splits",
        action="store_true",
        help="Also run a random-split CV to expose the channel-leakage gap.",
    )
    parser.add_argument(
        "--source",
        choices=["tracked", "benchmark"],
        default="tracked",
        help="tracked = rebuilt collection (tracked_videos+snapshots, correct "
        "channel_id); benchmark = legacy Video-table join.",
    )
    parser.add_argument(
        "--channel-features",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add leave-one-out channel-baseline features (grouped-CV safe). "
        "Use --no-channel-features for the A/B comparison.",
    )
    args = parser.parse_args()

    print("=" * 78)
    print("HONEST VELOCITY MODEL EVALUATION (channel-grouped CV + baselines)")
    print("=" * 78)

    loader = load_tracked_data if args.source == "tracked" else load_all_data
    df = build_features(loader())
    if args.channel_features:
        df = add_channel_features(df)
        print("   + channel-baseline features (leave-one-out)")
    if "channel_id" not in df.columns:
        print("ERROR: loaded data has no channel_id column; cannot group by channel.")
        return 2

    combos = [
        (CHECKPOINTS[i], to_cp)
        for i in range(len(CHECKPOINTS) - 1)
        for to_cp in CHECKPOINTS[i + 1:]
    ]

    rows = []
    for from_cp, to_cp in combos:
        res = evaluate_horizon(
            df, from_cp, to_cp, args.folds, args.compare_splits,
            channel_features=args.channel_features,
        )
        if res is None:
            print(f"  {from_cp:>4} → {to_cp:<4}: insufficient data (need ≥{MIN_SAMPLES} "
                  f"rows / ≥{MIN_GROUPS} channels)")
            continue
        rows.append(res)
        line = (
            f"  {res['horizon']:<10} n={res['n']:>6,} ch={res['n_channels']:>5,} | "
            f"model MAPE {res['model_mape']:6.1f}% (R²={res['model_r2']:.3f}) | "
            f"baseline {min(res['baseline_persist_mape'], res['baseline_growth_mape']):6.1f}% | "
            f"lift {res['lift_vs_baseline']*100:+5.1f}%"
        )
        if args.compare_splits:
            line += (
                f" | random-split {res['random_split_mape']:6.1f}% "
                f"(leakage gap {res['leakage_gap_mape']:+.1f}pp)"
            )
        print(line)

    if not rows:
        print("\nNo horizon had enough data. Point DATABASE_URL at the training DB.")
        return 0

    print("\n" + "-" * 78)
    print("READING THE NUMBERS")
    print("  • lift ≤ 0  → the model does NOT beat 'views won't change'; not worth shipping.")
    print("  • leakage gap (model − random) is how much the old random-split numbers")
    print("    were inflated by same-channel train/test contamination.")
    print("  • report MAPE + lift publicly, NOT '100 − MAPE' or raw R².")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
