"""Best honest shot at PRE-LAUNCH prediction — does any signal beat the coin flip?

Earlier we showed title+thumbnail+embeddings ≈ baseline for predicting
channel-relative overperformance. This is the strongest pre-launch model we can
build, to either find a modest real edge or definitively confirm the ceiling:

Pre-launch features ONLY (everything known before you hit publish):
- 9 hand-crafted title features
- 384-dim title embedding (full semantics)
- **title novelty** = cosine distance of the title to the channel's OWN title
  centroid (leave-one-out) — "is this a departure from what this channel
  usually posts" (a genuinely new pre-launch signal)
- publish timing (hour-of-day cyclic, day-of-week)
- log duration, log channel-median-views (scale)

Target: top-30% performer vs the channel's own median (channel-relative).
Eval: GroupKFold by channel_id (a channel is never in train+test). Under that
split, channel-constant features can't cheat — the model must find WITHIN-channel
pre-launch discriminators, which is the honest question.

NOTE on "is this topic hot": true temporal topic-hotness needs time-windowed
breakout context the backfill cross-section can't reconstruct cleanly — that
signal lives in Format Radar (market timing), evaluated separately.

Usage:
    python -m scripts.evaluate_prelaunch_ceiling
    python -m scripts.evaluate_prelaunch_ceiling --min-per-channel 10
"""
from __future__ import annotations

import argparse
import math
import pickle
from pathlib import Path

import numpy as np

from scripts.train_content_from_backfill import TITLE_FEATURES, _title_feats

EMB_CACHE = Path("data/cache/title_emb.pkl")
TOP_FRACTION = 0.30


def _embed(titles, video_ids):
    """Sentence-transformer title embeddings, cached on disk by video_id."""
    cache = {}
    if EMB_CACHE.exists():
        with open(EMB_CACHE, "rb") as fh:
            cache = pickle.load(fh)
    missing = [(v, t) for v, t in zip(video_ids, titles) if v not in cache]
    if missing:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        vecs = model.encode([t for _, t in missing], batch_size=128, show_progress_bar=True)
        for (v, _), vec in zip(missing, vecs):
            cache[v] = np.asarray(vec, dtype=np.float32)
        EMB_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(EMB_CACHE, "wb") as fh:
            pickle.dump(cache, fh)
    return np.vstack([cache[v] for v in video_ids])


def load_data(min_per_channel: int):
    import pandas as pd
    from sqlalchemy import select

    from src.database.connection import get_session
    from src.database.models import BackfillVideo as BV
    from src.database.models import TrackedChannel as TC
    from src.features.language import is_probably_english

    with get_session() as s:
        rows = s.execute(select(
            BV.video_id, BV.channel_id, BV.title, BV.outlier, BV.channel_median_views,
            BV.duration_seconds, BV.published_at, BV.default_audio_language,
        )).all()
        subs = dict(s.execute(select(TC.channel_id, TC.subscriber_count)).all())

    recs = []
    for vid, ch, title, outlier, med, dur, pub, lang in rows:
        if outlier is None or med is None or (dur or 0) < 60:
            continue
        if not is_probably_english(title or "", lang):
            continue
        rec = _title_feats(title)
        rec["log_duration"] = math.log1p(dur or 0)
        rec["log_channel_median"] = math.log1p(med)
        rec["log_subs"] = math.log1p(subs.get(ch) or 0)
        if pub is not None:
            rec["hour_sin"] = math.sin(2 * math.pi * pub.hour / 24)
            rec["hour_cos"] = math.cos(2 * math.pi * pub.hour / 24)
            rec["dow"] = float(pub.weekday())
        else:
            rec["hour_sin"] = rec["hour_cos"] = rec["dow"] = 0.0
        rec.update({"channel_id": ch, "video_id": vid, "title": title, "outlier": outlier})
        recs.append(rec)

    df = pd.DataFrame(recs)
    if df.empty:
        return df
    counts = df["channel_id"].value_counts()
    df = df[df["channel_id"].isin(counts[counts >= min_per_channel].index)].reset_index(drop=True)
    return df


def add_novelty(df, emb):
    """Cosine distance of each title to its channel's leave-one-out centroid."""
    import pandas as pd

    normed = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    nov = np.zeros(len(df))
    for _, idx in pd.Series(range(len(df))).groupby(df["channel_id"].to_numpy()).groups.items():
        ii = np.asarray(idx)
        if len(ii) < 2:
            continue
        grp = normed[ii]
        centroid = grp.sum(axis=0, keepdims=True) - grp        # leave-one-out sum
        centroid /= (len(ii) - 1)
        centroid /= (np.linalg.norm(centroid, axis=1, keepdims=True) + 1e-9)
        nov[ii] = 1.0 - np.sum(grp * centroid, axis=1)         # 1 - cosine sim
    df = df.copy()
    df["title_novelty"] = nov
    return df


def main() -> None:
    from sklearn.metrics import balanced_accuracy_score, roc_auc_score
    from sklearn.model_selection import GroupKFold
    from xgboost import XGBClassifier

    ap = argparse.ArgumentParser()
    ap.add_argument("--min-per-channel", type=int, default=8)
    args = ap.parse_args()

    print("=" * 74)
    print("PRE-LAUNCH CEILING TEST — best honest model, channel-grouped CV")
    print("=" * 74)
    df = load_data(args.min_per_channel)
    if df.empty or df["channel_id"].nunique() < 20:
        print("Not enough data.")
        return

    emb = _embed(df["title"].tolist(), df["video_id"].tolist())
    df = add_novelty(df, emb)

    scalar_cols = (
        list(TITLE_FEATURES)
        + ["log_duration", "log_channel_median", "log_subs", "hour_sin", "hour_cos", "dow",
           "title_novelty"]
    )
    Xs = df[scalar_cols].astype(float).fillna(0).to_numpy()
    cut = df["outlier"].quantile(1 - TOP_FRACTION)
    y = (df["outlier"] >= cut).astype(int).to_numpy()
    groups = df["channel_id"].to_numpy()

    def run(X, label):
        oof = np.zeros(len(y))
        for tr, te in GroupKFold(n_splits=5).split(X, y, groups):
            clf = XGBClassifier(
                n_estimators=300, max_depth=5, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
                scale_pos_weight=(y[tr] == 0).sum() / max(1, (y[tr] == 1).sum()),
            )
            clf.fit(X[tr], y[tr])
            oof[te] = clf.predict_proba(X[te])[:, 1]
        thr = np.quantile(oof, 1 - y.mean())
        auc = roc_auc_score(y, oof)
        bacc = balanced_accuracy_score(y, (oof >= thr).astype(int))
        print(f"  {label:34} AUC {auc:.3f}   bal-acc {bacc:.3f}")
        return auc

    print(f"  rows={len(df):,}  channels={df['channel_id'].nunique():,}  "
          f"positives={int(y.sum()):,} ({y.mean():.0%})")
    print(f"  {'':34}{'(baseline AUC 0.500)'}")
    run(Xs, "scalar (title+timing+novelty+scale)")
    run(np.hstack([Xs, emb]), "+ 384-dim title embedding (FULL)")
    print("\n  → AUC ≈ 0.50 confirms the pre-launch ceiling; > ~0.55 = a real (if modest) edge.")


if __name__ == "__main__":
    main()
