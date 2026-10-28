#!/usr/bin/env python3
"""Experiment 4: Deeper Neural Network."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pickle
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import balanced_accuracy_score, f1_score
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPClassifier

print("="*60)
print("🔮 EXPERIMENT 4: Deep Neural Network (512-256-128-64)")
print("="*60)

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

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s = scaler.transform(X_test)

print("\n🚀 Training Deep MLP (512-256-128-64)...")
model = MLPClassifier(
    hidden_layer_sizes=(512, 256, 128, 64),
    activation='relu',
    learning_rate_init=0.0005,
    max_iter=500,
    early_stopping=True,
    validation_fraction=0.1,
    n_iter_no_change=20,
    random_state=42,
    verbose=True
)
model.fit(X_train_s, y_train)

y_pred = model.predict(X_test_s)
acc = balanced_accuracy_score(y_test, y_pred)
f1 = f1_score(y_test, y_pred)

print(f"\n{'='*60}")
print(f"✅ RESULTS: Deep MLP")
print(f"{'='*60}")
print(f"   Balanced Accuracy: {acc*100:.2f}%")
print(f"   F1 Score: {f1:.3f}")

results_file = cache_dir / "results.txt"
with open(results_file, 'a') as f:
    f.write(f"Exp4 Deep MLP (512-256-128-64): {acc*100:.2f}% balanced acc, F1={f1:.3f}\n")
print(f"\n📝 Result saved to {results_file}")




