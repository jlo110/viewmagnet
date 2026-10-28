"""Prototype REACH predictor — predicts absolute breakout, where thumbnails matter.

Phase 6.1 finding: the 25 hand-crafted features predict "beat your own channel"
well (AUC ~0.79) but are useless for ABSOLUTE reach (AUC ~0.51). The
thumbnail + title (via CLIP) are what predict breakout — base+CLIP lifts
absolute-reach AUC 0.51 -> ~0.60. So a *reach* predictor is a different,
thumbnail-driven model from the served overperform classifier.

This trains that model (frozen CLIP features + hand-crafted), grouped-CV
evaluated, and saves it with a manifest. The frozen version is the immediately
usable baseline (~0.60 AUC); end-to-end CLIP fine-tuning is the GPU upgrade.

Target: top-quartile **views-per-subscriber** (log(views / subs)). A high value
= the video reached well beyond the channel's own audience.

Inputs (from the go/no-go pipeline):
  data/thumbnails/clip_feats.npz   Xb(25) + CLIP img(512)/txt(512) + groups + vids
Label (cached so we don't re-hit the YouTube API):
  data/thumbnails/reach_labels.json   {video_id: log_views_per_sub}

Usage:
  python -m scripts.train_reach_predictor               # frozen-CLIP reach model
  python -m scripts.train_reach_predictor --quantile 0.8  # stricter breakout def

Productionization note: at inference this model needs CLIP image+text embeddings
for the candidate thumbnail+title (run CLIP in a separate process/service from
XGBoost — they crash if imported together on macOS). The 512+512 CLIP dims are
the part that carries the reach signal.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

FEATS = Path("data/thumbnails/clip_feats.npz")
LABELS = Path("data/thumbnails/reach_labels.json")
OUT = Path("data/models/reach_predictor.pkl")


def _load_or_build_labels(vids) -> dict:
    """Return {video_id: log(views/subs)}, fetching from YouTube once and caching."""
    if LABELS.exists():
        cached = json.load(open(LABELS))
        if all(v in cached for v in vids):
            print(f"using cached reach labels ({len(cached):,})")
            return cached
    else:
        cached = {}

    from scripts.clip_thumbnail_experiment import _fetch_views_and_subs

    print(f"fetching views + subs for {len(vids):,} videos (one-time)...")
    vc, sv = _fetch_views_and_subs(vids)
    for v, c, s in zip(vids, vc, sv):
        if c >= 0:
            cached[str(v)] = float(np.log1p(c / max(s, 1)))
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    json.dump(cached, open(LABELS, "w"))
    print(f"cached {len(cached):,} reach labels -> {LABELS}")
    return cached


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quantile", type=float, default=0.75,
                    help="breakout threshold on views-per-sub (0.75 = top quartile)")
    ap.add_argument("--folds", type=int, default=5)
    args = ap.parse_args()

    import pickle

    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedGroupKFold
    from xgboost import XGBClassifier

    if not FEATS.exists():
        print(f"{FEATS} missing — run clip_thumbnail_experiment --phase extract first.")
        return 1
    z = np.load(FEATS, allow_pickle=True)
    Xb, groups, vids = z["Xb"], z["groups"], [str(v) for v in z["vids"]]
    img_emb, txt_emb = z["img_emb"], z["txt_emb"]

    labels = _load_or_build_labels(vids)
    have = np.array([v in labels for v in vids])
    vps = np.array([labels.get(v, 0.0) for v in vids])[have]
    Xb, img_emb, txt_emb, groups = Xb[have], img_emb[have], txt_emb[have], groups[have]
    y = (vps >= np.quantile(vps, args.quantile)).astype(int)
    print(f"{have.sum():,} videos / {len(set(groups.tolist())):,} channels; "
          f"breakout positives = {y.mean():.0%}")

    # The reach model = hand-crafted + CLIP image + CLIP text (the winning variant).
    X = np.hstack([Xb, img_emb, txt_emb]).astype(np.float32)
    feature_spec = (["hand_%d" % i for i in range(Xb.shape[1])]
                    + ["clip_img_%d" % i for i in range(img_emb.shape[1])]
                    + ["clip_txt_%d" % i for i in range(txt_emb.shape[1])])

    params = dict(n_estimators=400, max_depth=6, learning_rate=0.06, subsample=0.8,
                  colsample_bytree=0.8, tree_method="hist", eval_metric="logloss",
                  random_state=42, n_jobs=-1)

    # Grouped-CV AUC (honest).
    n = min(args.folds, len(set(groups.tolist())))
    aucs = []
    for tr, te in StratifiedGroupKFold(n_splits=n, shuffle=True, random_state=42).split(X, y, groups):
        m = XGBClassifier(**params).fit(X[tr], y[tr])
        aucs.append(roc_auc_score(y[te], m.predict_proba(X[te])[:, 1]))
    cv_auc = float(np.mean(aucs))
    print(f"grouped-CV AUC = {cv_auc:.3f} ± {np.std(aucs):.3f}  (frozen CLIP)")

    # Final fit on all data + save with manifest.
    final = XGBClassifier(**params).fit(X, y)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump({
        "model": final,
        "feature_spec": feature_spec,
        "model_type": "XGBoost+frozenCLIP",
        "target": f"top-{int((1-args.quantile)*100)}pct log(views/subs)",
        "clip_model": "openai/clip-vit-base-patch32",
        "cv_auc": cv_auc,
        "n_train": int(have.sum()),
    }, open(OUT, "wb"))
    print(f"saved {OUT}  (target={args.quantile:.0%} views/sub, CV AUC {cv_auc:.3f})")
    print("Next: end-to-end CLIP fine-tune on a GPU to push past this frozen baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
