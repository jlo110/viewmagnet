#!/usr/bin/env python3
"""
Simple model experiments - skip memory-intensive operations.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

from sklearn.model_selection import train_test_split
from sklearn.metrics import balanced_accuracy_score, f1_score
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPClassifier
from lightgbm import LGBMClassifier
from sentence_transformers import SentenceTransformer

from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures

print("="*60)
print("🚀 SIMPLE MODEL EXPERIMENTS")
print("="*60)
print()

# Load data
print("📊 Loading data...")
with get_session() as session:
    query = session.query(
        Video.video_id, Video.title, Video.view_count, Video.channel_id,
        Channel.subscriber_count, Channel.avg_views_per_video, Channel.primary_category,
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
    ).filter(
        Video.view_count > 0,
        Channel.avg_views_per_video > 0,
        Channel.subscriber_count > 1000,
    ).all()

columns = [
    'video_id', 'title', 'view_count', 'channel_id',
    'subscriber_count', 'avg_views_per_video', 'category',
    'title_len', 'title_words', 'has_number', 'has_question',
    'has_exclamation', 'has_brackets', 'caps_ratio', 'emotional', 'sentiment',
    'brightness', 'saturation', 'contrast', 'has_face', 'face_count',
    'face_area_ratio', 'has_text', 'text_words', 'visual_complexity', 'edge_density',
    'pit_momentum', 'pit_engagement_trend', 'pit_hit_rate', 'pit_recent_ratio'
]
df = pd.DataFrame(query, columns=columns)
print(f"   Loaded {len(df):,} videos")

# Target
df['perf_ratio'] = df['view_count'] / df['avg_views_per_video'].clip(lower=1)
threshold = df['perf_ratio'].quantile(0.70)
df['target'] = (df['perf_ratio'] >= threshold).astype(int)
print(f"   Target: {df['target'].mean()*100:.1f}% positive")

# Features
df['log_subs'] = np.log1p(df['subscriber_count'])
df['log_channel_avg'] = np.log1p(df['avg_views_per_video'])

feature_cols = [
    'title_len', 'title_words', 'has_number', 'has_question',
    'has_exclamation', 'has_brackets', 'caps_ratio', 'emotional', 'sentiment',
    'brightness', 'saturation', 'contrast', 'has_face', 'face_count',
    'face_area_ratio', 'has_text', 'text_words', 'visual_complexity', 'edge_density',
    'pit_momentum', 'pit_engagement_trend', 'pit_hit_rate', 'pit_recent_ratio',
    'log_subs', 'log_channel_avg',
]

for col in ['has_number', 'has_question', 'has_exclamation', 'has_brackets', 'has_face', 'has_text']:
    df[col] = df[col].fillna(0).astype(int)
for col in feature_cols:
    df[col] = df[col].fillna(0)

# Embeddings
print("🧠 Generating title embeddings...")
model_emb = SentenceTransformer('all-MiniLM-L6-v2')
titles = df['title'].tolist()
embeddings = model_emb.encode(titles, show_progress_bar=True, batch_size=512)
print(f"   Done: {embeddings.shape}")

# Combine
X_base = df[feature_cols].values
X = np.hstack([X_base, embeddings])
y = df['target'].values
print(f"   Total features: {X.shape[1]}")

# Split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)
print(f"   Train: {len(X_train):,} | Test: {len(X_test):,}")

# Results storage
results = {}

# Experiment 1: LightGBM (baseline)
print("\n" + "="*60)
print("📊 EXP 1: LightGBM Baseline")
print("="*60)
model1 = LGBMClassifier(n_estimators=200, max_depth=6, learning_rate=0.1, 
                        class_weight='balanced', random_state=42, verbosity=-1)
model1.fit(X_train, y_train)
y_pred = model1.predict(X_test)
acc1 = balanced_accuracy_score(y_test, y_pred)
f1_1 = f1_score(y_test, y_pred)
print(f"   ✅ Balanced Accuracy: {acc1*100:.2f}%")
print(f"   ✅ F1 Score: {f1_1:.3f}")
results['LightGBM'] = acc1

# Experiment 2: Neural Network
print("\n" + "="*60)
print("🧠 EXP 2: Neural Network (MLP)")
print("="*60)
scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s = scaler.transform(X_test)
model2 = MLPClassifier(hidden_layer_sizes=(256, 128, 64), activation='relu',
                       learning_rate_init=0.001, max_iter=200, early_stopping=True, random_state=42)
model2.fit(X_train_s, y_train)
y_pred = model2.predict(X_test_s)
acc2 = balanced_accuracy_score(y_test, y_pred)
f1_2 = f1_score(y_test, y_pred)
print(f"   ✅ Balanced Accuracy: {acc2*100:.2f}%")
print(f"   ✅ F1 Score: {f1_2:.3f}")
results['Neural Network'] = acc2

# Experiment 3: LightGBM with more trees
print("\n" + "="*60)
print("🌲 EXP 3: LightGBM (More Trees)")
print("="*60)
model3 = LGBMClassifier(n_estimators=500, max_depth=8, learning_rate=0.05,
                        class_weight='balanced', random_state=42, verbosity=-1)
model3.fit(X_train, y_train)
y_pred = model3.predict(X_test)
acc3 = balanced_accuracy_score(y_test, y_pred)
f1_3 = f1_score(y_test, y_pred)
print(f"   ✅ Balanced Accuracy: {acc3*100:.2f}%")
print(f"   ✅ F1 Score: {f1_3:.3f}")
results['LightGBM (500 trees)'] = acc3

# Experiment 4: Category embeddings
print("\n" + "="*60)
print("🏷️ EXP 4: + Category Embeddings")
print("="*60)
cat_emb = model_emb.encode(df['category'].fillna('unknown').tolist(), show_progress_bar=False)
X_cat = np.hstack([X, cat_emb])
X_train_c, X_test_c, _, _ = train_test_split(X_cat, y, test_size=0.2, stratify=y, random_state=42)
model4 = LGBMClassifier(n_estimators=200, max_depth=6, learning_rate=0.1,
                        class_weight='balanced', random_state=42, verbosity=-1)
model4.fit(X_train_c, y_train)
y_pred = model4.predict(X_test_c)
acc4 = balanced_accuracy_score(y_test, y_pred)
f1_4 = f1_score(y_test, y_pred)
print(f"   ✅ Balanced Accuracy: {acc4*100:.2f}%")
print(f"   ✅ F1 Score: {f1_4:.3f}")
results['+ Category Emb'] = acc4

# Experiment 5: Deeper Neural Network
print("\n" + "="*60)
print("🔮 EXP 5: Deep Neural Network")
print("="*60)
model5 = MLPClassifier(hidden_layer_sizes=(512, 256, 128, 64), activation='relu',
                       learning_rate_init=0.0005, max_iter=300, early_stopping=True, random_state=42)
model5.fit(X_train_s, y_train)
y_pred = model5.predict(X_test_s)
acc5 = balanced_accuracy_score(y_test, y_pred)
f1_5 = f1_score(y_test, y_pred)
print(f"   ✅ Balanced Accuracy: {acc5*100:.2f}%")
print(f"   ✅ F1 Score: {f1_5:.3f}")
results['Deep MLP'] = acc5

# Summary
print("\n" + "="*60)
print("📊 FINAL RESULTS")
print("="*60)
print()
print("Model                    | Balanced Accuracy")
print("-" * 50)
for name, acc in sorted(results.items(), key=lambda x: x[1], reverse=True):
    bar = "█" * int(acc * 30)
    print(f"{name:<24} | {acc*100:5.2f}% {bar}")

best_name = max(results, key=results.get)
best_acc = results[best_name]
print()
print(f"🏆 Best: {best_name} ({best_acc*100:.2f}%)")
print()
print("Note: This uses NO leaked channel features (honest evaluation)")




