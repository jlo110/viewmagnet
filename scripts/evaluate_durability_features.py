"""Do richer signals lift DURABILITY (sustain-vs-flash) beyond the base grader?

The sustain grader hit AUC ~0.79 (24h→7d) — but it was trained WITHOUT the
velocity-curve-shape features (growth ratios, vph deceleration, overall growth)
because those are built by ``build_features``, which the eval pipeline skipped.
This isolates each "heavier" signal's lift on EXISTING data, before spending on
bigger models / LLM budget:

  base      = raw checkpoint values + channel baseline + timing
  + shape   = base + build_features curve shape (growth/vph-decay) — ZERO cost
  + comments= + early comment VOLUME (already collected)

Honest note on retention heatmaps: most-replayed is captured ~2 weeks post-
publish, so it is NOT available at a 24h prediction point — using it to predict
7d sustain would be temporal leakage. Heatmaps can only feed a LATER-horizon
durability model (7d→30d), which needs more collection. Excluded here.

Channel-grouped CV (GroupKFold). Usage:
    python -m scripts.evaluate_durability_features --from 24h --to 7d
"""
from __future__ import annotations

import argparse

import numpy as np

from scripts.evaluate_breakout_prediction import _feature_cols, _grouped_oof
from scripts.evaluate_models import add_channel_features, load_tracked_data
from scripts.train_all_velocity_models import build_features

BREAKOUT_PCT = 0.25


def _sustain_pop(df, from_cp, to_cp):
    resid_e, resid_l = f"views_vs_chanbase_{from_cp}", f"views_vs_chanbase_{to_cp}"
    sub = df.dropna(subset=[resid_e, resid_l, f"views_{from_cp}"])
    sub = sub[sub[f"views_{from_cp}"] > 0]
    e_cut = sub[resid_e].quantile(1 - BREAKOUT_PCT)
    l_cut = sub[resid_l].quantile(1 - BREAKOUT_PCT)
    early = sub[sub[resid_e] >= e_cut].copy()
    early["_y"] = (early[resid_l] >= l_cut).astype(int)
    return early


def _auc(early, from_cp, extra_cols=None):
    from sklearn.metrics import roc_auc_score

    cols = _feature_cols(early, from_cp) + [c for c in (extra_cols or []) if c in early.columns]
    cols = list(dict.fromkeys(cols))
    X = early[cols].fillna(0).replace([np.inf, -np.inf], 0).astype(float).to_numpy()
    y = early["_y"].to_numpy()
    oof = _grouped_oof(X, y, early["channel_id"].to_numpy())
    return roc_auc_score(y, oof), len(cols)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_cp", default="24h")
    ap.add_argument("--to", dest="to_cp", default="7d")
    args = ap.parse_args()
    from_cp, to_cp = args.from_cp, args.to_cp

    print("=" * 72)
    print(f"DURABILITY feature ablation  ({from_cp}→{to_cp} sustain vs flash)")
    print("=" * 72)

    raw = load_tracked_data()
    base_df = add_channel_features(raw)               # no curve shape
    rich_df = add_channel_features(build_features(raw))  # + curve shape

    base_pop = _sustain_pop(base_df, from_cp, to_cp)
    rich_pop = _sustain_pop(rich_df, from_cp, to_cp)
    if len(rich_pop) < 200:
        print(f"insufficient early breakouts (n={len(rich_pop)})")
        return

    n, nch, sr = len(rich_pop), rich_pop["channel_id"].nunique(), rich_pop["_y"].mean()
    print(f"  early breakouts n={n:,}  channels={nch:,}  sustain-rate={sr:.0%}")

    spike = rich_pop[f"views_vs_chanbase_{from_cp}"].to_numpy()
    from sklearn.metrics import roc_auc_score
    base_auc, nb = _auc(base_pop, from_cp)
    rich_auc, nr = _auc(rich_pop, from_cp)
    comm_cols = [f"comments_{cp}" for cp in ["1h", "6h", "24h"]]
    comm_auc, nc = _auc(rich_pop, from_cp, comm_cols)

    print(f"\n  {'feature set':<34}{'feats':>6}{'AUC':>8}")
    print(f"  spike-size only (current product) {'1':>6}{roc_auc_score(rich_pop['_y'], spike):>8.3f}")
    print(f"  base (no curve shape)             {nb:>6}{base_auc:>8.3f}")
    print(f"  + velocity-curve shape (FREE)     {nr:>6}{rich_auc:>8.3f}")
    print(f"  + early comment volume            {nc:>6}{comm_auc:>8.3f}")
    print(f"\n  curve-shape lift over base: {rich_auc - base_auc:+.3f}  "
          f"| comments lift over shape: {comm_auc - rich_auc:+.3f}")
    print("  → only spend on heavier models/budget where a signal moves AUC here.")


if __name__ == "__main__":
    main()
