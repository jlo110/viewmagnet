"""Is the breakout ALERT trustworthy and early enough to be a product?

AUC measures ranking; an alert product lives or dies on **precision** (when we
say 'breaking out', is it real — false alerts kill trust) and **lead time** (how
early we can fire). This measures both, on the tracked channels — which are all
**public channels we DON'T control**, i.e. exactly the competitive-intelligence
scenario ('alert me when a competitor/niche breaks out').

The score is the live detector's actual signal: ``views_vs_chanbase_{from_cp}``
(how far the video is outpacing its channel's own early norm). We fire on the
top-K% by that score at an early checkpoint, and check what fraction are real
breakouts (top-25% channel-relative) at the outcome checkpoint.

Reports per lead time (1h / 6h / 24h): precision, recall, and lift over the
base rate — so you can see the speed-vs-trust tradeoff directly.

Usage:
    python -m scripts.evaluate_breakout_alerts                 # → 7d outcome
    python -m scripts.evaluate_breakout_alerts --to 3d
"""
from __future__ import annotations

import argparse

import numpy as np

from scripts.evaluate_models import add_channel_features, load_tracked_data

OUTCOME_PCT = 0.25       # "real breakout" = top 25% channel-relative at the outcome
ALERT_PCTS = [0.05, 0.10, 0.20]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", dest="to_cp", default="7d")
    ap.add_argument("--from", dest="from_cps", nargs="+", default=["1h", "6h", "24h"])
    args = ap.parse_args()

    print("=" * 76)
    print(f"BREAKOUT ALERT precision / lead-time  (outcome = breakout by {args.to_cp},")
    print("  on tracked = NON-OWNED public channels = the competitive-intel case)")
    print("=" * 76)

    df = add_channel_features(load_tracked_data())
    to_col = f"views_vs_chanbase_{args.to_cp}"
    if to_col not in df.columns:
        print("Outcome column missing — insufficient data for this horizon.")
        return

    for from_cp in args.from_cps:
        from_col = f"views_vs_chanbase_{from_cp}"
        if from_col not in df.columns:
            continue
        sub = df.dropna(subset=[from_col, to_col, f"views_{from_cp}"])
        sub = sub[sub[f"views_{from_cp}"] > 0]
        n, nch = len(sub), sub["channel_id"].nunique()
        if n < 1000 or nch < 50:
            print(f"\n  {from_cp}→{args.to_cp}: insufficient data (n={n}, ch={nch})")
            continue

        early = sub[from_col].to_numpy()
        true_bo = (sub[to_col] >= sub[to_col].quantile(1 - OUTCOME_PCT)).to_numpy()
        base = true_bo.mean()

        print(f"\n── Alert at {from_cp}  (lead time ≈ {from_cp} after publish) "
              f"| n={n:,} ch={nch:,} | base rate {base:.0%} ──")
        print(f"  {'alert on':<14}{'precision':>11}{'recall':>9}{'lift':>8}")
        for ap_ in ALERT_PCTS:
            fire = early >= np.quantile(early, 1 - ap_)
            if fire.sum() == 0:
                continue
            precision = true_bo[fire].mean()
            recall = true_bo[fire].sum() / max(1, true_bo.sum())
            print(f"  top {int(ap_ * 100):>2}% score   {precision:>10.0%}{recall:>9.0%}"
                  f"{precision / base:>7.1f}x")
    print("\n  precision = of the videos we ALERT on, how many are real breakouts.")
    print("  lift = precision ÷ base rate (1.0x = no better than random alerting).")


if __name__ == "__main__":
    main()
