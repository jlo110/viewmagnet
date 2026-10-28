"""
Velocity Model v3 - Predicting Day 30 views with 14d and 30d data.

Now that we have:
- 82,428 videos with 14d checkpoints
- 17,071 videos with 30d checkpoints

We can train models that predict TRUE final performance (Day 30), not just Day 7.

Models trained:
1. Day 7 → Day 30 (most useful for early predictions)
2. Day 14 → Day 30 (high accuracy confirmation)
3. Early (24h) → Day 30 (earliest prediction possible)
"""
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_absolute_error
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
import joblib
from pathlib import Path
from datetime import datetime

from src.database.connection import get_session
from src.database.models import VideoSnapshot, Video, VideoFeatures, Channel


def load_data():
    """Load velocity + video features."""
    print("📊 Loading data...")
    
    with get_session() as session:
        snapshots = session.query(
            VideoSnapshot.video_id,
            VideoSnapshot.checkpoint,
            VideoSnapshot.hours_since_publish,
            VideoSnapshot.view_count,
            VideoSnapshot.like_count,
            VideoSnapshot.comment_count,
            VideoSnapshot.views_per_hour,
        ).all()
        
        videos = session.query(
            Video.video_id,
            Video.title,
            Video.channel_id,
            Video.published_at,
            Video.duration_seconds,
        ).all()
        
        features = session.query(
            VideoFeatures.video_id,
            VideoFeatures.brightness,
            VideoFeatures.saturation,
            VideoFeatures.contrast,
            VideoFeatures.has_face,
            VideoFeatures.has_text,
            VideoFeatures.title_char_length,
            VideoFeatures.title_has_number,
            VideoFeatures.title_has_question,
            VideoFeatures.title_word_count,
            VideoFeatures.title_caps_ratio,
            VideoFeatures.visual_complexity,
        ).all()
        
        channels = session.query(
            Channel.id,
            Channel.subscriber_count,
            Channel.video_count,
        ).all()
    
    snap_df = pd.DataFrame(snapshots, columns=[
        'video_id', 'checkpoint', 'hours', 'views', 'likes', 'comments', 'vph'
    ])
    
    video_df = pd.DataFrame(videos, columns=[
        'video_id', 'title', 'channel_id', 'published_at', 'duration_seconds'
    ])
    
    feat_df = pd.DataFrame(features, columns=[
        'video_id', 'brightness', 'saturation', 'contrast',
        'has_face', 'has_text', 'title_length', 'has_number', 'has_question',
        'word_count', 'caps_ratio', 'visual_complexity'
    ])
    
    channel_df = pd.DataFrame(channels, columns=['channel_id', 'subscribers', 'channel_videos'])
    channel_df['channel_id'] = channel_df['channel_id'].astype(str)
    
    print(f"   Snapshots: {len(snap_df):,}")
    print(f"   Videos: {len(video_df):,}")
    print(f"   Features: {len(feat_df):,}")
    print(f"   Channels: {len(channel_df):,}")
    
    # Count checkpoints
    cp_counts = snap_df.groupby('checkpoint').size()
    print("\n   Checkpoint counts:")
    for cp in ['1h', '6h', '24h', '3d', '7d', '14d', '30d']:
        if cp in cp_counts.index:
            print(f"      {cp}: {cp_counts[cp]:,}")
    
    return snap_df, video_df, feat_df, channel_df


