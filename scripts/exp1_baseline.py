#!/usr/bin/env python3
"""Experiment 1: LightGBM Baseline with full data."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pickle
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import balanced_accuracy_score, f1_score
from lightgbm import LGBMClassifier
from sentence_transformers import SentenceTransformer

from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures

print("="*60)
print("📊 EXPERIMENT 1: LightGBM Baseline")
print("="*60)

# Check for cached data
cache_dir = Path("data/cache")
cache_dir.mkdir(exist_ok=True)
features_cache = cache_dir / "exp_features.pkl"
embeddings_cache = cache_dir / "exp_embeddings.npy"

if features_cache.exists() and embeddings_cache.exists():
    print("📦 Loading cached data...")
    with open(features_cache, 'rb') as f:
        cache = pickle.load(f)
    X_base = cache['X_base']
    y = cache['y']
    embeddings = np.load(embeddings_cache)
    print(f"   Loaded {len(y):,} samples")
else:
    print("📊 Loading from database...")
    with get_session() as session:
        query = session.query(
            Video.video_id, Video.title, Video.view_count,
            Channel.subscriber_count, Channel.avg_views_per_video,
            VideoFeatures.title_char_length, VideoFeatures.title_word_count,
            VideoFeatures.title_has_number, VideoFeatures.title_has_question,
            VideoFeatures.title_has_exclamation, VideoFeatures.title_has_brackets,
            VideoFeatures.title_caps_ratio, VideoFeatures.title_emotional_score,
            VideoFeatures.title_sentiment, VideoFeatures.brightness,
            VideoFeatures.saturation, VideoFeatures.contrast,
            VideoFeatures.has_face, VideoFeatures.face_count,
            VideoFeatures.face_area_ratio, VideoFeatures.has_text,
            VideoFeatures.text_word_count, VideoFeatures.visual_complexity,
            VideoFeatures.edge_density,
            VideoFeatures.channel_momentum_at_upload,
            VideoFeatures.channel_engagement_trend_at_upload,
            VideoFeatures.channel_hit_rate_at_upload,
            VideoFeatures.channel_recent_avg_ratio_at_upload,
        ).join(Channel, Video.channel_id == Channel.channel_id
        ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).filter(Video.view_count > 0, Channel.avg_views_per_video > 0, Channel.subscriber_count > 1000).all()

    columns = ['video_id', 'title', 'view_count', 'subscriber_count', 'avg_views_per_video',
               'title_len', 'title_words', 'has_number', 'has_question', 'has_exclamation',
               'has_brackets', 'caps_ratio', 'emotional', 'sentiment', 'brightness',
               'saturation', 'contrast', 'has_face', 'face_count', 'face_area_ratio',
               'has_text', 'text_words', 'visual_complexity', 'edge_density',
               'pit_momentum', 'pit_engagement_trend', 'pit_hit_rate', 'pit_recent_ratio']
    df = pd.DataFrame(query, columns=columns)
    print(f"   Loaded {len(df):,} videos")

    # Target
    df['perf_ratio'] = df['view_count'] / df['avg_views_per_video'].clip(lower=1)
    threshold = df['perf_ratio'].quantile(0.70)
    y = (df['perf_ratio'] >= threshold).astype(int).values
    print(f"   Target: {y.mean()*100:.1f}% positive")

    # Features
    df['log_subs'] = np.log1p(df['subscriber_count'])
    df['log_channel_avg'] = np.log1p(df['avg_views_per_video'])
    
    feature_cols = ['title_len', 'title_words', 'has_number', 'has_question', 'has_exclamation',
                    'has_brackets', 'caps_ratio', 'emotional', 'sentiment', 'brightness',
                    'saturation', 'contrast', 'has_face', 'face_count', 'face_area_ratio',
                    'has_text', 'text_words', 'visual_complexity', 'edge_density',
                    'pit_momentum', 'pit_engagement_trend', 'pit_hit_rate', 'pit_recent_ratio',
                    'log_subs', 'log_channel_avg']
    
    for col in ['has_number', 'has_question', 'has_exclamation', 'has_brackets', 'has_face', 'has_text']:
        df[col] = df[col].fillna(0).astype(int)
    for col in feature_cols:
        df[col] = df[col].fillna(0)
    
    X_base = df[feature_cols].values

    # Embeddings
    print("🧠 Generating embeddings...")
    model_emb = SentenceTransformer('all-MiniLM-L6-v2')
    embeddings = model_emb.encode(df['title'].tolist(), show_progress_bar=True, batch_size=512)
    
    # Cache
    print("💾 Caching data...")
    with open(features_cache, 'wb') as f:
        pickle.dump({'X_base': X_base, 'y': y}, f)
    np.save(embeddings_cache, embeddings)

# Combine
X = np.hstack([X_base, embeddings])
print(f"   Features: {X.shape[1]}")

# Split and train
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)
print(f"   Train: {len(X_train):,} | Test: {len(X_test):,}")

print("\n🚀 Training LightGBM...")
model = LGBMClassifier(n_estimators=200, max_depth=6, learning_rate=0.1,
                       class_weight='balanced', random_state=42, verbosity=-1)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
acc = balanced_accuracy_score(y_test, y_pred)
f1 = f1_score(y_test, y_pred)

print(f"\n{'='*60}")
print(f"✅ RESULTS: LightGBM Baseline")
print(f"{'='*60}")
print(f"   Balanced Accuracy: {acc*100:.2f}%")
print(f"   F1 Score: {f1:.3f}")

# Save result
results_file = cache_dir / "results.txt"
with open(results_file, 'a') as f:
    f.write(f"Exp1 LightGBM: {acc*100:.2f}% balanced acc, F1={f1:.3f}\n")
print(f"\n📝 Result saved to {results_file}")




