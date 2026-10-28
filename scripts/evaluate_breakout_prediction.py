"""Honest test of the 'track many signals to catch breakouts' thesis.

Today's two earlier evals tested the WRONG questions:
- the content classifier used title+thumbnail only (packaging alone — confirmed
  ~baseline, which is *why* we track more), and
- the velocity eval forecast *absolute* future views (dominated by persistence —
  near-unbeatable and not the product's value).

This tests the actual product question: **from EARLY signals (≤ from_cp), can we
predict that a video will BREAK OUT — over-perform its own channel baseline — by
a later checkpoint?** It uses the full early signal set the pipeline tracks
(velocity shape, engagement, channel context, upload timing) and is judged the
honest way:

- **Target**: breakout = top-``BREAKOUT_PCT`` of ``views_vs_chanbase_{to_cp}``
  (the channel-relative log-residual at the outcome) — NOT absolute views.
- **Two baselines that must be beaten to justify the model:**
    1. base rate (no-skill) → balanced acc 0.50;
    2. **early-residual** = "it's already over-performing at from_cp" — rank by
       ``views_vs_chanbase_{from_cp}`` alone. If the model can't beat this, the
       extra signals add nothing over "just look at whether it's ahead now".
- **GroupKFold by channel_id** so a channel is never in train+test.

Usage:
    python -m scripts.evaluate_breakout_prediction                 # default 24h→7d
    python -m scripts.evaluate_breakout_prediction --from 6h --to 24h
    python -m scripts.evaluate_breakout_prediction --breakout-pct 0.20
"""
from __future__ import annotations

import argparse

import numpy as np

from scripts.evaluate_models import (
    TIMING_FEATURES,
    add_channel_features,
    get_features_for_stage,
    load_tracked_data,
)

BREAKOUT_PCT = 0.25      # top quartile of channel-relative residual = "breakout"
MIN_SAMPLES = 200
MIN_GROUPS = 20


def _feature_cols(df, from_cp: str) -> list:
    """Early features legitimately available at ``from_cp`` (no outcome leak)."""
    cands = (
        list(get_features_for_stage(df, from_cp))
        + list(TIMING_FEATURES)
        + [f"chanbase_logviews_{from_cp}", f"views_vs_chanbase_{from_cp}"]
    )
    # de-dupe, keep only existing, and DROP any to_cp/future columns defensively
    seen, out = set(), []
    for c in cands:
        if c in df.columns and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _power(n: int, ch: int) -> str:
    """Flag whether a horizon has enough data to trust the conclusion."""
    if n < 2000 or ch < 100:
        return "  ⚠ UNDERPOWERED — too little data yet, treat as provisional"
    if n < 8000 or ch < 800:
        return "  ~ moderate power — directional, not final"
    return "  ✓ well-powered"


def _grouped_oof(X, y, groups):
    """Channel-grouped out-of-fold breakout probabilities from XGBoost."""
    from sklearn.model_selection import GroupKFold
    from xgboost import XGBClassifier

    oof = np.zeros(len(y))
    for tr, te in GroupKFold(n_splits=5).split(X, y, groups):
        clf = XGBClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
            scale_pos_weight=(y[tr] == 0).sum() / max(1, (y[tr] == 1).sum()),
        )
        clf.fit(X[tr], y[tr])
        oof[te] = clf.predict_proba(X[te])[:, 1]
    return oof


def evaluate(df, from_cp: str, to_cp: str, breakout_pct: float):
    from sklearn.metrics import balanced_accuracy_score, f1_score, roc_auc_score

    resid_to = f"views_vs_chanbase_{to_cp}"
    resid_from = f"views_vs_chanbase_{from_cp}"
    need = [f"views_{from_cp}", f"views_{to_cp}", resid_to, resid_from]
    df = df.dropna(subset=need)
    df = df[df[f"views_{from_cp}"] > 0]
    if len(df) < MIN_SAMPLES or df["channel_id"].nunique() < MIN_GROUPS:
        print(f"  {from_cp}→{to_cp}: insufficient data (n={len(df)}, ch={df['channel_id'].nunique()})")
        return

    # Breakout label = top-pct of the channel-relative residual at the outcome.
    cut = df[resid_to].quantile(1 - breakout_pct)
    y = (df[resid_to] >= cut).astype(int).to_numpy()
    groups = df["channel_id"].to_numpy()

    feat_cols = _feature_cols(df, from_cp)
    X = df[feat_cols].fillna(0).replace([np.inf, -np.inf], 0).astype(float).to_numpy()

    # --- Model: full early signal set, channel-grouped OOF ---
    oof = _grouped_oof(X, y, groups)

    # --- Baseline: rank by the early residual alone ("already ahead now") ---
    early = df[resid_from].fillna(0).replace([np.inf, -np.inf], 0).to_numpy()

    def at_threshold(score):
        # Threshold matched to the positive rate so balanced-acc is comparable.
        thr = np.quantile(score, 1 - breakout_pct)
        return (score >= thr).astype(int)

    model_pred = at_threshold(oof)
    base_pred = at_threshold(early)

    m_auc = roc_auc_score(y, oof)
    b_auc = roc_auc_score(y, early)
    m_bacc = balanced_accuracy_score(y, model_pred)
    b_bacc = balanced_accuracy_score(y, base_pred)
    m_f1 = f1_score(y, model_pred, zero_division=0)

    print(f"\n── Breakout prediction {from_cp} → {to_cp} "
          f"(breakout = top {int(breakout_pct * 100)}% channel-relative) ──")
    print(f"  n={len(df):,}  channels={df['channel_id'].nunique():,}  "
          f"positives={int(y.sum()):,} ({y.mean():.0%})  features={len(feat_cols)}")
    print(f"  {'':22}{'AUC':>8}{'bal-acc':>10}")
    print(f"  base rate (no-skill)  {'0.500':>8}{'0.500':>10}")
    print(f"  early-residual only   {b_auc:>8.3f}{b_bacc:>10.3f}   <- the bar to beat")
    print(f"  FULL multi-signal     {m_auc:>8.3f}{m_bacc:>10.3f}   (F1 {m_f1:.3f})")
    print(f"  model lift vs early-residual: AUC {m_auc - b_auc:+.3f}, "
          f"bal-acc {m_bacc - b_bacc:+.3f}")
    print("  → if lift ≈ 0, the extra tracked signals add nothing over "
          "'it's already ahead'.")
    print(_power(len(df), df["channel_id"].nunique()))


