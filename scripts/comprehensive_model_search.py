#!/usr/bin/env python3
"""
Comprehensive model search for ViewMagnet.

Tests multiple architectures:
1. LightGBM (with tuning)
2. XGBoost (with tuning)
3. CatBoost
4. Neural Network (MLP)
5. Random Forest
6. Ensemble of top models

ALL include title embeddings for fair comparison.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pickle
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

import optuna
from optuna.samplers import TPESampler
optuna.logging.set_verbosity(optuna.logging.WARNING)

from sqlalchemy import func
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import (
    balanced_accuracy_score, accuracy_score, f1_score, 
    precision_score, recall_score, roc_auc_score, make_scorer
)
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPClassifier
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from lightgbm import LGBMClassifier
from xgboost import XGBClassifier
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


def generate_embeddings(titles: list) -> np.ndarray:
    """Generate title embeddings in batches."""
    print("🧠 Generating title embeddings...")
    
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    batch_size = 1000
    embeddings = []
    
    for i in range(0, len(titles), batch_size):
        batch = titles[i:i+batch_size]
        batch_emb = model.encode(batch, show_progress_bar=False)
        embeddings.append(batch_emb)
        if (i + batch_size) % 10000 == 0:
            print(f"   Processed {min(i+batch_size, len(titles)):,}/{len(titles):,} titles")
    
    return np.vstack(embeddings)


def prepare_data(df):
    """Prepare features and target."""
    print("📋 Preparing features...")
    
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
    
    print(f"   Target distribution: {df['target'].mean()*100:.1f}% positive")
    
    # Features
    df['log_subs'] = np.log1p(df['subscriber_count'])
    df['log_channel_avg'] = np.log1p(df['avg_views_per_video'])
    
    # Generate embeddings
    embeddings = generate_embeddings(df['title'].tolist())
    
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
    
    # Combine base features with embeddings
    X_base = df[feature_cols].values
    X = np.hstack([X_base, embeddings])
    y = df['target'].values
    
    # Add embedding column names
    emb_cols = [f'emb_{i}' for i in range(embeddings.shape[1])]
    all_feature_cols = feature_cols + emb_cols
    
    print(f"   Total features: {X.shape[1]} ({len(feature_cols)} base + {len(emb_cols)} embeddings)")
    
    return X, y, all_feature_cols


def evaluate_model(model, X_test, y_test, name="Model"):
    """Evaluate a model and return metrics."""
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1] if hasattr(model, 'predict_proba') else y_pred
    
    metrics = {
        'name': name,
        'accuracy': accuracy_score(y_test, y_pred),
        'balanced_accuracy': balanced_accuracy_score(y_test, y_pred),
        'f1': f1_score(y_test, y_pred),
        'precision': precision_score(y_test, y_pred),
        'recall': recall_score(y_test, y_pred),
        'auc_roc': roc_auc_score(y_test, y_prob),
    }
    
    return metrics


def tune_lightgbm(X_train, y_train, n_trials=30):
    """Tune LightGBM hyperparameters."""
    print("\n🔧 Tuning LightGBM...")
    
    def objective(trial):
        params = {
            'n_estimators': trial.suggest_int('n_estimators', 100, 400),
            'max_depth': trial.suggest_int('max_depth', 4, 10),
            'learning_rate': trial.suggest_float('learning_rate', 0.02, 0.2, log=True),
            'num_leaves': trial.suggest_int('num_leaves', 20, 100),
            'min_child_samples': trial.suggest_int('min_child_samples', 20, 80),
            'subsample': trial.suggest_float('subsample', 0.7, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.7, 1.0),
            'class_weight': 'balanced',
            'random_state': 42,
            'verbosity': -1,
        }
        
        model = LGBMClassifier(**params)
        scores = cross_val_score(model, X_train, y_train, cv=3, 
                                scoring=make_scorer(balanced_accuracy_score), n_jobs=-1)
        return scores.mean()
    
    study = optuna.create_study(direction='maximize', sampler=TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
    
    best_params = study.best_params
    best_params['class_weight'] = 'balanced'
    best_params['random_state'] = 42
    best_params['verbosity'] = -1
    
    print(f"   Best CV score: {study.best_value*100:.2f}%")
    
    return LGBMClassifier(**best_params)


def tune_xgboost(X_train, y_train, n_trials=30):
    """Tune XGBoost hyperparameters."""
    print("\n🔧 Tuning XGBoost...")
    
    # Calculate scale_pos_weight for imbalanced data
    scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()
    
    def objective(trial):
        params = {
            'n_estimators': trial.suggest_int('n_estimators', 100, 400),
            'max_depth': trial.suggest_int('max_depth', 4, 10),
            'learning_rate': trial.suggest_float('learning_rate', 0.02, 0.2, log=True),
            'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
            'subsample': trial.suggest_float('subsample', 0.7, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.7, 1.0),
            'gamma': trial.suggest_float('gamma', 0, 5),
            'scale_pos_weight': scale_pos_weight,
            'random_state': 42,
            'verbosity': 0,
            'use_label_encoder': False,
            'eval_metric': 'logloss',
        }
        
        model = XGBClassifier(**params)
        scores = cross_val_score(model, X_train, y_train, cv=3, 
                                scoring=make_scorer(balanced_accuracy_score), n_jobs=-1)
        return scores.mean()
    
    study = optuna.create_study(direction='maximize', sampler=TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
    
    best_params = study.best_params
    best_params['scale_pos_weight'] = scale_pos_weight
    best_params['random_state'] = 42
    best_params['verbosity'] = 0
    best_params['use_label_encoder'] = False
    best_params['eval_metric'] = 'logloss'
    
    print(f"   Best CV score: {study.best_value*100:.2f}%")
    
    return XGBClassifier(**best_params)


def tune_neural_network(X_train, y_train, n_trials=20):
    """Tune Neural Network (MLP) hyperparameters."""
    print("\n🔧 Tuning Neural Network...")
    
    # Scale features for neural network
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_train)
    
    def objective(trial):
        n_layers = trial.suggest_int('n_layers', 1, 3)
        layers = []
        for i in range(n_layers):
            layers.append(trial.suggest_int(f'n_units_l{i}', 64, 512))
        
        params = {
            'hidden_layer_sizes': tuple(layers),
            'activation': trial.suggest_categorical('activation', ['relu', 'tanh']),
            'alpha': trial.suggest_float('alpha', 1e-5, 1e-1, log=True),
            'learning_rate_init': trial.suggest_float('learning_rate_init', 1e-4, 1e-2, log=True),
            'max_iter': 500,
            'early_stopping': True,
            'random_state': 42,
        }
        
        model = MLPClassifier(**params)
        scores = cross_val_score(model, X_scaled, y_train, cv=3, 
                                scoring=make_scorer(balanced_accuracy_score), n_jobs=-1)
        return scores.mean()
    
    study = optuna.create_study(direction='maximize', sampler=TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
    
    # Reconstruct best params
    best_trial = study.best_trial
    n_layers = best_trial.params['n_layers']
    layers = [best_trial.params[f'n_units_l{i}'] for i in range(n_layers)]
    
    best_params = {
        'hidden_layer_sizes': tuple(layers),
        'activation': best_trial.params['activation'],
        'alpha': best_trial.params['alpha'],
        'learning_rate_init': best_trial.params['learning_rate_init'],
        'max_iter': 500,
        'early_stopping': True,
        'random_state': 42,
    }
    
    print(f"   Best CV score: {study.best_value*100:.2f}%")
    print(f"   Architecture: {layers}")
    
    return MLPClassifier(**best_params), scaler


def train_random_forest(X_train, y_train):
    """Train Random Forest with balanced weights."""
    print("\n🌲 Training Random Forest...")
    
    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        min_samples_split=20,
        min_samples_leaf=10,
        class_weight='balanced',
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    
    return model


def main():
    print("=" * 70)
    print("🎯 COMPREHENSIVE MODEL SEARCH FOR ViewMagnet")
    print("=" * 70)
    print()
    
    # Load and prepare data
    df = load_data()
    X, y, feature_cols = prepare_data(df)
    
    print(f"\n📊 Dataset: {X.shape[0]:,} samples, {X.shape[1]} features")
    print(f"   Positive class: {y.mean()*100:.1f}%")
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    
    print(f"   Train: {len(X_train):,} | Test: {len(X_test):,}")
    
    results = []
    models = {}
    
    # 1. LightGBM (tuned)
    lgbm_model = tune_lightgbm(X_train, y_train, n_trials=30)
    lgbm_model.fit(X_train, y_train)
    lgbm_metrics = evaluate_model(lgbm_model, X_test, y_test, "LightGBM (tuned)")
    results.append(lgbm_metrics)
    models['lgbm'] = lgbm_model
    print(f"   ✅ LightGBM: {lgbm_metrics['balanced_accuracy']*100:.2f}%")
    
    # 2. XGBoost (tuned)
    xgb_model = tune_xgboost(X_train, y_train, n_trials=30)
    xgb_model.fit(X_train, y_train)
    xgb_metrics = evaluate_model(xgb_model, X_test, y_test, "XGBoost (tuned)")
    results.append(xgb_metrics)
    models['xgb'] = xgb_model
    print(f"   ✅ XGBoost: {xgb_metrics['balanced_accuracy']*100:.2f}%")
    
    # 3. Neural Network (tuned)
    mlp_model, scaler = tune_neural_network(X_train, y_train, n_trials=20)
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    mlp_model.fit(X_train_scaled, y_train)
    mlp_metrics = evaluate_model(mlp_model, X_test_scaled, y_test, "Neural Network (tuned)")
    results.append(mlp_metrics)
    models['mlp'] = (mlp_model, scaler)
    print(f"   ✅ Neural Network: {mlp_metrics['balanced_accuracy']*100:.2f}%")
    
    # 4. Random Forest
    rf_model = train_random_forest(X_train, y_train)
    rf_metrics = evaluate_model(rf_model, X_test, y_test, "Random Forest")
    results.append(rf_metrics)
    models['rf'] = rf_model
    print(f"   ✅ Random Forest: {rf_metrics['balanced_accuracy']*100:.2f}%")
    
    # 5. LightGBM (default - our baseline)
    lgbm_default = LGBMClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        num_leaves=31,
        class_weight='balanced',
        random_state=42,
        verbosity=-1,
    )
    lgbm_default.fit(X_train, y_train)
    lgbm_default_metrics = evaluate_model(lgbm_default, X_test, y_test, "LightGBM (default)")
    results.append(lgbm_default_metrics)
    print(f"   ✅ LightGBM (default): {lgbm_default_metrics['balanced_accuracy']*100:.2f}%")
    
    # 6. Ensemble (top 3 models)
    print("\n🤝 Building ensemble...")
    ensemble = VotingClassifier(
        estimators=[
            ('lgbm', lgbm_model),
            ('xgb', xgb_model),
            ('rf', rf_model),
        ],
        voting='soft',
    )
    ensemble.fit(X_train, y_train)
    ensemble_metrics = evaluate_model(ensemble, X_test, y_test, "Ensemble (LGBM+XGB+RF)")
    results.append(ensemble_metrics)
    models['ensemble'] = ensemble
    print(f"   ✅ Ensemble: {ensemble_metrics['balanced_accuracy']*100:.2f}%")
    
    # Results summary
    print("\n" + "=" * 70)
    print("📈 FINAL RESULTS")
    print("=" * 70)
    print()
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('balanced_accuracy', ascending=False)
    
    print("Model                    | Bal Acc | F1    | AUC   | Precision | Recall")
    print("-" * 75)
    
    for _, row in results_df.iterrows():
        print(f"{row['name']:<24} | {row['balanced_accuracy']*100:5.2f}%  | {row['f1']:.3f} | {row['auc_roc']:.3f} | {row['precision']*100:5.1f}%     | {row['recall']*100:5.1f}%")
    
    # Best model
    best = results_df.iloc[0]
    print()
    print("=" * 70)
    print(f"🏆 BEST MODEL: {best['name']}")
    print(f"   Balanced Accuracy: {best['balanced_accuracy']*100:.2f}%")
    print(f"   F1 Score: {best['f1']:.3f}")
    print(f"   AUC-ROC: {best['auc_roc']:.3f}")
    print("=" * 70)
    
    # Compare to previous baseline
    baseline = 0.745
    improvement = (best['balanced_accuracy'] - baseline) * 100
    if improvement > 0:
        print(f"\n🎉 Improvement over previous baseline (74.5%): +{improvement:.2f}%")
    elif improvement < 0:
        print(f"\n📊 Compared to previous baseline (74.5%): {improvement:.2f}%")
    else:
        print(f"\n📊 Same as previous baseline (74.5%)")
    
    # Save best model
    best_name = best['name'].lower().replace(' ', '_').replace('(', '').replace(')', '')
    model_path = Path(f"data/models/best_{best_name}.pkl")
    model_path.parent.mkdir(exist_ok=True)
    
    if 'lgbm' in best_name and 'default' not in best_name:
        save_model = lgbm_model
    elif 'xgb' in best_name:
        save_model = xgb_model
    elif 'neural' in best_name:
        save_model = (mlp_model, scaler)
    elif 'random' in best_name:
        save_model = rf_model
    elif 'ensemble' in best_name:
        save_model = ensemble
    else:
        save_model = lgbm_default
    
    with open(model_path, 'wb') as f:
        pickle.dump({
            'model': save_model,
            'feature_cols': feature_cols,
            'metrics': best.to_dict(),
            'all_results': results,
        }, f)
    
    print(f"\n💾 Saved best model to {model_path}")
    
    # Also save to clean_predictor.pkl if better
    if best['balanced_accuracy'] > baseline:
        clean_path = Path("data/models/clean_predictor.pkl")
        with open(clean_path, 'wb') as f:
            pickle.dump({
                'model': save_model,
                'feature_cols': feature_cols,
                'metrics': best.to_dict(),
            }, f)
        print(f"   Also saved to {clean_path}")
    
    print("\n✅ Comprehensive model search complete!")


if __name__ == "__main__":
    main()




