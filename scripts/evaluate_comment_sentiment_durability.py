"""Does early AUDIENCE REACTION (comment sentiment/depth) lift durability?

The last cheap untested lever. The base multi-signal durability grader is at
AUC ~0.812 (24h→7d sustain); curve-shape added nothing. This tests whether the
*text* of early comments — audience reaction, not just volume — predicts which
breakouts SUSTAIN, beyond the base. Free (VADER lexicon, no LLM). If it moves
AUC, an LLM-based comment-analysis investment is justified; if not, it isn't.

Per-video comment features: VADER mean/std compound, %positive, %negative,
mean comment like_count & reply_count (resonance/debate), mean length, question
rate. Videos with no collected comments are flagged (has_comments=0).

Channel-grouped CV. Reports coverage first — if few breakouts have comments yet,
the result is provisional. Usage:
    python -m scripts.evaluate_comment_sentiment_durability
"""
from __future__ import annotations

import argparse

import numpy as np

from scripts.evaluate_breakout_prediction import _feature_cols, _grouped_oof
from scripts.evaluate_durability_features import _sustain_pop
from scripts.evaluate_models import add_channel_features, load_tracked_data
from scripts.train_all_velocity_models import build_features

COMMENT_FEATS = [
    "cmt_n", "cmt_sent_mean", "cmt_sent_std", "cmt_frac_pos", "cmt_frac_neg",
    "cmt_like_mean", "cmt_reply_mean", "cmt_len_mean", "cmt_q_rate", "has_comments",
]


def _comment_features(video_ids):
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    from sqlalchemy import select

    from src.database.connection import get_session
    from src.database.models import VideoComment as VC

    sia = SentimentIntensityAnalyzer()
    by_vid: dict = {}
    with get_session() as s:
        for vid, text, likes, replies in s.execute(
            select(VC.video_id, VC.text, VC.like_count, VC.reply_count).where(VC.video_id.in_(video_ids))
        ).all():
            by_vid.setdefault(vid, []).append((text or "", likes or 0, replies or 0))

    feats = {}
    for vid, rows in by_vid.items():
        comps = [sia.polarity_scores(t)["compound"] for t, _, _ in rows]
        comps = np.asarray(comps)
        feats[vid] = {
            "cmt_n": len(rows),
            "cmt_sent_mean": float(comps.mean()),
            "cmt_sent_std": float(comps.std()),
            "cmt_frac_pos": float((comps > 0.05).mean()),
            "cmt_frac_neg": float((comps < -0.05).mean()),
            "cmt_like_mean": float(np.mean([r[1] for r in rows])),
            "cmt_reply_mean": float(np.mean([r[2] for r in rows])),
            "cmt_len_mean": float(np.mean([len(r[0]) for r in rows])),
            "cmt_q_rate": float(np.mean([("?" in r[0]) for r in rows])),
            "has_comments": 1,
        }
    return feats


def main() -> None:
    argparse.ArgumentParser().parse_args()
    from sklearn.metrics import roc_auc_score

    print("=" * 70)
    print("COMMENT-SENTIMENT durability test (24h→7d sustain), free VADER")
    print("=" * 70)

    df = add_channel_features(build_features(load_tracked_data()))
    pop = _sustain_pop(df, "24h", "7d")
    if len(pop) < 200:
        print(f"insufficient population (n={len(pop)})")
        return

    cfeats = _comment_features(pop["video_id"].tolist())
    cov = len(set(cfeats) & set(pop["video_id"]))
    print(f"  population: {len(pop):,} early breakouts / {pop['channel_id'].nunique():,} channels")
    print(f"  comment coverage: {cov:,} have collected comments ({cov / len(pop):.0%})")
    if cov < 300:
        print("  ⚠ coverage too low for a trustworthy test — comments still backfilling. PROVISIONAL.")

    pop = pop.copy()
    for f in COMMENT_FEATS:
        pop[f] = pop["video_id"].map(lambda v: cfeats.get(v, {}).get(f, 0.0))

    base_cols = _feature_cols(pop, "24h")
    y = pop["_y"].to_numpy()
    groups = pop["channel_id"].to_numpy()

    def auc(cols):
        X = pop[cols].fillna(0).replace([np.inf, -np.inf], 0).astype(float).to_numpy()
        return roc_auc_score(y, _grouped_oof(X, y, groups))

    base_auc = auc(base_cols)
    full_auc = auc(base_cols + COMMENT_FEATS)
    # On the subset that actually HAS comments (where the signal could show).
    has = pop["has_comments"] == 1
    sub_note = ""
    if has.sum() >= 300 and pop[has]["channel_id"].nunique() >= 30:
        ph = pop[has]
        yh, gh = ph["_y"].to_numpy(), ph["channel_id"].to_numpy()
        Xb = ph[base_cols].fillna(0).replace([np.inf, -np.inf], 0).astype(float).to_numpy()
        Xf = ph[base_cols + COMMENT_FEATS].fillna(0).replace([np.inf, -np.inf], 0).astype(float).to_numpy()
        bh = roc_auc_score(yh, _grouped_oof(Xb, yh, gh))
        fh = roc_auc_score(yh, _grouped_oof(Xf, yh, gh))
        sub_note = f"\n  on comment-having subset (n={has.sum():,}): base {bh:.3f} → +comments {fh:.3f} ({fh - bh:+.3f})"

    print(f"\n  base multi-signal            AUC {base_auc:.3f}")
    print(f"  + comment sentiment/depth    AUC {full_auc:.3f}   ({full_auc - base_auc:+.3f})")
    print(sub_note)
    print("\n  → if lift ≈ 0, LLM comment-analysis budget is NOT justified for durability.")


if __name__ == "__main__":
    main()
