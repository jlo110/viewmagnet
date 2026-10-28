"""Phase 6.1 — Multimodal pre-upload performance predictor.

Builds an "will this video overperform?" classifier from the surviving 144k
feature cache, and measures whether adding **thumbnail** + better **text**
embeddings beats the currently-served model (`clean_predictor.pkl`,
balanced-acc 0.746 / F1 0.638, which uses 25 hand-crafted features + 384-dim
title embeddings and NO thumbnail signal).

Feature variants compared:
  base       : 25 hand-crafted features only
  current    : 25 + 384-dim title emb        (≈ the served model)
  text+      : 25 + 768-dim mpnet title emb   (better text)
  multimodal : 25 + 768 title + 576 thumbnail CNN emb   (the upgrade)

CV: StratifiedKFold by default (apples-to-apples with the served model, which
was random-split). Pass --channel-map <json: {video_id: channel_id}> to use
**channel-grouped** CV (StratifiedGroupKFold) for the honest, leakage-free
number — resolve it with scripts/seed_tracked_channels-style YouTube lookups.

Data (all row-aligned to data/cache/video_ids.txt):
  data/cache/exp_features.pkl     X_base (N,25) + y (N,)
  data/cache/exp_embeddings.npy   (N,384) title
  data/cache/large_embeddings.npy (N,768) mpnet title
  data/cnn_embeddings_cache.pkl   {thumbnail_url: (576,)} thumbnail CNN

Usage:
  python -m scripts.train_multimodal_predictor --sample 40000 --folds 3
  python -m scripts.train_multimodal_predictor            # full data, 5 folds
  python -m scripts.train_multimodal_predictor --save     # also fit+save best on all data
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np

CACHE = Path("data/cache")
THUMB_CACHE = Path("data/cnn_embeddings_cache.pkl")
SERVED_BALANCED_ACC = 0.746  # current clean_predictor.pkl, for reference


def _load_base():
    d = pickle.load(open(CACHE / "exp_features.pkl", "rb"))
    return np.asarray(d["X_base"], dtype=np.float32), np.asarray(d["y"]).astype(int)


def _load_video_ids() -> list[str]:
    return [l.strip() for l in open(CACHE / "video_ids.txt") if l.strip()]


def _load_thumbnail_matrix(video_ids: list[str]) -> tuple[np.ndarray, float]:
    """Align thumbnail CNN embeddings to rows via the maxresdefault URL.
    Missing thumbnails get a zero vector. Returns (matrix, coverage)."""
    cache = pickle.load(open(THUMB_CACHE, "rb"))
    dim = len(next(iter(cache.values())))
    mat = np.zeros((len(video_ids), dim), dtype=np.float32)
    hit = 0
    for i, vid in enumerate(video_ids):
        emb = cache.get(f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg")
        if emb is not None:
            mat[i] = emb
            hit += 1
    return mat, hit / max(1, len(video_ids))


def _cv_score(X, y, groups, folds):
    """Mean/std balanced-acc, F1, AUC across folds (grouped if groups given)."""
    from sklearn.metrics import balanced_accuracy_score, f1_score, roc_auc_score
    from xgboost import XGBClassifier

    if groups is not None:
        from sklearn.model_selection import StratifiedGroupKFold
        splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=42)
        split = splitter.split(X, y, groups)
    else:
        from sklearn.model_selection import StratifiedKFold
        splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
        split = splitter.split(X, y)

    bal, f1, auc = [], [], []
    for tr, te in split:
        clf = XGBClassifier(
            n_estimators=300, max_depth=6, learning_rate=0.1,
            subsample=0.8, colsample_bytree=0.8, tree_method="hist",
            eval_metric="logloss", random_state=42, n_jobs=-1,
        )
        clf.fit(X[tr], y[tr])
        proba = clf.predict_proba(X[te])[:, 1]
        pred = (proba >= 0.5).astype(int)
        bal.append(balanced_accuracy_score(y[te], pred))
        f1.append(f1_score(y[te], pred))
        auc.append(roc_auc_score(y[te], proba))
    return {
        "balanced_acc": (float(np.mean(bal)), float(np.std(bal))),
        "f1": (float(np.mean(f1)), float(np.std(f1))),
        "auc": (float(np.mean(auc)), float(np.std(auc))),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=None, help="subsample N rows for speed")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--channel-map", help="json {video_id: channel_id} -> grouped CV")
    ap.add_argument("--save", action="store_true", help="fit best variant on all data + save")
    args = ap.parse_args()

    print("=" * 74)
    print("6.1 MULTIMODAL PREDICTOR — feature-variant comparison")
    print("=" * 74)

    X_base, y = _load_base()
    video_ids = _load_video_ids()
    title384 = np.load(CACHE / "exp_embeddings.npy")
    title768 = np.load(CACHE / "large_embeddings.npy")
    thumb, coverage = _load_thumbnail_matrix(video_ids)
    print(f"rows={len(y):,}  positives={y.mean():.1%}  thumbnail coverage={coverage:.1%}")

    idx = np.arange(len(y))

    # Channel-grouped CV: restrict to videos with a resolved channel so the
    # grouping is real (no singleton-group dilution from unmapped rows).
    cmap = None
    if args.channel_map:
        cmap = json.load(open(args.channel_map))
        mapped = set(cmap)
        idx = idx[[video_ids[i] in mapped for i in idx]]
        print(f"restricted to {len(idx):,} videos with a resolved channel")

    if args.sample and args.sample < len(idx):
        rng = np.random.default_rng(42)
        idx = rng.choice(idx, size=args.sample, replace=False)
        print(f"subsampled to {len(idx):,} rows")

    groups = None
    if cmap is not None:
        groups = np.array([cmap[video_ids[i]] for i in idx])
        print(f"channel-grouped CV: {len(set(groups)):,} groups")
    else:
        print("StratifiedKFold (random split — apples-to-apples w/ served model)")

    # PCA-denoised embedding variants: trees handle a few dense PCA components
    # far better than hundreds of raw, noisy embedding dims.
    from sklearn.decomposition import PCA

    def _pca(mat, k):
        return PCA(n_components=k, random_state=42).fit_transform(mat.astype(np.float32))

    title_pca = _pca(title768, 48)
    thumb_pca = _pca(thumb, 48)

    variants = {
        "base       ": X_base[idx],
        "current    ": np.hstack([X_base, title384])[idx],
        "text+      ": np.hstack([X_base, title768])[idx],
        "multimodal ": np.hstack([X_base, title768, thumb])[idx],
        "base+txtPCA": np.hstack([X_base, title_pca])[idx],
        "base+thmPCA": np.hstack([X_base, thumb_pca])[idx],
        "mm_pca     ": np.hstack([X_base, title_pca, thumb_pca])[idx],
    }

    print(f"\n{'variant':<12}{'features':>9}  {'balanced_acc':>16}{'F1':>14}{'AUC':>14}")
    best = None
    for name, X in variants.items():
        s = _cv_score(np.ascontiguousarray(X), y[idx], groups, args.folds)
        ba, f1, auc = s["balanced_acc"], s["f1"], s["auc"]
        print(f"{name:<12}{X.shape[1]:>9}  {ba[0]:>10.3f}±{ba[1]:.3f}{f1[0]:>9.3f}±{f1[1]:.3f}{auc[0]:>9.3f}±{auc[1]:.3f}")
        if best is None or ba[0] > best[1]:
            best = (name.strip(), ba[0], X)

    print("-" * 74)
    print(f"served clean_predictor.pkl reference: balanced_acc {SERVED_BALANCED_ACC:.3f}")
    print(f"best variant: {best[0]} (balanced_acc {best[1]:.3f}) "
          f"-> {'+' if best[1] > SERVED_BALANCED_ACC else ''}{(best[1]-SERVED_BALANCED_ACC):.3f} vs served")
    if args.channel_map is None:
        print("NOTE: random-split numbers (inflated by channel leakage, like the served "
              "model). Re-run with --channel-map for the honest grouped figure.")

    if args.save:
        from xgboost import XGBClassifier
        clf = XGBClassifier(n_estimators=400, max_depth=6, learning_rate=0.08,
                            subsample=0.8, colsample_bytree=0.8, tree_method="hist",
                            eval_metric="logloss", random_state=42, n_jobs=-1)
        clf.fit(np.ascontiguousarray(best[2]), y[idx])
        out = Path("data/models/multimodal_predictor.pkl")
        pickle.dump({"model": clf, "variant": best[0], "cv_balanced_acc": best[1]}, open(out, "wb"))
        print(f"saved best ({best[0]}) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
