"""Retrain the content classifier on the REBUILT backfill dataset.

The original training data was lost (memory/ml-data-disconnected.md). The
``backfill_videos`` table reconstructs a fresh labelled set from channels' live
upload history. This trains a "will this title over-perform for its channel"
classifier on it and reports the **honest, channel-grouped** metric.

Scope is deliberate. The served ``clean_predictor.pkl`` uses 409 features (25
hand-crafted + 384 title embeddings); of the 25, ten are thumbnail-image
features and four are point-in-time channel-trend features — neither can be
faithfully reconstructed from backfill (no analyzed thumbnail pixels; no
historical channel state at each past upload). So this trains on what the
recovered data *does* support and the product is actually about — the **title**
(9 features) + **channel scale** (log channel median, log subs), optionally +
title embeddings (``--embeddings``; Phase 6.1 found these add ~no signal).

Honesty guardrails:
- **Label** = top-30% performer by ``outlier`` (views vs the channel's own
  median) — the same target the served model uses, but channel-relative so it
  isn't just "big channel".
- **GroupKFold by ``channel_id``** so a channel is never in train+test (random
  splits leak per-channel baselines and inflate the score — remediation 2.1).
- Reports **lift over the majority-class baseline**, not raw accuracy.

Usage:
    python -m scripts.train_content_from_backfill                 # lean (title + scale)
    python -m scripts.train_content_from_backfill --embeddings    # + 384-dim title embeddings
    python -m scripts.train_content_from_backfill --min-per-channel 8
"""
from __future__ import annotations

import argparse
import math
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np

TITLE_FEATURES = [
    "title_len", "title_words", "has_number", "has_question",
    "has_exclamation", "has_brackets", "caps_ratio", "emotional", "sentiment",
]
SCALE_FEATURES = ["log_channel_avg", "log_subs"]
THUMB_FEATURES = [
    "brightness", "saturation", "contrast", "has_face", "face_count",
    "face_area_ratio", "has_text", "visual_complexity", "edge_density",
]
TOP_FRACTION = 0.30          # "top 30% performer" — matches the served target
ARTIFACT = Path("data/models/content_from_backfill.pkl")
THUMB_CACHE = Path("data/cache/thumb_features.pkl")   # video_id -> thumb feature dict


def _title_feats(title: str) -> dict:
    from src.features.title_analyzer import TitleAnalyzer

    f = TitleAnalyzer().analyze(title or "")
    return {
        "title_len": f.char_length, "title_words": f.word_count,
        "has_number": int(f.has_number), "has_question": int(f.has_question),
        "has_exclamation": int(f.has_exclamation), "has_brackets": int(f.has_brackets),
        "caps_ratio": f.caps_ratio, "emotional": f.emotional_score, "sentiment": f.sentiment,
    }


def load_frame(min_per_channel: int):
    """Backfill rows (English long-form) -> feature DataFrame + label + groups."""
    import pandas as pd
    from sqlalchemy import select

    from src.database.connection import get_session
    from src.database.models import BackfillVideo as BV
    from src.database.models import TrackedChannel as TC
    from src.features.language import is_probably_english

    with get_session() as s:
        rows = s.execute(select(
            BV.video_id, BV.channel_id, BV.title, BV.outlier, BV.channel_median_views,
            BV.duration_seconds, BV.default_audio_language, BV.thumbnail_url,
        )).all()
        subs = dict(s.execute(select(TC.channel_id, TC.subscriber_count)).all())

    recs = []
    for video_id, ch, title, outlier, med, dur, lang, thumb in rows:
        if outlier is None or med is None:
            continue
        if (dur or 0) < 60:                       # Shorts behave differently — exclude
            continue
        if not is_probably_english(title or "", lang):
            continue
        rec = _title_feats(title)
        rec["log_channel_avg"] = math.log1p(med)
        rec["log_subs"] = math.log1p(subs.get(ch) or 0)
        rec["channel_id"] = ch
        rec["video_id"] = video_id
        rec["thumbnail_url"] = thumb
        rec["outlier"] = outlier
        rec["title"] = title
        recs.append(rec)

    df = pd.DataFrame(recs)
    if df.empty:
        return df
    # Keep channels with enough videos so the channel-relative label is meaningful.
    counts = df["channel_id"].value_counts()
    keep = counts[counts >= min_per_channel].index
    df = df[df["channel_id"].isin(keep)].reset_index(drop=True)
    # Label: top-30% by outlier across the kept set.
    cut = df["outlier"].quantile(1 - TOP_FRACTION)
    df["label"] = (df["outlier"] >= cut).astype(int)
    return df


def _load_thumb_cache() -> dict:
    if THUMB_CACHE.exists():
        with open(THUMB_CACHE, "rb") as fh:
            return pickle.load(fh)
    return {}


def add_thumbnail_features(df, max_thumbs: int):
    """Download + analyse thumbnails (cached on disk), keep rows that succeed.

    Returns the subset DataFrame with THUMB_FEATURES columns populated. Cache is
    keyed by video_id so re-runs are incremental — extend max_thumbs to grow it.
    """
    from src.features.thumbnail_analyzer import ThumbnailAnalyzer

    cache = _load_thumb_cache()
    analyzer = ThumbnailAnalyzer(enable_face_detection=True, enable_text_detection=False)

    todo = df[~df["video_id"].isin(cache) & df["thumbnail_url"].notna()]
    todo = todo.head(max_thumbs)
    print(f"  thumbnails: {len(cache):,} cached, analysing {len(todo):,} more…")
    done = 0
    for vid, url in zip(todo["video_id"], todo["thumbnail_url"]):
        feats = analyzer.analyze_from_url_sync(url)
        if feats is not None:
            cache[vid] = {
                "brightness": feats.brightness, "saturation": feats.saturation,
                "contrast": feats.contrast, "has_face": int(feats.has_face),
                "face_count": feats.face_count, "face_area_ratio": feats.face_area_ratio,
                "has_text": int(feats.has_text), "visual_complexity": feats.visual_complexity,
                "edge_density": feats.edge_density,
            }
        done += 1
        if done % 200 == 0:
            THUMB_CACHE.parent.mkdir(parents=True, exist_ok=True)
            with open(THUMB_CACHE, "wb") as fh:
                pickle.dump(cache, fh)
            print(f"    …{done:,}/{len(todo):,}")
    THUMB_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(THUMB_CACHE, "wb") as fh:
        pickle.dump(cache, fh)

    have = df[df["video_id"].isin(cache)].copy()
    for col in THUMB_FEATURES:
        have[col] = have["video_id"].map(lambda v: cache[v][col])
    return have.reset_index(drop=True)