def evaluate_sustained(df, early_cp: str, late_cp: str, breakout_pct: float):
    """Among videos that ARE early breakouts, predict SUSTAIN vs FLASH.

    This is where richer signals *might* earn their keep: every video here has a
    big early residual (by construction), so 'how big the early spike is' should
    be a weak discriminator — if engagement/velocity-shape features beat it, the
    multi-signal tracking adds real value for durability.
    """
    from sklearn.metrics import balanced_accuracy_score, roc_auc_score

    resid_e, resid_l = f"views_vs_chanbase_{early_cp}", f"views_vs_chanbase_{late_cp}"
    sub = df.dropna(subset=[resid_e, resid_l, f"views_{early_cp}"])
    sub = sub[sub[f"views_{early_cp}"] > 0]
    if sub.empty:
        print(f"\n── Sustain vs flash {early_cp}→{late_cp}: no data ──")
        return
    # Early breakouts only, then label sustain = still above the late breakout cut.
    e_cut = sub[resid_e].quantile(1 - breakout_pct)
    l_cut = sub[resid_l].quantile(1 - breakout_pct)
    early_bo = sub[sub[resid_e] >= e_cut].copy()
    if len(early_bo) < MIN_SAMPLES or early_bo["channel_id"].nunique() < MIN_GROUPS:
        print(f"\n── Sustain vs flash {early_cp}→{late_cp}: insufficient early-breakouts "
              f"(n={len(early_bo)}) ──")
        return
    y = (early_bo[resid_l] >= l_cut).astype(int).to_numpy()
    groups = early_bo["channel_id"].to_numpy()

    feat_cols = _feature_cols(early_bo, early_cp)
    X = early_bo[feat_cols].fillna(0).replace([np.inf, -np.inf], 0).astype(float).to_numpy()
    oof = _grouped_oof(X, y, groups)
    spike = early_bo[resid_e].to_numpy()  # baseline: just how big the early spike is

    m_auc, b_auc = roc_auc_score(y, oof), roc_auc_score(y, spike)
    thr = np.quantile(oof, 1 - y.mean())
    m_bacc = balanced_accuracy_score(y, (oof >= thr).astype(int))
    print(f"\n── Sustain vs flash: early breakout @{early_cp}, still breakout @{late_cp} ──")
    print(f"  n(early breakouts)={len(early_bo):,}  channels={early_bo['channel_id'].nunique():,}  "
          f"sustain-rate={y.mean():.0%}  features={len(feat_cols)}")
    print(f"  early-spike size only : AUC {b_auc:.3f}   <- the bar to beat")
    print(f"  FULL multi-signal     : AUC {m_auc:.3f}  bal-acc {m_bacc:.3f}")
    print(f"  model lift vs spike-size: AUC {m_auc - b_auc:+.3f}  "
          f"(>0 ⇒ rich signals predict DURABILITY the residual can't)")
    print(_power(len(early_bo), early_bo["channel_id"].nunique()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_cp", default="24h")
    ap.add_argument("--to", dest="to_cp", default="7d")
    ap.add_argument("--breakout-pct", type=float, default=BREAKOUT_PCT)
    ap.add_argument("--all", action="store_true", help="full sweep incl. 1h + sustain")
    args = ap.parse_args()

    print("=" * 78)
    print("HONEST BREAKOUT-PREDICTION EVAL (early signals → channel-relative breakout)")
    print("=" * 78)
    df = load_tracked_data()
    df = add_channel_features(df)
    if args.all:
        print("\n### (b) early DETECTION incl. 1h (where the residual is noisiest)")
        for fc, tc in [("1h", "24h"), ("1h", "7d"), ("6h", "24h"), ("24h", "7d")]:
            evaluate(df, fc, tc, args.breakout_pct)
        print("\n### (b) SUSTAIN vs FLASH (does multi-signal predict durability?)")
        for ec, lc in [("6h", "7d"), ("24h", "7d"), ("1h", "7d")]:
            evaluate_sustained(df, ec, lc, args.breakout_pct)
    else:
        evaluate(df, args.from_cp, args.to_cp, args.breakout_pct)


if __name__ == "__main__":
    main()
