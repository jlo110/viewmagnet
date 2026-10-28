"""Fit the breakout-detector probability calibration from realized outcomes.

Takes the early breakout *score* (views at ``from_cp`` vs the channel's
leave-one-out log-views baseline) and fits an **isotonic** map to the realized
breakout label (top-(1-q) of channel-relative overperformance at ``to_cp``), so
the served detector emits an honest P(breakout) rather than a raw score
(remediation 6.3). Evaluated channel-grouped (AUC) before saving; the artifact is
interpolation knots only (loads with just numpy).

Usage:
    python -m scripts.train_breakout_calibrator                 # 6h -> 24h, top 25%
    python -m scripts.train_breakout_calibrator --from 1h --to 24h --top-q 0.75
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from scripts.evaluate_breakout import breakout_labels
from scripts.evaluate_models import add_channel_features, load_tracked_data
from scripts.train_all_velocity_models import build_features
from src.features.breakout_detector import DEFAULT_CALIBRATOR, BreakoutCalibrator


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="from_cp", default="6h")
    ap.add_argument("--to", dest="to_cp", default="24h")
    ap.add_argument("--top-q", type=float, default=0.75)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--include-shorts", action="store_true",
                    help="include Shorts (default: exclude, to match the live detector)")
    ap.add_argument("--out", default=str(DEFAULT_CALIBRATOR))
    args = ap.parse_args()

    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    print(f"Fitting breakout calibrator {args.from_cp}->{args.to_cp} (top {(1-args.top_q)*100:.0f}%)"
          f"{'' if args.include_shorts else ' [Shorts excluded]'}")
    raw = load_tracked_data()
    if not args.include_shorts:
        # Match detect_live_breakouts: exclude Shorts from the calibration data so
        # the score→P(breakout) mapping reflects the (Shorts-excluded) live feed.
        from sqlalchemy import select

        from src.database.connection import get_session
        from src.database.models import VideoSnapshot
        with get_session() as _s:
            shorts = {r[0] for r in _s.execute(
                select(VideoSnapshot.video_id).where(VideoSnapshot.is_short.is_(True)).distinct()).all()}
        before = len(raw)
        raw = raw[~raw["video_id"].isin(shorts)]
        print(f"  excluded {before - len(raw):,} Shorts rows; {len(raw):,} remain")
    df = add_channel_features(build_features(raw))

    score_col = f"views_vs_chanbase_{args.from_cp}"   # = log views_from - channel baseline
    target_col = f"views_vs_chanbase_{args.to_cp}"
    if score_col not in df.columns or target_col not in df.columns:
        print("ERROR: required columns missing (insufficient data for this horizon).")
        return 1

    mask = df[score_col].notna() & df[target_col].notna() & df["channel_id"].notna()
    sub = df[mask].copy()
    if len(sub) < 200:
        print(f"ERROR: only {len(sub)} rows — need >=200.")
        return 1

    scores = sub[score_col].to_numpy(dtype=float)
    y = breakout_labels(sub[target_col].to_numpy(), args.top_q)
    groups = sub["channel_id"].astype(str).to_numpy()

    # Channel-grouped OOF AUC of the raw score (the honest detector metric).
    oof = np.full(len(y), np.nan)
    n_splits = min(args.folds, len(set(groups)))
    for tr, te in GroupKFold(n_splits=n_splits).split(scores, y, groups):
        if len(set(y[tr])) < 2:
            continue
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(scores[tr], y[tr])
        oof[te] = iso.predict(scores[te])
    ok = ~np.isnan(oof)
    auc = float(roc_auc_score(y[ok], oof[ok])) if len(set(y[ok])) > 1 else float("nan")

    # Final calibrator fit on all rows; store a thinned set of knots.
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(scores, y)
    grid = np.quantile(scores, np.linspace(0, 1, 101))
    grid = np.unique(grid)
    probs = iso.predict(grid)

    cal = BreakoutCalibrator(
        x=[float(v) for v in grid],
        y=[float(v) for v in probs],
        meta={
            "from_cp": args.from_cp,
            "to_cp": args.to_cp,
            "top_q": args.top_q,
            "breakout_pct": round((1 - args.top_q) * 100, 1),
            "grouped_cv_auc": round(auc, 4),
            "n": int(len(y)),
            "n_channels": int(len(set(groups))),
            "positives": int(y.sum()),
            "fit_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    cal.save(Path(args.out))
    print(f"  grouped-CV AUC: {auc:.4f}  (n={len(y):,}, {cal.meta['positives']:,} breakouts)")
    print(f"  saved -> {args.out}")
    print(f"  P(breakout) range over score knots: {min(probs):.3f}..{max(probs):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