def create_features_30d(snap_df, video_df, feat_df, channel_df):
    """Create feature matrix for Day 30 prediction."""
    print("\n🔧 Creating features for 30d prediction...")
    
    # Pivot snapshots
    pivot = snap_df.pivot_table(
        index='video_id',
        columns='checkpoint',
        values=['views', 'likes', 'comments', 'vph'],
        aggfunc='first'
    )
    pivot.columns = [f"{col[0]}_{col[1]}" for col in pivot.columns]
    pivot = pivot.reset_index()
    
    # Require 30d target + early checkpoints
    required = ['views_1h', 'views_6h', 'views_24h', 'views_7d', 'views_30d']
    mask = pivot[required].notna().all(axis=1)
    pivot = pivot[mask].copy()
    
    print(f"   Videos with full 30d data: {len(pivot):,}")
    
    if len(pivot) < 100:
        print("   ⚠️ Not enough 30d data yet")
        return None
    
    # === VELOCITY FEATURES ===
    
    # Growth ratios (key predictors)
    pivot['growth_1h_6h'] = pivot['views_6h'] / pivot['views_1h'].clip(lower=1)
    pivot['growth_6h_24h'] = pivot['views_24h'] / pivot['views_6h'].clip(lower=1)
    pivot['growth_1h_24h'] = pivot['views_24h'] / pivot['views_1h'].clip(lower=1)
    pivot['growth_24h_7d'] = pivot['views_7d'] / pivot['views_24h'].clip(lower=1)
    
    # Add 3d growth if available
    if 'views_3d' in pivot.columns:
        pivot['growth_24h_3d'] = pivot['views_3d'] / pivot['views_24h'].clip(lower=1)
        pivot['growth_3d_7d'] = pivot['views_7d'] / pivot['views_3d'].clip(lower=1)
    
    # Add 14d growth if available
    if 'views_14d' in pivot.columns:
        pivot['growth_7d_14d'] = pivot['views_14d'] / pivot['views_7d'].clip(lower=1)
        pivot['growth_14d_30d'] = pivot['views_30d'] / pivot['views_14d'].clip(lower=1)
        pivot['log_views_14d'] = np.log1p(pivot['views_14d'])
    
    # Velocity decay (shows momentum loss)
    pivot['vph_decay_1h_6h'] = pivot['vph_6h'] / pivot['vph_1h'].clip(lower=0.1)
    pivot['vph_decay_6h_24h'] = pivot['vph_24h'] / pivot['vph_6h'].clip(lower=0.1)
    if 'vph_7d' in pivot.columns:
        pivot['vph_decay_24h_7d'] = pivot['vph_7d'] / pivot['vph_24h'].clip(lower=0.1)
    
    # Engagement rates at each checkpoint
    for cp in ['1h', '6h', '24h', '3d', '7d', '14d']:
        views_col = f'views_{cp}'
        likes_col = f'likes_{cp}'
        comments_col = f'comments_{cp}'
        
        if views_col in pivot.columns and likes_col in pivot.columns:
            pivot[f'like_rate_{cp}'] = pivot[likes_col] / pivot[views_col].clip(lower=1)
        if views_col in pivot.columns and comments_col in pivot.columns:
            pivot[f'comment_rate_{cp}'] = pivot[comments_col] / pivot[views_col].clip(lower=1)
    
    # Log transforms
    for col in ['views_1h', 'views_6h', 'views_24h', 'views_3d', 'views_7d', 
                'vph_1h', 'vph_6h', 'vph_24h', 'likes_24h', 'likes_7d']:
        if col in pivot.columns:
            pivot[f'log_{col}'] = np.log1p(pivot[col])
    
    # === MERGE METADATA ===
    pivot = pivot.merge(video_df, on='video_id', how='left')
    
    # Time features
    if 'published_at' in pivot.columns:
        pivot['hour_of_day'] = pd.to_datetime(pivot['published_at']).dt.hour
        pivot['day_of_week'] = pd.to_datetime(pivot['published_at']).dt.dayofweek
        pivot['is_weekend'] = pivot['day_of_week'].isin([5, 6]).astype(int)
    
    # Duration features
    if 'duration_seconds' in pivot.columns:
        pivot['duration_mins'] = pivot['duration_seconds'] / 60
        pivot['is_short'] = (pivot['duration_seconds'] < 60).astype(int)
        pivot['is_long'] = (pivot['duration_seconds'] > 1200).astype(int)
    
    # Thumbnail/title features
    pivot = pivot.merge(feat_df, on='video_id', how='left')
    
    # Channel data
    pivot = pivot.merge(channel_df, on='channel_id', how='left')
    
    if 'subscribers' in pivot.columns:
        pivot['log_subscribers'] = np.log1p(pivot['subscribers'].fillna(0))
        pivot['views_per_sub_24h'] = pivot['views_24h'] / pivot['subscribers'].clip(lower=1)
        pivot['views_per_sub_7d'] = pivot['views_7d'] / pivot['subscribers'].clip(lower=1)
    
    return pivot


