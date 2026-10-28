"""Train the breakout DURABILITY grader (stage 2 of Breakout Radar).

EXPERIMENTAL / PROVISIONAL. Detection (stage 1, live in breakout_detector) only
needs the channel-relative residual. This grader answers the *second* question
the residual can't: among videos that ARE breaking out early, **which will
SUSTAIN vs flash out?** The honest eval (scripts/evaluate_breakout_prediction)
showed the full multi-signal set beats early-spike-size alone by +0.07–0.11 AUC
here — i.e. this is where the heavy collection earns its keep.

Caveats baked in:
- Trained ONLY on early-breakout videos (the population the grader scores).
- Channel-grouped CV (GroupKFold) — honest, no per-channel leak.
- **Power is moderate** (~5–6k early breakouts as of 2026-06-19) and the 14d/30d
  horizons don't have data yet, so the artifact is stamped ``provisional`` and
  must NOT be presented as a confident production signal until re-validated at
  full power. Re-run in ~2–3 weeks.

Usage:
    python -m scripts.train_sustain_grader                 # 24h -> 7d (best lift)
    python -m scripts.train_sustain_grader --from 6h --to 7d
"""
from __future__ import annotations

import argparse
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np

from scripts.evaluate_breakout_prediction import _feature_cols, _grouped_oof
from scripts.evaluate_models import add_channel_features, load_tracked_data

BREAKOUT_PCT = 0.25
MIN_EARLY_BREAKOUTS = 200
MIN_GROUPS = 20


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="from_cp", default="24h")
    ap.add_argument("--to", dest="to_cp", default="7d")
    ap.add_argument("--breakout-pct", type=float, default=BREAKOUT_PCT)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from sklearn.metrics import balanced_accuracy_score, roc_auc_score
    from xgboost import XGBClassifier

    from_cp, to_cp = args.from_cp, args.to_cp
    out = Path(args.out or f"data/models/sustain_grader_{from_cp}_{to_cp}.pkl")
    print(f"Training durability grader: early breakout @{from_cp} → still breakout @{to_cp}")

    df = add_channel_features(load_tracked_data())
    resid_e, resid_l = f"views_vs_chanbase_{from_cp}", f"views_vs_chanbase_{to_cp}"
    if resid_e not in df.columns or resid_l not in df.columns:
        print("ERROR: required columns missing (insufficient data for this horizon).")
        return 1

    sub = df.dropna(subset=[resid_e, resid_l, f"views_{from_cp}"])
    sub = sub[sub[f"views_{from_cp}"] > 0]
    e_cut = sub[resid_e].quantile(1 - args.breakout_pct)
    l_cut = sub[resid_l].quantile(1 - args.breakout_pct)
    early = sub[sub[resid_e] >= e_cut].copy()   # the population this grader scores
    if len(early) < MIN_EARLY_BREAKOUTS or early["channel_id"].nunique() < MIN_GROUPS:
        print(f"ERROR: only {len(early)} early breakouts / "
              f"{early['channel_id'].nunique()} channels — need more data.")
        return 1

    y = (early[resid_l] >= l_cut).astype(int).to_numpy()      # 1 = sustained
    groups = early["channel_id"].to_numpy()
    feat_cols = _feature_cols(early, from_cp)
    X = early[feat_cols].fillna(0).replace([np.inf, -np.inf], 0).astype(float).to_numpy()

    # Honest channel-grouped OOF metric, and the spike-size-only baseline it must beat.
    oof = _grouped_oof(X, y, groups)
    spike = early[resid_e].to_numpy()
    cv_auc = roc_auc_score(y, oof)
    base_auc = roc_auc_score(y, spike)
    thr = np.quantile(oof, 1 - y.mean())
    cv_bacc = balanced_accuracy_score(y, (oof >= thr).astype(int))

    n, nch = len(early), early["channel_id"].nunique()
    provisional = n < 8000 or nch < 800
    print(f"  early breakouts: n={n:,} channels={nch:,} sustain-rate={y.mean():.0%} feats={len(feat_cols)}")
    print(f"  grouped-CV AUC {cv_auc:.3f} (bal-acc {cv_bacc:.3f}) | spike-size baseline {base_auc:.3f} "
          f"| lift {cv_auc - base_auc:+.3f}")
    if provisional:
        print("  ⚠ PROVISIONAL: moderate power — do NOT present as a confident signal; re-validate later.")

    # Refit on all early-breakouts and save the artifact (not wired into live).
    clf = XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
        scale_pos_weight=(y == 0).sum() / max(1, (y == 1).sum()),
    )
    clf.fit(X, y)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        pickle.dump({
            "model": clf, "feature_cols": feat_cols,
            "from_cp": from_cp, "to_cp": to_cp, "breakout_pct": args.breakout_pct,
            "cv_auc": float(cv_auc), "cv_balanced_accuracy": float(cv_bacc),
            "spike_baseline_auc": float(base_auc), "n_samples": int(n), "n_channels": int(nch),
            "provisional": bool(provisional), "trained_at": datetime.utcnow().isoformat(),
        }, fh)
    print(f"  saved → {out}  (provisional={provisional}; NOT wired into the live detector)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
