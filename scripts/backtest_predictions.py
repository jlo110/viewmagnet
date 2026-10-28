"""Backtest velocity predictability against realized outcomes (live monitor).

Unlike ``evaluate_models.py`` (which trains a fresh model under grouped CV on a
dataset), this scores **realized** outcomes as they land in the live
``video_snapshots`` table — the production health metric for the velocity
rebuild. For every video that has snapshots at both an early checkpoint and a
later one, it asks: how well does the early value predict the later one?

It reports, per ``from→to`` horizon, on the real collected data:
  - naive **persistence** baseline MAPE (later ≈ earlier)
  - persistence × median-growth baseline MAPE
  - (optional) a plugged-in model's MAPE + **lift over the better baseline**

This is the foundation for "is our served/retrained model actually beating
'views won't change' on recent real videos." Run it on a schedule or ad hoc.

Usage:
    DATABASE_URL=... python -m scripts.backtest_predictions
    DATABASE_URL=... python -m scripts.backtest_predictions --min-pairs 30

Gracefully reports "insufficient realized data" per horizon while collection is
still maturing (most videos won't have a 30d snapshot for ~30 days).
"""
from __future__ import annotations

import argparse
from collections import defaultdict

import numpy as np

# Reuse the audited metric helpers (single source of truth).
from scripts.evaluate_models import lift, mape, naive_persistence

CHECKPOINTS = ["1h", "6h", "24h", "3d", "7d", "14d", "30d"]


def _load_snapshot_pairs(min_pairs: int):
    """Return {(from_cp, to_cp): (views_from[], views_to[])} from live snapshots."""
    from sqlalchemy import select

    from src.database.connection import get_session
    from src.database.models import VideoSnapshot

    # video_id -> {checkpoint: view_count}
    by_video: dict[str, dict[str, float]] = defaultdict(dict)
    with get_session() as session:
        rows = session.execute(
            select(VideoSnapshot.video_id, VideoSnapshot.checkpoint, VideoSnapshot.view_count)
        ).all()
    for video_id, checkpoint, views in rows:
        if views is not None:
            by_video[video_id][checkpoint] = float(views)

    pairs: dict[tuple, tuple] = {}
    for i, from_cp in enumerate(CHECKPOINTS[:-1]):
        for to_cp in CHECKPOINTS[i + 1:]:
            vf, vt = [], []
            for cps in by_video.values():
                if from_cp in cps and to_cp in cps:
                    vf.append(cps[from_cp])
                    vt.append(cps[to_cp])
            if len(vf) >= min_pairs:
                pairs[(from_cp, to_cp)] = (np.array(vf), np.array(vt))
    return pairs, len(by_video)


def backtest(min_pairs: int, model_scorer=None) -> list[dict]:
    """Score each horizon. ``model_scorer(from_cp, to_cp, views_from) -> preds``
    is an optional hook to score a real model; omit for baseline-only."""
    pairs, n_videos = _load_snapshot_pairs(min_pairs)
    results = []
    for (from_cp, to_cp), (views_from, views_to) in sorted(pairs.items()):
        median_growth = float(np.median(views_to / np.clip(views_from, 1, None)))
        base_persist = mape(views_to, naive_persistence(views_from, 1.0))
        base_growth = mape(views_to, naive_persistence(views_from, median_growth))
        best_baseline = min(base_persist, base_growth)

        row = {
            "horizon": f"{from_cp}->{to_cp}",
            "n_pairs": len(views_from),
            "baseline_persist_mape": base_persist,
            "baseline_growth_mape": base_growth,
            "median_growth": median_growth,
        }
        if model_scorer is not None:
            try:
                preds = np.asarray(model_scorer(from_cp, to_cp, views_from), dtype=float)
                row["model_mape"] = mape(views_to, preds)
                row["lift_vs_baseline"] = lift(best_baseline, row["model_mape"])
            except Exception as e:  # a missing/incompatible model shouldn't crash the monitor
                row["model_error"] = str(e)
        results.append(row)
    return results, n_videos


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-pairs", type=int, default=20,
                        help="min videos with both checkpoints to report a horizon")
    args = parser.parse_args()

    print("=" * 70)
    print("VELOCITY BACKTEST — realized outcomes from live video_snapshots")
    print("=" * 70)

    results, n_videos = backtest(args.min_pairs)
    print(f"videos with snapshots: {n_videos:,}")
    if not results:
        print(f"\nNo horizon has >= {args.min_pairs} videos with both checkpoints yet.")
        print("Collection is still maturing — re-run as snapshots accumulate "
              "(30d pairs need ~30 days of tracking).")
        return 0

    print(f"\n{'horizon':<12}{'n':>7}  {'persist MAPE':>13}{'growth MAPE':>13}  median_growth")
    for r in results:
        print(f"  {r['horizon']:<10}{r['n_pairs']:>7}  "
              f"{r['baseline_persist_mape']:>11.1f}%{r['baseline_growth_mape']:>12.1f}%  "
              f"{r['median_growth']:>10.2f}x")
    print("\nThese are the baselines a model must beat. Plug a model_scorer into "
          "backtest() to report model MAPE + lift over baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