def get_feature_cols(df, prediction_stage='7d'):
    """Get feature columns based on prediction stage."""
    
    # Base velocity features (always available)
    base_velocity = [
        'views_1h', 'views_6h', 'views_24h',
        'vph_1h', 'vph_6h', 'vph_24h',
        'likes_1h', 'likes_6h', 'likes_24h',
        'comments_24h',
        'growth_1h_6h', 'growth_6h_24h', 'growth_1h_24h',
        'vph_decay_1h_6h', 'vph_decay_6h_24h',
        'like_rate_1h', 'like_rate_6h', 'like_rate_24h',
        'comment_rate_24h',
        'log_views_1h', 'log_views_6h', 'log_views_24h',
        'log_vph_24h', 'log_likes_24h',
    ]
    
    # 3d features
    day3_features = [
        'views_3d', 'growth_24h_3d', 'log_views_3d',
        'like_rate_3d', 'comment_rate_3d',
    ]
    
    # 7d features
    day7_features = [
        'views_7d', 'growth_24h_7d', 'growth_3d_7d',
        'vph_decay_24h_7d', 'log_views_7d',
        'likes_7d', 'log_likes_7d',
        'like_rate_7d', 'comment_rate_7d',
        'views_per_sub_7d',
    ]
    
    # 14d features
    day14_features = [
        'views_14d', 'growth_7d_14d', 'log_views_14d',
        'like_rate_14d', 'comment_rate_14d',
    ]
    
    # Video metadata
    video_cols = [
        'duration_mins', 'is_short', 'is_long',
        'hour_of_day', 'day_of_week', 'is_weekend',
    ]
    
    # Thumbnail features
    thumbnail_cols = [
        'brightness', 'saturation', 'contrast',
        'has_face', 'has_text', 'visual_complexity',
    ]
    
    # Title features
    title_cols = [
        'title_length', 'has_number', 'has_question',
        'word_count', 'caps_ratio',
    ]
    
    # Channel features
    channel_cols = [
        'log_subscribers', 'channel_videos', 'views_per_sub_24h',
    ]
    
    # Build feature set based on prediction stage
    if prediction_stage == '24h':
        features = base_velocity
    elif prediction_stage == '3d':
        features = base_velocity + day3_features
    elif prediction_stage == '7d':
        features = base_velocity + day3_features + day7_features
    elif prediction_stage == '14d':
        features = base_velocity + day3_features + day7_features + day14_features
    else:
        features = base_velocity + day3_features + day7_features + day14_features
    
    features += video_cols + thumbnail_cols + title_cols + channel_cols
    
    # Only return columns that exist
    return [c for c in features if c in df.columns]


def train_model(df, feature_cols, target_col, model_name):
    """Train a single model."""
    X = df[feature_cols].fillna(0)
    
    # Convert boolean columns
    for col in X.columns:
        if X[col].dtype == 'object' or X[col].dtype == 'bool':
            X[col] = X[col].astype(float)
    
    y = np.log1p(df[target_col])
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Train XGBoost (generally best)
    model = XGBRegressor(
        n_estimators=1000,
        learning_rate=0.03,
        max_depth=8,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=0
    )
    model.fit(X_train, y_train)
    
    pred = model.predict(X_test)
    r2 = r2_score(y_test, pred)
    mape = calc_mape(np.expm1(y_test), np.expm1(pred))
    
    # Feature importance
    importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    
    return {
        'model': model,
        'feature_cols': feature_cols,
        'r2': r2,
        'mape': mape,
        'importance': importance,
        'train_size': len(X_train),
        'test_size': len(X_test),
    }


