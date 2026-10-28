#!/usr/bin/env python3
"""
Experiment 9: Multi-Modal Fusion

Combine multiple embedding sources:
- Title embeddings (384d)
- Large title embeddings (768d) 
- Category embeddings (384d)
- Base features (25d)

Total: 1561 features
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pickle
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import balanced_accuracy_score, f1_score
from xgboost import XGBClassifier
from sentence_transformers import SentenceTransformer

print("="*60)
print("🔗 EXPERIMENT 9: Multi-Modal Fusion")
print("="*60)

cache_dir = Path("data/cache")

# Load all cached data
print("\n📦 Loading cached data...")
with open(cache_dir / "exp_features.pkl", 'rb') as f:
    cache = pickle.load(f)
X_base = cache['X_base']
y = cache['y']

title_emb_384 = np.load(cache_dir / "exp_embeddings.npy")
title_emb_768 = np.load(cache_dir / "large_embeddings.npy")

print(f"   Base features: {X_base.shape}")
print(f"   Title embeddings (384d): {title_emb_384.shape}")
print(f"   Title embeddings (768d): {title_emb_768.shape}")

# Generate category embeddings
print("\n🏷️ Generating category embeddings...")
from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures

with get_session() as session:
    categories = [r[0] or 'unknown' for r in session.query(Channel.primary_category
        ).join(Video, Video.channel_id == Channel.channel_id
        ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).filter(Video.view_count > 0, Channel.avg_views_per_video > 0,
                Channel.subscriber_count > 1000).all()]

model = SentenceTransformer('all-MiniLM-L6-v2')
category_emb = model.encode(categories, show_progress_bar=False, batch_size=512)
print(f"   Category embeddings: {category_emb.shape}")

# Combine all features
print("\n🔗 Combining all modalities...")
X_combined = np.hstack([X_base, title_emb_384, title_emb_768, category_emb])
print(f"   Total features: {X_combined.shape[1]}")
print(f"   (25 base + 384 title + 768 large + 384 category)")

# Split
X_train, X_test, y_train, y_test = train_test_split(
    X_combined, y, test_size=0.2, stratify=y, random_state=42
)
print(f"   Train: {len(X_train):,} | Test: {len(X_test):,}")

# Train
print("\n🚀 Training XGBoost with multi-modal features...")
scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()

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

print(f"\n{'='*60}")
print(f"✅ RESULTS: Multi-Modal Fusion")
print(f"{'='*60}")
print(f"   Balanced Accuracy: {acc*100:.2f}%")
print(f"   F1 Score: {f1:.3f}")

baseline = 0.7458
improvement = (acc - baseline) * 100
if improvement > 0:
    print(f"   🎉 Improvement: +{improvement:.2f}%")
else:
    print(f"   📊 vs baseline: {improvement:.2f}%")

# Save
results_file = cache_dir / "results.txt"
with open(results_file, 'a') as f:
    f.write(f"Exp9 Multi-Modal Fusion: {acc*100:.2f}% balanced acc, F1={f1:.3f}\n")
print(f"\n📝 Saved to {results_file}")




