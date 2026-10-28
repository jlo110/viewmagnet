#!/usr/bin/env python3
"""Save best XGBoost model as production model."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pickle
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import balanced_accuracy_score, f1_score
from xgboost import XGBClassifier

print("🏆 Saving Best Model (XGBoost) as Production")
print("="*50)

cache_dir = Path("data/cache")
features_cache = cache_dir / "exp_features.pkl"
embeddings_cache = cache_dir / "exp_embeddings.npy"

print("📦 Loading cached data...")
with open(features_cache, 'rb') as f:
    cache = pickle.load(f)
X_base = cache['X_base']
y = cache['y']
embeddings = np.load(embeddings_cache)

X = np.hstack([X_base, embeddings])
print(f"   Samples: {len(y):,} | Features: {X.shape[1]}")

# Split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)

# Calculate scale_pos_weight
scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()

print("\n🚀 Training XGBoost (production config)...")
model = XGBClassifier(
    n_estimators=300,
    max_depth=7,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    scale_pos_weight=scale_pos_weight,
    random_state=42,
    verbosity=0,
    use_label_encoder=False,
    eval_metric='logloss'
)
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
acc = balanced_accuracy_score(y_test, y_pred)
f1 = f1_score(y_test, y_pred)

print(f"\n✅ Performance:")
print(f"   Balanced Accuracy: {acc*100:.2f}%")
print(f"   F1 Score: {f1:.3f}")

# Feature names
feature_cols = [
    'title_len', 'title_words', 'has_number', 'has_question', 'has_exclamation',
    'has_brackets', 'caps_ratio', 'emotional', 'sentiment', 'brightness',
    'saturation', 'contrast', 'has_face', 'face_count', 'face_area_ratio',
    'has_text', 'text_words', 'visual_complexity', 'edge_density',
    'pit_momentum', 'pit_engagement_trend', 'pit_hit_rate', 'pit_recent_ratio',
    'log_subs', 'log_channel_avg'
]
emb_cols = [f'emb_{i}' for i in range(384)]
all_feature_cols = feature_cols + emb_cols

# Save model
model_path = Path("data/models/production_model.pkl")
model_path.parent.mkdir(exist_ok=True)

with open(model_path, 'wb') as f:
    pickle.dump({
        'model': model,
        'feature_cols': all_feature_cols,
        'model_type': 'XGBoost',
        'balanced_accuracy': acc,
        'f1_score': f1,
        'training_samples': len(X_train),
        'test_samples': len(X_test),
    }, f)

print(f"\n💾 Saved to {model_path}")

# Also update clean_predictor.pkl for API
clean_path = Path("data/models/clean_predictor.pkl")
with open(clean_path, 'wb') as f:
    pickle.dump({
        'model': model,
        'feature_cols': all_feature_cols,
        'model_type': 'XGBoost',
        'balanced_accuracy': acc,
        'f1_score': f1,
    }, f)
print(f"💾 Also saved to {clean_path} (for API)")

print("\n✅ Done!")




