"""Train the LEAN content predictor (25 hand-crafted features, no embeddings).

Phase 6.1 found that the 384-dim title embeddings in the served
`clean_predictor.pkl` (409 features) add no signal — the 25 hand-crafted
features match/beat them under CV. This trains the lean model so the served
inference path can drop the SentenceTransformer dependency entirely.

The saved model's `feature_cols` are the served model's first 25 (the
non-`emb_` names), so `analyze.py` — which builds its input vector by iterating
`feature_cols` — drops straight in with zero feature-extraction changes.

Output: data/models/clean_predictor_lean.pkl

Usage:
    python -m scripts.train_lean_content_model
"""
from __future__ import annotations

import pickle
from pathlib import Path

import joblib
import numpy as np


def main() -> int:
    from sklearn.metrics import balanced_accuracy_score, f1_score, roc_auc_score
    from sklearn.model_selection import train_test_split
    from xgboost import XGBClassifier

    d = pickle.load(open("data/cache/exp_features.pkl", "rb"))
    X = np.asarray(d["X_base"], dtype=np.float32)  # (N, 25)
    y = np.asarray(d["y"]).astype(int)

    # Reuse the served model's first-25 feature names so analyze.py's
    # features.get(col) lines up exactly.
    served = joblib.load("data/models/clean_predictor.pkl")
    served_cols = [c for c in served["feature_cols"] if not c.startswith("emb_")]
    assert len(served_cols) == X.shape[1], (
        f"served has {len(served_cols)} non-emb cols but X_base has {X.shape[1]}"
    )

    # Quick holdout for a sanity metric (the real eval is grouped CV).
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    params = dict(n_estimators=400, max_depth=6, learning_rate=0.08, subsample=0.8,
                  colsample_bytree=0.8, tree_method="hist", eval_metric="logloss",
                  random_state=42, n_jobs=-1)
    clf = XGBClassifier(**params)
    clf.fit(Xtr, ytr)
    proba = clf.predict_proba(Xte)[:, 1]
    pred = (proba >= 0.5).astype(int)
    bal = balanced_accuracy_score(yte, pred)
    f1 = f1_score(yte, pred)
    auc = roc_auc_score(yte, proba)
    print(f"holdout: balanced_acc={bal:.3f}  f1={f1:.3f}  auc={auc:.3f}")

    # Fit final on ALL data and save with the matching feature_cols.
    final = XGBClassifier(**params)
    final.fit(X, y)
    out = Path("data/models/clean_predictor_lean.pkl")
    pickle.dump({
        "model": final,
        "feature_cols": served_cols,
        "model_type": "XGBoost",
        "training": "lean-25feat-no-embeddings",
        "holdout_balanced_accuracy": float(bal),
        "holdout_f1_score": float(f1),
        "holdout_auc": float(auc),
    }, open(out, "wb"))
    print(f"saved {out} ({len(served_cols)} features, no embeddings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
