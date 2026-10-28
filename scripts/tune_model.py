#!/usr/bin/env python3
"""
Hyperparameter tuning for ViewMagnet model using Optuna.

Tests different LightGBM configurations to maximize balanced accuracy.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pickle
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

import optuna
from optuna.samplers import TPESampler
from sqlalchemy import func
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import balanced_accuracy_score, make_scorer
from lightgbm import LGBMClassifier
from sentence_transformers import SentenceTransformer

from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures


def load_data():
    """Load video data with features."""
    print("📊 Loading data from database...")
    
    with get_session() as session:
        query = session.query(
            Video.video_id,
            Video.title,
            Video.view_count,
            Video.channel_id,
            Video.published_at,
            Channel.subscriber_count,
            Channel.avg_views_per_video,
            Channel.primary_category,
            VideoFeatures.title_char_length,
            VideoFeatures.title_word_count,
            VideoFeatures.title_has_number,
            VideoFeatures.title_has_question,
            VideoFeatures.title_has_exclamation,
            VideoFeatures.title_has_brackets,
            VideoFeatures.title_caps_ratio,
            VideoFeatures.title_emotional_score,
            VideoFeatures.title_sentiment,
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
            Channel.subscriber_count > 1000,
        ).all()
        
        print(f"   Loaded {len(query):,} videos")
        
        columns = [
            'video_id', 'title', 'view_count', 'channel_id', 'published_at',
            'subscriber_count', 'avg_views_per_video', 'category',
            'title_len', 'title_words', 'has_number', 'has_question',
            'has_exclamation', 'has_brackets', 'caps_ratio', 'emotional', 'sentiment',
            'brightness', 'saturation', 'contrast', 'has_face', 'face_count',
            'face_area_ratio', 'has_text', 'text_words', 'visual_complexity', 'edge_density',
            'pit_momentum', 'pit_engagement_trend', 'pit_hit_rate', 'pit_recent_ratio'
        ]
        
        df = pd.DataFrame(query, columns=columns)
        
    return df


def prepare_data(df):
    """Prepare features and target."""
    # Channel history
    channel_stats = df.groupby('channel_id').agg({
        'view_count': ['mean', 'std', 'count']
    }).reset_index()
    channel_stats.columns = ['channel_id', 'channel_mean', 'channel_std', 'video_count']
    df = df.merge(channel_stats, on='channel_id', how='left')
    
    df['perf_ratio'] = df['view_count'] / df['channel_mean'].clip(lower=1)
    
    hit_rates = df.groupby('channel_id').apply(
        lambda g: (g['view_count'] > g['avg_views_per_video']).mean(),
        include_groups=False
    ).reset_index()
    hit_rates.columns = ['channel_id', 'hit_rate']
    df = df.merge(hit_rates, on='channel_id', how='left')
    
    avg_ratios = df.groupby('channel_id')['perf_ratio'].mean().reset_index()
    avg_ratios.columns = ['channel_id', 'avg_ratio']
    df = df.merge(avg_ratios, on='channel_id', how='left')
    
    std_ratios = df.groupby('channel_id')['perf_ratio'].std().fillna(0).reset_index()
    std_ratios.columns = ['channel_id', 'std_ratio']
    df = df.merge(std_ratios, on='channel_id', how='left')
    
    # Target: Top 30% globally
    threshold = df['perf_ratio'].quantile(0.70)
    df['target'] = (df['perf_ratio'] >= threshold).astype(int)
    
    # Features
    df['log_subs'] = np.log1p(df['subscriber_count'])
    df['log_channel_avg'] = np.log1p(df['avg_views_per_video'])
    
    feature_cols = [
        'title_len', 'title_words', 'has_number', 'has_question',
        'has_exclamation', 'has_brackets', 'caps_ratio', 'emotional', 'sentiment',
        'brightness', 'saturation', 'contrast', 'has_face', 'face_count',
        'face_area_ratio', 'has_text', 'text_words', 'visual_complexity', 'edge_density',
        'hit_rate', 'avg_ratio', 'std_ratio', 'video_count',
        'pit_momentum', 'pit_engagement_trend', 'pit_hit_rate', 'pit_recent_ratio',
        'log_subs', 'log_channel_avg',
    ]
    
    # Booleans to int
    for col in ['has_number', 'has_question', 'has_exclamation', 'has_brackets', 'has_face', 'has_text']:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)
    
    # Fill NaN
    for col in feature_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)
    
    feature_cols = [c for c in feature_cols if c in df.columns]
    
    X = df[feature_cols].values
    y = df['target'].values
    
    return X, y, feature_cols


def objective(trial, X_train, y_train):
    """Optuna objective function."""
    params = {
        'n_estimators': trial.suggest_int('n_estimators', 100, 500),
        'max_depth': trial.suggest_int('max_depth', 3, 12),
        'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
        'num_leaves': trial.suggest_int('num_leaves', 20, 150),
        'min_child_samples': trial.suggest_int('min_child_samples', 10, 100),
        'subsample': trial.suggest_float('subsample', 0.6, 1.0),
        'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
        'reg_alpha': trial.suggest_float('reg_alpha', 1e-8, 10.0, log=True),
        'reg_lambda': trial.suggest_float('reg_lambda', 1e-8, 10.0, log=True),
        'class_weight': 'balanced',
        'random_state': 42,
        'verbosity': -1,
    }
    
    model = LGBMClassifier(**params)
    
    # Cross-validation with balanced accuracy
    scorer = make_scorer(balanced_accuracy_score)
    scores = cross_val_score(model, X_train, y_train, cv=3, scoring=scorer, n_jobs=-1)
    
    return scores.mean()


def main():
    print("=" * 60)
    print("🎯 ViewMagnet HYPERPARAMETER TUNING")
    print("=" * 60)
    print()
    
    # Load and prepare data
    df = load_data()
    X, y, feature_cols = prepare_data(df)
    
    print(f"📊 Dataset: {X.shape[0]:,} samples, {X.shape[1]} features")
    print(f"   Positive class: {y.mean()*100:.1f}%")
    print()
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    
    print("🔍 Starting hyperparameter search (50 trials)...")
    print()
    
    # Optuna study
    study = optuna.create_study(
        direction='maximize',
        sampler=TPESampler(seed=42)
    )
    
    study.optimize(
        lambda trial: objective(trial, X_train, y_train),
        n_trials=50,
        show_progress_bar=True
    )
    
    print()
    print("=" * 60)
    print("🏆 BEST PARAMETERS FOUND")
    print("=" * 60)
    print(f"Best CV Balanced Accuracy: {study.best_value:.4f} ({study.best_value*100:.2f}%)")
    print()
    print("Parameters:")
    for key, value in study.best_params.items():
        print(f"   {key}: {value}")
    
    # Train final model with best params
    print()
    print("🚀 Training final model with best parameters...")
    
    best_params = study.best_params
    best_params['class_weight'] = 'balanced'
    best_params['random_state'] = 42
    best_params['verbosity'] = -1
    
    final_model = LGBMClassifier(**best_params)
    final_model.fit(X_train, y_train)
    
    # Evaluate on test set
    y_pred = final_model.predict(X_test)
    test_accuracy = balanced_accuracy_score(y_test, y_pred)
    
    print()
    print("=" * 60)
    print("📈 FINAL MODEL EVALUATION (Test Set)")
    print("=" * 60)
    print(f"Balanced Accuracy: {test_accuracy*100:.2f}%")
    
    # Compare to baseline
    baseline = 0.745  # Our previous best
    improvement = (test_accuracy - baseline) * 100
    if improvement > 0:
        print(f"🎉 Improvement over baseline: +{improvement:.2f}%")
    else:
        print(f"📉 Compared to baseline: {improvement:.2f}%")
    
    # Save if better
    if test_accuracy > baseline:
        model_path = Path("data/models/tuned_predictor.pkl")
        model_path.parent.mkdir(exist_ok=True)
        
        with open(model_path, 'wb') as f:
            pickle.dump({
                'model': final_model,
                'feature_cols': feature_cols,
                'best_params': best_params,
                'balanced_accuracy': test_accuracy,
            }, f)
        
        print(f"💾 Saved improved model to {model_path}")
    else:
        print("ℹ️ Keeping previous model (no improvement)")
    
    print()


if __name__ == "__main__":
    main()




