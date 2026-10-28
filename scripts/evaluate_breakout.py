"""Honest breakout-classification evaluation (the reframe from point-MAPE).

The velocity point-predictor loses to a persistence baseline at every horizon
(`docs/velocity_eval_report.md`) — absolute-view MAPE is the wrong objective.
This asks the product-relevant question instead: **from EARLY signals (1h/6h),
can we predict whether a video will BREAK OUT** — land in the top quartile of
channel-relative overperformance at a later checkpoint (24h/3d)?

Method (same discipline as evaluate_models):
- Target: breakout = top-quartile of ``views_vs_chanbase_{to_cp}`` (log views at
  ``to_cp`` minus the channel's leave-one-out baseline) — i.e. did it beat its
  own channel by a lot. Channel-relative, so it isn't just "big channel".
- Features: only what's known at ``from_cp`` — early views/vph, early engagement
  (like-rate, comment-rate), and early channel-relative position.
- Model: XGBoost classifier, channel-grouped ``GroupKFold`` OOF ``predict_proba``.
- **Baseline to beat:** ranking by the single early feature
  ``views_vs_chanbase_{from_cp}`` ("just look at early views vs the channel").
  The model only earns its keep if its AUC beats that — i.e. if early
  *engagement* adds breakout signal over early *views*.

Usage:
    python -m scripts.evaluate_breakout
    python -m scripts.evaluate_breakout --top-q 0.90   # rarer "big" breakouts
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from scripts.evaluate_models import add_channel_features, load_tracked_data
from scripts.train_all_velocity_models import build_features

HORIZONS = [("1h", "24h"), ("1h", "3d"), ("6h", "24h"), ("6h", "3d")]
MIN_SAMPLES = 200
MIN_GROUPS = 5


def breakout_labels(overperf: np.ndarray, top_q: float) -> np.ndarray:
    """1 for the top ``(1 - top_q)`` fraction of channel-relative overperformance."""
    overperf = np.asarray(overperf, dtype=float)
    threshold = np.quantile(overperf, top_q)
    return (overperf >= threshold).astype(int)


def early_feature_cols(from_cp: str) -> list:
    """Features legitimately known at ``from_cp`` (no future checkpoints)."""
    cps = ["1h", "6h", "24h", "3d", "7d", "14d", "30d"]
    avail = cps[: cps.index(from_cp) + 1]
    cols = []
    for cp in avail:
        cols += [
            f"views_{cp}", f"vph_{cp}", f"log_views_{cp}",
            f"like_rate_{cp}", f"comment_rate_{cp}",
            f"chanbase_logviews_{cp}", f"views_vs_chanbase_{cp}",
        ]
    return cols


def _auc(y_true, scores) -> float:
    from sklearn.metrics import roc_auc_score

    if len(set(y_true)) < 2:
        return float("nan")
    return float(roc_auc_score(y_true, scores))


def evaluate(df: pd.DataFrame, from_cp: str, to_cp: str, folds: int, top_q: float):
    from sklearn.model_selection import GroupKFold
    from xgboost import XGBClassifier

    target_col = f"views_vs_chanbase_{to_cp}"
    if target_col not in df.columns or f"views_{from_cp}" not in df.columns:
        return None
    feat_cols = [c for c in early_feature_cols(from_cp) if c in df.columns]
    base_col = f"views_vs_chanbase_{from_cp}"
    mask = df[target_col].notna() & df[f"views_{from_cp}"].notna() & df["channel_id"].notna()
    subset = df[mask].copy()
    if len(subset) < MIN_SAMPLES or subset["channel_id"].nunique() < MIN_GROUPS:
        return None

    y = breakout_labels(subset[target_col].to_numpy(), top_q)
    X = subset[feat_cols].fillna(0).replace([np.inf, -np.inf], 0).astype(float)
    groups = subset["channel_id"].astype(str).to_numpy()
    n_splits = min(folds, len(set(groups)))

    oof = np.full(len(y), np.nan)
    for tr, te in GroupKFold(n_splits=n_splits).split(X, y, groups):
        if len(set(y[tr])) < 2:
            continue
        clf = XGBClassifier(
            n_estimators=300, learning_rate=0.05, max_depth=5,
            subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
            random_state=42, verbosity=0,
        )
        clf.fit(X.iloc[tr], y[tr])
        oof[te] = clf.predict_proba(X.iloc[te])[:, 1]

    ok = ~np.isnan(oof)
    model_auc = _auc(y[ok], oof[ok])
    # Baseline: rank by the single early channel-relative-views feature.
    base_auc = (
        _auc(y, subset[base_col].fillna(0).to_numpy()) if base_col in subset else float("nan")
    )
    return {
        "horizon": f"{from_cp}→{to_cp}",
        "n": int(len(y)),
        "n_channels": int(len(set(groups))),
        "positives": int(y.sum()),
        "model_auc": model_auc,
        "baseline_auc": base_auc,
        "auc_gain": model_auc - base_auc if not np.isnan(base_auc) else float("nan"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--top-q", type=float, default=0.75, help="breakout = top (1-q) fraction")
    args = ap.parse_args()

    print("=" * 78)
    print(f"HONEST BREAKOUT EVALUATION (channel-grouped CV, breakout = top {(1-args.top_q)*100:.0f}%)")
    print("=" * 78)

    df = add_channel_features(build_features(load_tracked_data()))
    if "channel_id" not in df.columns:
        print("ERROR: no channel_id; cannot group.")
        return 1

    rows = []
    for from_cp, to_cp in HORIZONS:
        res = evaluate(df, from_cp, to_cp, args.folds, args.top_q)
        if res is None:
            print(f"  {from_cp:>3} → {to_cp:<3}: insufficient data")
            continue
        rows.append(res)
        gain = res["auc_gain"]
        flag = "✅ beats early-views" if gain > 0.01 else ("≈ tie" if gain > -0.01 else "❌ worse")
        print(
            f"  {res['horizon']:<9} n={res['n']:>6,} ch={res['n_channels']:>5,} "
            f"pos={res['positives']:>5,} | model AUC {res['model_auc']:.3f} | "
            f"early-views AUC {res['baseline_auc']:.3f} | Δ {gain:+.3f}  {flag}"
        )

    print("\n" + "-" * 78)
    print("READING: AUC 0.5 = chance. The model earns its keep only if it beats the")
    print("'early channel-relative views' baseline — i.e. early ENGAGEMENT adds signal")
    print("beyond early VIEWS. That delta is the breakout detector's real value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
