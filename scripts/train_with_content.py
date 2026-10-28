"""
Train ML model with content features (hook, audio, pacing).

This model uses BOTH pre-upload features (title, thumbnail) AND
content features (hook timing, audio energy, scene changes) to predict performance.

Note: Content features can only be used for POST-upload analysis or
draft video analysis - not for pre-upload prediction.
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures, VideoContentAnalysis
from sentence_transformers import SentenceTransformer
from lightgbm import LGBMClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, roc_auc_score

print("🎯 TRAINING MODEL WITH CONTENT FEATURES")
print("=" * 60)

# Load data
with get_session() as session:
    results = session.query(
        Video.video_id,
        Video.title,
        Video.view_count,
        Video.published_at,
        Channel.subscriber_count,
        Channel.avg_views_per_video,
        Channel.primary_category,
        # Title features
        VideoFeatures.title_char_length,
        VideoFeatures.title_word_count,
        VideoFeatures.title_has_number,
        VideoFeatures.title_has_question,
        VideoFeatures.title_has_exclamation,
        VideoFeatures.title_emotional_score,
        # Thumbnail features
        VideoFeatures.brightness,
        VideoFeatures.saturation,
        VideoFeatures.has_face,
        VideoFeatures.face_count,
        VideoFeatures.has_text,
        VideoFeatures.text_word_count,
        # Content features
        VideoContentAnalysis.hook_face_appears_seconds,
        VideoContentAnalysis.hook_scene_changes_count,
        VideoContentAnalysis.hook_avg_motion,
        VideoContentAnalysis.words_per_minute,
        VideoContentAnalysis.audio_energy_mean,
        VideoContentAnalysis.audio_energy_variance,
        VideoContentAnalysis.has_music_intro,
        VideoContentAnalysis.face_screen_time_ratio,
        VideoContentAnalysis.total_scene_changes,
        VideoContentAnalysis.call_to_action_count,
        VideoContentAnalysis.question_count,
    ).join(
        Channel, Video.channel_id == Channel.channel_id
    ).join(
        VideoFeatures, Video.video_id == VideoFeatures.video_id
    ).join(
        VideoContentAnalysis, Video.video_id == VideoContentAnalysis.video_id
    ).filter(
        VideoContentAnalysis.extraction_success == True,
        Channel.avg_views_per_video > 0,
        Video.view_count > 100
    ).all()

print(f"📊 Loaded {len(results):,} videos with content features")

# Convert to DataFrame
columns = [
    'video_id', 'title', 'views', 'published_at', 'subs', 'channel_avg', 'category',
    'title_len', 'title_words', 'has_number', 'has_question', 'has_exclamation', 'emotional',
    'brightness', 'saturation', 'has_face', 'face_count', 'has_text', 'text_words',
    'hook_face_sec', 'hook_cuts', 'hook_motion', 'wpm', 'audio_energy', 'audio_variance',
    'has_music', 'face_time_ratio', 'total_scenes', 'cta_count', 'question_count'
]
df = pd.DataFrame(results, columns=columns)

# Calculate performance metrics
df['perf_ratio'] = df['views'] / df['channel_avg']

# Calculate age-adjusted performance
now = pd.Timestamp.now(tz=None)
df['published_at'] = pd.to_datetime(df['published_at']).dt.tz_localize(None)
df['age_days'] = (now - df['published_at']).dt.days.clip(lower=1)
df['views_per_day'] = df['views'] / df['age_days']
df['expected_per_day'] = df['channel_avg'] / 30  # Assume videos mature in ~30 days
df['age_adjusted_ratio'] = df['views_per_day'] / df['expected_per_day'].replace(0, 1)

# Binary target: Top 30% performers
threshold = df['age_adjusted_ratio'].quantile(0.70)
df['is_hit'] = (df['age_adjusted_ratio'] >= threshold).astype(int)

print(f"📈 Target: Top 30% by age-adjusted ratio (threshold: {threshold:.2f}x)")
print(f"   Positive samples: {df['is_hit'].sum():,} ({df['is_hit'].mean()*100:.1f}%)")

# Prepare features
feature_cols = [
    # Title features
    'title_len', 'title_words', 'has_number', 'has_question', 'has_exclamation', 'emotional',
    # Thumbnail features
    'brightness', 'saturation', 'has_face', 'face_count', 'has_text', 'text_words',
    # Content features
    'hook_face_sec', 'hook_cuts', 'hook_motion', 'wpm', 'audio_energy', 'audio_variance',
    'has_music', 'face_time_ratio', 'total_scenes', 'cta_count', 'question_count',
    # Channel context
    'subs', 'channel_avg', 'age_days'
]

# Fill NaN values
for col in feature_cols:
    if col in df.columns:
        df[col] = df[col].fillna(0)

# Convert booleans
for col in ['has_number', 'has_question', 'has_exclamation', 'has_face', 'has_text', 'has_music']:
    if col in df.columns:
        df[col] = df[col].astype(int)

# Log transform skewed features
df['log_subs'] = np.log1p(df['subs'])
df['log_channel_avg'] = np.log1p(df['channel_avg'])

# Update feature cols with log versions
feature_cols = [c for c in feature_cols if c not in ['subs', 'channel_avg']]
feature_cols.extend(['log_subs', 'log_channel_avg'])

# Generate title embeddings
print("\n🔤 Generating title embeddings...")
model = SentenceTransformer('all-MiniLM-L6-v2')
embeddings = model.encode(df['title'].tolist(), show_progress_bar=True)
embedding_df = pd.DataFrame(embeddings, columns=[f'emb_{i}' for i in range(embeddings.shape[1])])
df = pd.concat([df.reset_index(drop=True), embedding_df], axis=1)

# Add embedding columns to features
feature_cols.extend([f'emb_{i}' for i in range(embeddings.shape[1])])

# Prepare X and y
X = df[feature_cols].values
y = df['is_hit'].values

print(f"\n📐 Feature matrix: {X.shape}")

# Split data
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

print(f"   Train: {len(X_train):,} | Test: {len(X_test):,}")

# Train model
print("\n🚂 Training LightGBM...")
model = LGBMClassifier(
    n_estimators=300,
    learning_rate=0.05,
    max_depth=8,
    num_leaves=31,
    class_weight='balanced',
    random_state=42,
    verbose=-1
)
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
y_prob = model.predict_proba(X_test)[:, 1]

print("\n" + "=" * 60)
print("📊 MODEL WITH CONTENT FEATURES")
print("=" * 60)
print(f"Accuracy:          {accuracy_score(y_test, y_pred):.1%}")
print(f"Balanced Accuracy: {balanced_accuracy_score(y_test, y_pred):.1%}")
print(f"F1 Score:          {f1_score(y_test, y_pred):.3f}")
print(f"AUC-ROC:           {roc_auc_score(y_test, y_prob):.3f}")

# Feature importance
print("\n📊 Top 15 Feature Importance:")
importance = pd.DataFrame({
    'feature': feature_cols,
    'importance': model.feature_importances_
}).sort_values('importance', ascending=False)

for _, row in importance.head(15).iterrows():
    bar = '█' * int(row['importance'] * 100)
    print(f"  {row['feature']:20} {bar}")

# Separate content vs pre-upload importance
content_features = ['hook_face_sec', 'hook_cuts', 'hook_motion', 'wpm', 'audio_energy', 
                   'audio_variance', 'has_music', 'face_time_ratio', 'total_scenes', 
                   'cta_count', 'question_count']

content_importance = importance[importance['feature'].isin(content_features)]['importance'].sum()
total_importance = importance['importance'].sum()

print(f"\n📈 Content features contribute: {content_importance/total_importance*100:.1f}% of model importance")

# Save model
os.makedirs('data/models', exist_ok=True)
model_data = {
    'model': model,
    'feature_cols': feature_cols,
    'threshold': threshold,
    'trained_at': datetime.now(timezone.utc).isoformat(),
    'metrics': {
        'accuracy': accuracy_score(y_test, y_pred),
        'balanced_accuracy': balanced_accuracy_score(y_test, y_pred),
        'f1': f1_score(y_test, y_pred),
        'auc': roc_auc_score(y_test, y_prob)
    },
    'content_feature_contribution': content_importance / total_importance
}

with open('data/models/content_predictor.pkl', 'wb') as f:
    pickle.dump(model_data, f)

print(f"\n✅ Saved to data/models/content_predictor.pkl")