def evaluate(df, use_embeddings: bool, use_thumbnails: bool):
    from sklearn.metrics import balanced_accuracy_score, f1_score
    from sklearn.model_selection import GroupKFold
    from xgboost import XGBClassifier

    feat_cols = list(TITLE_FEATURES + SCALE_FEATURES)
    if use_thumbnails:
        feat_cols += THUMB_FEATURES
    X = df[feat_cols].astype(float).values
    if use_embeddings:
        emb = _embed_titles(df["title"].tolist())
        X = np.hstack([X, emb])
        feat_cols += [f"emb_{i}" for i in range(emb.shape[1])]
    y = df["label"].values
    groups = df["channel_id"].values

    gkf = GroupKFold(n_splits=5)
    oof = np.zeros(len(y))
    for tr, te in gkf.split(X, y, groups):
        clf = XGBClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
            scale_pos_weight=(y[tr] == 0).sum() / max(1, (y[tr] == 1).sum()),
        )
        clf.fit(X[tr], y[tr])
        oof[te] = clf.predict_proba(X[te])[:, 1]

    preds = (oof >= 0.5).astype(int)
    bacc = balanced_accuracy_score(y, preds)
    f1 = f1_score(y, preds, zero_division=0)
    return feat_cols, X, y, bacc, f1


def _embed_titles(titles):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")
    return np.asarray(model.encode(titles, batch_size=128, show_progress_bar=True), dtype=float)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embeddings", action="store_true", help="add 384-dim title embeddings")
    ap.add_argument("--thumbnails", action="store_true", help="add thumbnail image features")
    ap.add_argument("--max-thumbs", type=int, default=8000, help="cap thumbnails analysed per run")
    ap.add_argument("--min-per-channel", type=int, default=5)
    args = ap.parse_args()

    print("Loading backfill dataset…")
    df = load_frame(args.min_per_channel)
    if df.empty or df["channel_id"].nunique() < 5:
        print("Not enough backfill data yet (need ≥5 channels with videos). "
              "Let the backfill job run longer.")
        return

    parts = ["title+scale"]
    if args.thumbnails:
        df = add_thumbnail_features(df, args.max_thumbs)
        # Re-derive the label/min-channel filter on the thumbnail subset so it's
        # internally consistent (top-30% within the evaluated set).
        counts = df["channel_id"].value_counts()
        df = df[df["channel_id"].isin(counts[counts >= args.min_per_channel].index)].reset_index(drop=True)
        cut = df["outlier"].quantile(1 - TOP_FRACTION)
        df["label"] = (df["outlier"] >= cut).astype(int)
        parts.append("thumb")
    if args.embeddings:
        parts.append("emb")
    if df.empty or df["channel_id"].nunique() < 5:
        print("Not enough rows with thumbnail features yet — raise --max-thumbs.")
        return

    pos = int(df["label"].sum())
    print(f"  rows={len(df):,}  channels={df['channel_id'].nunique():,}  "
          f"positives={pos:,} ({pos / len(df):.1%})")

    feat_cols, X, y, bacc, f1 = evaluate(df, args.embeddings, args.thumbnails)

    # Apples-to-apples: title+scale only, on the SAME rows, when extras are on.
    base_note = ""
    if args.thumbnails or args.embeddings:
        _, _, _, b0, _ = evaluate(df, use_embeddings=False, use_thumbnails=False)
        base_note = f"   (title+scale only, same rows: {b0:.3f})"

    # Baseline: majority-class predictor -> balanced acc 0.5 by construction.
    print("\n── Honest channel-grouped CV (GroupKFold by channel_id) ──")
    print(f"  features:          {len(feat_cols)} ({'+'.join(parts)})")
    print(f"  balanced accuracy: {bacc:.3f}{base_note}")
    print("                     (baseline 0.500, served clean_predictor 0.746*)")
    print(f"  F1:                {f1:.3f}   (served clean_predictor 0.638*)")
    print(f"  lift over baseline:{bacc - 0.5:+.3f}")
    print("  * served metric is on the LOST dataset w/ thumbnail+PIT features — not apples-to-apples")

    # Refit on all data and save a candidate artifact (does NOT touch the served model).
    from xgboost import XGBClassifier

    clf = XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
        scale_pos_weight=(y == 0).sum() / max(1, (y == 1).sum()),
    )
    clf.fit(X, y)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    with open(ARTIFACT, "wb") as fh:
        pickle.dump({
            "model": clf, "feature_cols": feat_cols, "model_type": "content_from_backfill",
            "balanced_accuracy": float(bacc), "f1_score": float(f1),
            "target": f"top_{int(TOP_FRACTION * 100)}pct_outlier", "n_samples": int(len(df)),
            "trained_at": datetime.utcnow().isoformat(),
        }, fh)
    print(f"\nSaved candidate artifact → {ARTIFACT} (served model untouched)")


if __name__ == "__main__":
    main()
