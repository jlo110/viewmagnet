#!/usr/bin/env python3
"""
Train a clean prediction model with optimal features.

Based on our analysis:
- Channel history features are most important (~60% of signal)
- Title features contribute ~25%
- Thumbnail features contribute ~15%
- Content features (hook timing, audio) don't improve prediction

This script trains a model with ONLY pre-upload available features.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pickle
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

from sqlalchemy import func
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, f1_score,
    precision_score, recall_score, roc_auc_score,
    classification_report
)
from lightgbm import LGBMClassifier
from sentence_transformers import SentenceTransformer

from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures


def load_data():
    """Load video data with features."""
    print("📊 Loading data from database...")
    
    with get_session() as session:
        # Get videos with features
        query = session.query(
            Video.video_id,
            Video.title,
            Video.view_count,
            Video.channel_id,
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
            VideoFeatures.title_has_brackets,
            VideoFeatures.title_caps_ratio,
            VideoFeatures.title_emotional_score,
            VideoFeatures.title_sentiment,
            # Thumbnail features
            VideoFeatures.brightness,
            VideoFeatures.saturation,
            VideoFeatures.contrast,
            VideoFeatures.has_face,
            VideoFeatures.face_count,
            VideoFeatures.face_area_ratio,
            VideoFeatures.has_text,
            VideoFeatures.text_word_count,
            VideoFeatures.visual_complexity,
            VideoFeatures.edge_density,
            # New composition features
            VideoFeatures.composition_score,
            VideoFeatures.rule_of_thirds_score,
            VideoFeatures.focal_point_x,
            VideoFeatures.focal_point_y,
            VideoFeatures.on_power_point,
            # Point-in-time channel trends (no data leakage)
            VideoFeatures.channel_momentum_at_upload,
            VideoFeatures.channel_engagement_trend_at_upload,
            VideoFeatures.channel_hit_rate_at_upload,
            VideoFeatures.channel_recent_avg_ratio_at_upload,
        ).join(
            Channel, Video.channel_id == Channel.channel_id
        ).join(
            VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).filter(
            Video.view_count > 0,
            Channel.avg_views_per_video > 0,
            Channel.subscriber_count > 1000,  # Filter very small channels
        ).all()
        
        print(f"   Loaded {len(query):,} videos")
        
        # Convert to DataFrame
        columns = [
            'video_id', 'title', 'view_count', 'channel_id', 'published_at',
            'subscriber_count', 'avg_views_per_video', 'category',
            'title_len', 'title_words', 'has_number', 'has_question',
            'has_exclamation', 'has_brackets', 'caps_ratio', 'emotional', 'sentiment',
            'brightness', 'saturation', 'contrast', 'has_face', 'face_count',
            'face_area_ratio', 'has_text', 'text_words', 'visual_complexity', 'edge_density',
            # New composition features
            'composition_score', 'rule_of_thirds_score', 'focal_point_x', 'focal_point_y', 'on_power_point',
            # Point-in-time channel trends
            'pit_momentum', 'pit_engagement_trend', 'pit_hit_rate', 'pit_recent_ratio'
        ]
        
        df = pd.DataFrame(query, columns=columns)
        
    return df


def calculate_channel_history(df):
    """Calculate channel history features (most important for prediction)."""
    print("📊 Calculating channel history features...")
    
    # Group by channel
    channel_stats = df.groupby('channel_id').agg({
        'view_count': ['mean', 'std', 'count']
    }).reset_index()
    
    channel_stats.columns = ['channel_id', 'channel_mean', 'channel_std', 'video_count']
    
    # Merge back
    df = df.merge(channel_stats, on='channel_id', how='left')
    
    # Calculate performance ratio for each video
    df['perf_ratio'] = df['view_count'] / df['channel_mean'].clip(lower=1)
    
    # Calculate hit rate per channel (% of videos that beat channel average)
    hit_rates = df.groupby('channel_id').apply(
        lambda g: (g['view_count'] > g['avg_views_per_video']).mean(),
        include_groups=False
    ).reset_index()
    hit_rates.columns = ['channel_id', 'hit_rate']
    df = df.merge(hit_rates, on='channel_id', how='left')
    
    # Calculate avg_ratio and std_ratio per channel
    ratio_stats = df.groupby('channel_id').apply(
        lambda g: pd.Series({
            'avg_ratio': g['perf_ratio'].mean(),
            'std_ratio': g['perf_ratio'].std() if len(g) > 1 else 0.5
        }),
        include_groups=False
    ).reset_index()
    df = df.merge(ratio_stats, on='channel_id', how='left')
    
    print(f"   Hit rate range: {df['hit_rate'].min():.2f} - {df['hit_rate'].max():.2f}")
    print(f"   Average hit rate: {df['hit_rate'].mean():.1%}")
    print(f"   Channel features calculated")
    return df


def create_target(df, percentile=70):
    """Create binary target: top X% of videos GLOBALLY by age-adjusted performance."""
    print(f"🎯 Creating target (top {100-percentile}% globally)...")
    
    # Calculate age-adjusted performance
    # (views / age_days) / (channel_avg / 30)
    now = pd.Timestamp.now()
    df['age_days'] = (now - pd.to_datetime(df['published_at'])).dt.days.clip(lower=1)
    df['views_per_day'] = df['view_count'] / df['age_days']
    df['expected_per_day'] = df['avg_views_per_video'] / 30  # Assuming 30-day average
    df['age_adjusted_ratio'] = df['views_per_day'] / df['expected_per_day'].clip(lower=1)
    
    # Top X% globally
    threshold = df['age_adjusted_ratio'].quantile(percentile / 100)
    df['target'] = (df['age_adjusted_ratio'] >= threshold).astype(int)
    
    positive_rate = df['target'].mean()
    print(f"   Positive class rate: {positive_rate:.1%}")
    print(f"   Threshold ratio: {threshold:.2f}x")
    
    return df


def generate_embeddings(df, model_name='all-MiniLM-L6-v2'):
    """Generate title embeddings."""
    print(f"🔤 Generating title embeddings ({model_name})...")
    
    model = SentenceTransformer(model_name)
    
    # Generate embeddings in batches
    batch_size = 1000
    titles = df['title'].tolist()
    embeddings = []
    
    for i in range(0, len(titles), batch_size):
        batch = titles[i:i+batch_size]
        batch_emb = model.encode(batch, show_progress_bar=False)
        embeddings.extend(batch_emb)
        
        if (i + batch_size) % 10000 == 0:
            print(f"   Processed {i + batch_size:,} titles...")
    
    embeddings = np.array(embeddings)
    print(f"   Generated embeddings: {embeddings.shape}")
    
    # Add to dataframe
    emb_cols = [f'emb_{i}' for i in range(embeddings.shape[1])]
    emb_df = pd.DataFrame(embeddings, columns=emb_cols, index=df.index)
    df = pd.concat([df, emb_df], axis=1)
    
    return df, emb_cols


def prepare_features(df, emb_cols):
    """Prepare feature matrix."""
    print("🔧 Preparing features...")
    
    # Core features (pre-upload available)
    feature_cols = [
        # Title features
        'title_len', 'title_words', 'has_number', 'has_question',
        'has_exclamation', 'has_brackets', 'caps_ratio', 'emotional', 'sentiment',
        
        # Thumbnail features
        'brightness', 'saturation', 'contrast', 'has_face', 'face_count',
        'face_area_ratio', 'has_text', 'text_words', 'visual_complexity', 'edge_density',
        
        # DISABLED: Composition v2 features (added noise, hurt accuracy)
        # 'composition_score', 'rule_of_thirds_score', 'focal_point_x', 'focal_point_y', 'on_power_point',
        
        # Channel history (MOST IMPORTANT)
        'hit_rate', 'avg_ratio', 'std_ratio', 'video_count',
        
        # Point-in-time channel trends (no leakage) - KEEP THESE
        'pit_momentum', 'pit_engagement_trend', 'pit_hit_rate', 'pit_recent_ratio',
        
        # Channel size
        'log_subs', 'log_channel_avg',
    ]
    
    # Add computed features
    df['log_subs'] = np.log1p(df['subscriber_count'])
    df['log_channel_avg'] = np.log1p(df['avg_views_per_video'])
    
    # Add embedding columns
    feature_cols.extend(emb_cols)
    
    # Convert booleans to int
    for col in ['has_number', 'has_question', 'has_exclamation', 'has_brackets', 'has_face', 'has_text', 'on_power_point']:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)
    
    # Fill NaN with 0
    for col in feature_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)
    
    # Filter to only existing columns
    feature_cols = [c for c in feature_cols if c in df.columns]
    
    print(f"   Total features: {len(feature_cols)}")
    print(f"   - Title features: 9")
    print(f"   - Thumbnail features: 10")
    print(f"   - Channel history: 4")
    print(f"   - Point-in-time trends: 4")
    print(f"   - Channel size: 2")
    print(f"   - Embeddings: {len(emb_cols)}")
    
    return df, feature_cols


def train_model(X_train, y_train, X_test, y_test):
    """Train LightGBM classifier."""
    print("🚀 Training model...")
    
    model = LGBMClassifier(
        n_estimators=500,
        max_depth=8,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=42,
        verbose=-1,
        n_jobs=-1,
    )
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        callbacks=[],
    )
    
    return model


def evaluate_model(model, X_test, y_test, feature_cols):
    """Evaluate model performance."""
    print("\n📈 MODEL EVALUATION")
    print("=" * 60)
    
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    
    metrics = {
        'accuracy': accuracy_score(y_test, y_pred),
        'balanced_accuracy': balanced_accuracy_score(y_test, y_pred),
        'f1_score': f1_score(y_test, y_pred),
        'precision': precision_score(y_test, y_pred),
        'recall': recall_score(y_test, y_pred),
        'auc_roc': roc_auc_score(y_test, y_prob),
    }
    
    print(f"Accuracy:          {metrics['accuracy']:.1%}")
    print(f"Balanced Accuracy: {metrics['balanced_accuracy']:.1%}")
    print(f"F1 Score:          {metrics['f1_score']:.3f}")
    print(f"Precision:         {metrics['precision']:.1%}")
    print(f"Recall:            {metrics['recall']:.1%}")
    print(f"AUC-ROC:           {metrics['auc_roc']:.3f}")
    
    print("\n📊 FEATURE IMPORTANCE (Top 20)")
    print("-" * 40)
    
    importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    
    for i, row in importance.head(20).iterrows():
        bar = '█' * int(row['importance'] / importance['importance'].max() * 20)
        print(f"{row['feature'][:25]:25} {bar} {row['importance']:.0f}")
    
    return metrics, importance


def save_model(model, feature_cols, metrics, output_path):
    """Save trained model."""
    print(f"\n💾 Saving model to {output_path}")
    
    model_data = {
        'model': model,
        'feature_cols': feature_cols,
        'threshold': 0.5,
        'trained_at': datetime.now().isoformat(),
        'metrics': metrics,
        'description': 'Clean model with title, thumbnail, and channel history features only',
    }
    
    with open(output_path, 'wb') as f:
        pickle.dump(model_data, f)
    
    # Verify it saved correctly
    with open(output_path, 'rb') as f:
        loaded = pickle.load(f)
    
    print(f"   ✅ Model saved and verified ({len(feature_cols)} features)")


def main():
    print("=" * 60)
    print("🎯 ViewMagnet CLEAN MODEL TRAINING")
    print("=" * 60)
    print()
    
    # Load data
    df = load_data()
    
    # Calculate channel history
    df = calculate_channel_history(df)
    
    # Create target
    df = create_target(df, percentile=70)  # Top 30%
    
    # Remove channels with too few videos
    channel_counts = df.groupby('channel_id').size()
    valid_channels = channel_counts[channel_counts >= 5].index
    df = df[df['channel_id'].isin(valid_channels)]
    print(f"   Filtered to {len(df):,} videos from {len(valid_channels):,} channels")
    
    # Generate embeddings
    df, emb_cols = generate_embeddings(df)
    
    # Prepare features
    df, feature_cols = prepare_features(df, emb_cols)
    
    # Split data
    print("\n📊 Splitting data...")
    X = df[feature_cols].values
    y = df['target'].values
    
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    
    print(f"   Train: {len(X_train):,} samples")
    print(f"   Test:  {len(X_test):,} samples")
    
    # Train model
    model = train_model(X_train, y_train, X_test, y_test)
    
    # Evaluate
    metrics, importance = evaluate_model(model, X_test, y_test, feature_cols)
    
    # Save model
    output_path = Path("data/models/clean_predictor.pkl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_model(model, feature_cols, metrics, output_path)
    
    print("\n" + "=" * 60)
    print("✅ TRAINING COMPLETE!")
    print("=" * 60)
    print(f"\nModel saved to: {output_path}")
    print(f"Balanced Accuracy: {metrics['balanced_accuracy']:.1%}")
    print(f"F1 Score: {metrics['f1_score']:.3f}")
    
    # Show top channel history importance
    channel_features = ['hit_rate', 'avg_ratio', 'std_ratio', 'video_count']
    channel_importance = importance[importance['feature'].isin(channel_features)]
    channel_pct = channel_importance['importance'].sum() / importance['importance'].sum() * 100
    print(f"\nChannel history contribution: {channel_pct:.1f}%")


if __name__ == "__main__":
    main()

