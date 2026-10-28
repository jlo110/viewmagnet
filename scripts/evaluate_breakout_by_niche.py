"""Per-niche breakout analysis (plan 8.10 stage 1) — is breakout niche-invariant?

The served breakout detector is a single channel-relative feature
(`views_vs_chanbase`) → isotonic calibration, global across all niches
(grouped-CV AUC ~0.93). Question 8.10 asks: do niches behave differently enough
that per-niche models/calibration would help?

Two things vary by niche, tested here:
1. **Predictive strength** — within-niche grouped-CV AUC of the early score for
   predicting a *within-niche* top-quartile breakout. If News scores 0.95 but
   Education 0.85, per-niche thresholds matter; if all ~0.93, breakout is
   niche-invariant (because the score is already channel-relative) — a clean
   simplifying result that says "don't bother".
2. **Calibration drift** — does one GLOBAL calibrator's probability have higher
   error (ECE) on some niches? Isotonic is monotonic so per-niche calibration
   can't change AUC, only calibration quality — this is where per-niche
   calibrators would earn their keep.

Usage:
    python -m scripts.evaluate_breakout_by_niche
    python -m scripts.evaluate_breakout_by_niche --from 1h --to 24h
"""
from __future__ import annotations

import argparse

import numpy as np

from scripts.evaluate_breakout import breakout_labels
from scripts.evaluate_models import add_channel_features, load_tracked_data
from scripts.train_all_velocity_models import build_features

CAT = {
    "1": "Film", "2": "Autos", "10": "Music", "15": "Pets", "17": "Sports",
    "19": "Travel", "20": "Gaming", "22": "People", "23": "Comedy",
    "24": "Entertainment", "25": "News", "26": "Howto", "27": "Education",
    "28": "Science", "29": "Nonprofit",
}
MIN_NICHE = 400  # need enough for a grouped split


def load_video_categories() -> dict:
    """Modal youtube_category_id per video (≈100% coverage since 7.1/8.5)."""
    from collections import Counter, defaultdict

    from sqlalchemy import select

    from src.database.connection import get_session
    from src.database.models import VideoSnapshot

    counts: dict = defaultdict(Counter)
    with get_session() as s:
        for vid, cat in s.execute(
            select(VideoSnapshot.video_id, VideoSnapshot.youtube_category_id)
            .where(VideoSnapshot.youtube_category_id.isnot(None))
        ).all():
            counts[vid][cat] += 1
    return {vid: c.most_common(1)[0][0] for vid, c in counts.items()}


def grouped_auc(scores, labels, groups, folds=5):
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    scores, labels = np.asarray(scores, float), np.asarray(labels, int)
    n_splits = min(folds, len(set(groups)))
    if n_splits < 2 or len(set(labels)) < 2:
        return float("nan")
    oof = np.full(len(labels), np.nan)
    for tr, te in GroupKFold(n_splits=n_splits).split(scores, labels, groups):
        if len(set(labels[tr])) < 2:
            continue
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(scores[tr], labels[tr])
        oof[te] = iso.predict(scores[te])
    ok = ~np.isnan(oof)
    return float(roc_auc_score(labels[ok], oof[ok])) if len(set(labels[ok])) > 1 else float("nan")


