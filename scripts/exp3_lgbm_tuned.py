#!/usr/bin/env python3
"""Experiment 3: LightGBM with more trees and tuning."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pickle
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import balanced_accuracy_score, f1_score
from lightgbm import LGBMClassifier

print("="*60)
print("🌲 EXPERIMENT 3: LightGBM Tuned (500 trees)")
print("="*60)

# Load cached data
cache_dir = Path("data/cache")
features_cache = cache_dir / "exp_features.pkl"
embeddings_cache = cache_dir / "exp_embeddings.npy"

if not features_cache.exists():
    print("❌ Run exp1_baseline.py first!")
    exit(1)

print("📦 Loading cached data...")
with open(features_cache, 'rb') as f:
    cache = pickle.load(f)
X_base = cache['X_base']
y = cache['y']
embeddings = np.load(embeddings_cache)

X = np.hstack([X_base, embeddings])
print(f"   Samples: {len(y):,} | Features: {X.shape[1]}")

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)

print("\n🚀 Training LightGBM (500 trees, depth 8)...")
model = LGBMClassifier(
    n_estimators=500,
    max_depth=8,
    learning_rate=0.05,
    num_leaves=50,
    min_child_samples=30,
    subsample=0.8,
    colsample_bytree=0.8,
    class_weight='balanced',
    random_state=42,
    verbosity=-1
)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
acc = balanced_accuracy_score(y_test, y_pred)
f1 = f1_score(y_test, y_pred)

print(f"\n{'='*60}")
print(f"✅ RESULTS: LightGBM Tuned")
print(f"{'='*60}")
print(f"   Balanced Accuracy: {acc*100:.2f}%")
print(f"   F1 Score: {f1:.3f}")

# Save
results_file = cache_dir / "results.txt"
with open(results_file, 'a') as f:
    f.write(f"Exp3 LightGBM Tuned (500 trees): {acc*100:.2f}% balanced acc, F1={f1:.3f}\n")
print(f"\n📝 Result saved to {results_file}")