def calc_mape(y_true, y_pred):
    """Calculate MAPE avoiding divide by zero."""
    mask = y_true > 0
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100


def main():
    print("=" * 70)
    print("🚀 VELOCITY MODEL v3 - DAY 30 PREDICTION WITH 14d/30d DATA")
    print("=" * 70)
    
    # Load data
    snap_df, video_df, feat_df, channel_df = load_data()
    
    # Create features
    df = create_features_30d(snap_df, video_df, feat_df, channel_df)
    
    if df is None or len(df) < 100:
        print("\n❌ Not enough 30d data for training")
        return
    
    print(f"\n📊 Training dataset: {len(df):,} videos with complete 30d data")
    
    # === TRAIN MULTIPLE MODELS ===
    
    results = {}
    
    # Model 1: Day 7 → Day 30 (most practical)
    print("\n" + "=" * 50)
    print("📈 MODEL 1: Day 7 → Day 30 Prediction")
    print("=" * 50)
    
    feature_cols_7d = get_feature_cols(df, '7d')
    result_7d = train_model(df, feature_cols_7d, 'views_30d', '7d_to_30d')
    results['7d_to_30d'] = result_7d
    
    print(f"   Features: {len(feature_cols_7d)}")
    print(f"   R²: {result_7d['r2']:.4f}")
    print(f"   MAPE: {result_7d['mape']:.2f}%")
    print(f"   Accuracy: ~{100 - result_7d['mape']:.1f}%")
    print("\n   Top features:")
    for _, row in result_7d['importance'].head(5).iterrows():
        print(f"      {row['feature']}: {row['importance']:.0f}")
    
    # Model 2: Day 14 → Day 30 (confirmation model)
    if 'views_14d' in df.columns and df['views_14d'].notna().sum() > 100:
        print("\n" + "=" * 50)
        print("📈 MODEL 2: Day 14 → Day 30 Prediction")
        print("=" * 50)
        
        df_14d = df[df['views_14d'].notna()].copy()
        feature_cols_14d = get_feature_cols(df_14d, '14d')
        result_14d = train_model(df_14d, feature_cols_14d, 'views_30d', '14d_to_30d')
        results['14d_to_30d'] = result_14d
        
        print(f"   Training size: {len(df_14d):,} videos")
        print(f"   Features: {len(feature_cols_14d)}")
        print(f"   R²: {result_14d['r2']:.4f}")
        print(f"   MAPE: {result_14d['mape']:.2f}%")
        print(f"   Accuracy: ~{100 - result_14d['mape']:.1f}%")
        print("\n   Top features:")
        for _, row in result_14d['importance'].head(5).iterrows():
            print(f"      {row['feature']}: {row['importance']:.0f}")
    
    # Model 3: Early (24h) → Day 30 (earliest prediction)
    print("\n" + "=" * 50)
    print("📈 MODEL 3: Day 1 (24h) → Day 30 Prediction")
    print("=" * 50)
    
    feature_cols_24h = get_feature_cols(df, '24h')
    result_24h = train_model(df, feature_cols_24h, 'views_30d', '24h_to_30d')
    results['24h_to_30d'] = result_24h
    
    print(f"   Features: {len(feature_cols_24h)}")
    print(f"   R²: {result_24h['r2']:.4f}")
    print(f"   MAPE: {result_24h['mape']:.2f}%")
    print(f"   Accuracy: ~{100 - result_24h['mape']:.1f}%")
    print("\n   Top features:")
    for _, row in result_24h['importance'].head(5).iterrows():
        print(f"      {row['feature']}: {row['importance']:.0f}")
    
    # === SUMMARY ===
    print("\n" + "=" * 70)
    print("📊 MODEL COMPARISON SUMMARY")
    print("=" * 70)
    print(f"{'Model':<20} {'R²':>10} {'MAPE':>10} {'Accuracy':>12} {'Samples':>10}")
    print("-" * 70)
    
    for name, res in sorted(results.items(), key=lambda x: x[1]['r2'], reverse=True):
        acc = 100 - res['mape']
        print(f"{name:<20} {res['r2']:>10.4f} {res['mape']:>9.2f}% {acc:>11.1f}% {res['train_size']:>10,}")
    
    # === INSIGHTS ===
    print("\n" + "=" * 70)
    print("💡 KEY INSIGHTS FROM 30-DAY DATA")
    print("=" * 70)
    
    # Calculate actual 7d→30d growth in the data
    growth_7d_30d = df['views_30d'] / df['views_7d'].clip(lower=1)
    print(f"\n   Typical 7d→30d growth: {growth_7d_30d.median():.2f}x")
    print(f"   Range: {growth_7d_30d.quantile(0.1):.2f}x (P10) to {growth_7d_30d.quantile(0.9):.2f}x (P90)")
    
    if 'views_14d' in df.columns:
        growth_14d_30d = df['views_30d'] / df['views_14d'].clip(lower=1)
        print(f"\n   Typical 14d→30d growth: {growth_14d_30d.median():.2f}x")
        print(f"   Range: {growth_14d_30d.quantile(0.1):.2f}x (P10) to {growth_14d_30d.quantile(0.9):.2f}x (P90)")
    
    # How much does 7d predict 30d?
    from scipy.stats import spearmanr
    corr, _ = spearmanr(df['views_7d'], df['views_30d'])
    print(f"\n   7d→30d correlation: {corr:.3f}")
    
    if 'views_14d' in df.columns and df['views_14d'].notna().sum() > 100:
        corr_14d, _ = spearmanr(
            df[df['views_14d'].notna()]['views_14d'], 
            df[df['views_14d'].notna()]['views_30d']
        )
        print(f"   14d→30d correlation: {corr_14d:.3f}")
    
    # === SAVE MODELS ===
    print("\n" + "=" * 70)
    print("💾 SAVING MODELS")
    print("=" * 70)
    
    model_dir = Path("models")
    model_dir.mkdir(exist_ok=True)
    
    # Save primary model (7d→30d) as the new v3
    best_result = results['7d_to_30d']
    joblib.dump({
        'model': best_result['model'],
        'feature_cols': best_result['feature_cols'],
        'metrics': {
            'r2': best_result['r2'],
            'mape': best_result['mape'],
            'accuracy': 100 - best_result['mape'],
        },
        'target': 'views_30d',
        'prediction_stage': '7d',
        'training_samples': best_result['train_size'],
        'trained_at': datetime.now().isoformat(),
    }, model_dir / "velocity_model_v3.joblib")
    print(f"   ✅ Saved velocity_model_v3.joblib (7d→30d)")
    
    # Save all model variants
    for name, res in results.items():
        filename = f"velocity_{name}.joblib"
        joblib.dump({
            'model': res['model'],
            'feature_cols': res['feature_cols'],
            'metrics': {
                'r2': res['r2'],
                'mape': res['mape'],
                'accuracy': 100 - res['mape'],
            },
            'target': 'views_30d',
            'prediction_stage': name.split('_')[0],
            'training_samples': res['train_size'],
            'trained_at': datetime.now().isoformat(),
        }, model_dir / filename)
        print(f"   ✅ Saved {filename}")
    
    print("\n" + "=" * 70)
    print("🎉 TRAINING COMPLETE!")
    print("=" * 70)
    print(f"\n   Primary model: velocity_model_v3.joblib")
    print(f"   Predicts: Day 30 views from Day 7 data")
    print(f"   Accuracy: ~{100 - results['7d_to_30d']['mape']:.1f}%")


if __name__ == "__main__":
    main()