def ece(probs, labels, bins=10):
    """Expected calibration error — mean |confidence − accuracy| over bins."""
    probs, labels = np.asarray(probs, float), np.asarray(labels, int)
    edges = np.linspace(0, 1, bins + 1)
    e = 0.0
    for i in range(bins):
        m = (probs >= edges[i]) & (probs < edges[i + 1] if i < bins - 1 else probs <= edges[i + 1])
        if m.sum() == 0:
            continue
        e += (m.sum() / len(probs)) * abs(probs[m].mean() - labels[m].mean())
    return float(e)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="from_cp", default="6h")
    ap.add_argument("--to", dest="to_cp", default="24h")
    ap.add_argument("--top-q", type=float, default=0.75)
    args = ap.parse_args()

    print("=" * 78)
    print(f"PER-NICHE BREAKOUT ({args.from_cp}->{args.to_cp}, top {(1-args.top_q)*100:.0f}%)")
    print("=" * 78)

    df = add_channel_features(build_features(load_tracked_data()))
    cats = load_video_categories()
    df["category"] = df["video_id"].map(cats)

    score_col = f"views_vs_chanbase_{args.from_cp}"
    target_col = f"views_vs_chanbase_{args.to_cp}"
    base = df[df[score_col].notna() & df[target_col].notna() & df["channel_id"].notna()].copy()

    # Global: breakout = global top quartile.
    gy = breakout_labels(base[target_col].to_numpy(), args.top_q)
    g_auc = grouped_auc(base[score_col], gy, base["channel_id"].astype(str))
    print(f"\nGLOBAL: n={len(base):,}  grouped-CV AUC {g_auc:.3f}\n")

    # HELD-OUT calibration comparison: one grouped CV; per fold fit a GLOBAL
    # isotonic (all train rows) and PER-NICHE isotonics (train rows within each
    # niche), predict the test rows with both. ECE is then measured on
    # out-of-fold probabilities — no in-sample overfit.
    from sklearn.isotonic import IsotonicRegression
    from sklearn.model_selection import GroupKFold

    scores = base[score_col].to_numpy(float)
    groups = base["category"].astype(str).to_numpy()
    chan = base["channel_id"].astype(str).to_numpy()
    g_oof = np.full(len(base), np.nan)
    n_oof = np.full(len(base), np.nan)
    for tr, te in GroupKFold(n_splits=5).split(scores, gy, chan):
        if len(set(gy[tr])) < 2:
            continue
        g_oof[te] = IsotonicRegression(out_of_bounds="clip").fit(scores[tr], gy[tr]).predict(scores[te])
        for cid in set(groups[te]):
            tr_n = tr[groups[tr] == cid]
            if len(tr_n) < 100 or len(set(gy[tr_n])) < 2:
                continue
            te_n = te[groups[te] == cid]
            n_oof[te_n] = IsotonicRegression(out_of_bounds="clip").fit(scores[tr_n], gy[tr_n]).predict(scores[te_n])

    print(f"{'niche':14s} {'n':>6s} {'base%':>6s} {'within-AUC':>11s} {'globalECE':>10s} {'nicheECE':>9s}")
    rows = []
    for cid, sub in base.groupby("category"):
        if len(sub) < MIN_NICHE:
            continue
        idx = base.index.get_indexer(sub.index)
        wy = breakout_labels(sub[target_col].to_numpy(), args.top_q)
        w_auc = grouped_auc(sub[score_col], wy, sub["channel_id"].astype(str))
        # held-out ECE of global vs per-niche calibrator on this niche's rows
        gp, np_ = g_oof[idx], n_oof[idx]
        gok, nok = ~np.isnan(gp), ~np.isnan(np_)
        g_ece = ece(gp[gok], gy[idx][gok]) if gok.any() else float("nan")
        n_ece = ece(np_[nok], gy[idx][nok]) if nok.any() else float("nan")
        rows.append((CAT.get(cid, cid), len(sub), wy.mean(), w_auc, g_ece, n_ece))
    for name, n, br, auc, gece, nece in sorted(rows, key=lambda r: -r[1]):
        print(f"{name:14s} {n:>6,} {br*100:>5.1f}% {auc:>11.3f} {gece:>10.3f} {nece:>9.3f}")

    aucs = [r[3] for r in rows if not np.isnan(r[3])]
    print("\n" + "-" * 78)
    print(f"within-niche AUC spread: {min(aucs):.3f}–{max(aucs):.3f} (global {g_auc:.3f})")
    print("READING: tight spread near global ⇒ breakout is niche-invariant (score is already")
    print("channel-relative); don't build per-niche classifiers. If globalECE ≫ nicheECE for")
    print("some niches, a per-niche CALIBRATOR is worth it even when AUC is flat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
