"""
Velocity Model v2 - Improved accuracy with more features and better models.
"""
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.preprocessing import StandardScaler
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
import joblib
from pathlib import Path

from src.database.connection import get_session
from src.database.models import VideoSnapshot, Video, VideoFeatures, Channel

def load_data():
    """Load velocity + video features."""
    print("📊 Loading data...")
    
    with get_session() as session:
        # Velocity snapshots
        snapshots = session.query(
            VideoSnapshot.video_id,
            VideoSnapshot.checkpoint,
            VideoSnapshot.hours_since_publish,
            VideoSnapshot.view_count,
            VideoSnapshot.like_count,
            VideoSnapshot.comment_count,
            VideoSnapshot.views_per_hour,
        ).all()
        
        # Video metadata
        videos = session.query(
            Video.video_id,
            Video.title,
            Video.channel_id,
            Video.published_at,
            Video.duration_seconds,
        ).all()
        
        # Video features (thumbnail, etc)
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
        
        # Channel stats
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
    
    return snap_df, video_df, feat_df, channel_df

def create_features(snap_df, video_df, feat_df, channel_df):
    """Create comprehensive feature matrix."""
    print("🔧 Creating features...")
    
    # Pivot snapshots
    pivot = snap_df.pivot_table(
        index='video_id',
        columns='checkpoint',
        values=['views', 'likes', 'comments', 'vph'],
        aggfunc='first'
    )
    pivot.columns = [f"{col[0]}_{col[1]}" for col in pivot.columns]
    pivot = pivot.reset_index()
    
    # Require early checkpoints + target
    required = ['views_1h', 'views_6h', 'views_24h', 'views_7d']
    mask = pivot[required].notna().all(axis=1)
    pivot = pivot[mask].copy()
    
    # Velocity features
    pivot['growth_1h_6h'] = pivot['views_6h'] / pivot['views_1h'].clip(lower=1)
    pivot['growth_6h_24h'] = pivot['views_24h'] / pivot['views_6h'].clip(lower=1)
    pivot['growth_1h_24h'] = pivot['views_24h'] / pivot['views_1h'].clip(lower=1)
    
    # Velocity decay rates
    pivot['vph_decay_1h_6h'] = pivot['vph_6h'] / pivot['vph_1h'].clip(lower=0.1)
    pivot['vph_decay_6h_24h'] = pivot['vph_24h'] / pivot['vph_6h'].clip(lower=0.1)
    
    # Engagement ratios early
    pivot['like_rate_1h'] = pivot['likes_1h'] / pivot['views_1h'].clip(lower=1)
    pivot['like_rate_6h'] = pivot['likes_6h'] / pivot['views_6h'].clip(lower=1)
    pivot['like_rate_24h'] = pivot['likes_24h'] / pivot['views_24h'].clip(lower=1)
    
    pivot['comment_rate_24h'] = pivot['comments_24h'] / pivot['views_24h'].clip(lower=1)
    
    # Log transforms (views are highly skewed)
    for col in ['views_1h', 'views_6h', 'views_24h', 'vph_1h', 'vph_6h', 'vph_24h', 'likes_24h']:
        if col in pivot.columns:
            pivot[f'log_{col}'] = np.log1p(pivot[col])
    
    # Add 3d data if available
    if 'views_3d' in pivot.columns:
        pivot['growth_24h_3d'] = pivot['views_3d'] / pivot['views_24h'].clip(lower=1)
        pivot['log_views_3d'] = np.log1p(pivot['views_3d'])
    
    # Merge video metadata
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
    
    # Merge thumbnail/title features
    pivot = pivot.merge(feat_df, on='video_id', how='left')
    
    # Merge channel data
    pivot = pivot.merge(channel_df, on='channel_id', how='left')
    
    # Channel size features
    if 'subscribers' in pivot.columns:
        pivot['log_subscribers'] = np.log1p(pivot['subscribers'].fillna(0))
        pivot['views_per_sub_24h'] = pivot['views_24h'] / pivot['subscribers'].clip(lower=1)
    
    print(f"   Final dataset: {len(pivot):,} videos")
    return pivot

def train_models(df):
    """Train and compare multiple models."""
    print("🚀 Training models...")
    
    # Feature columns
    velocity_cols = [
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
    
    # Add 3d if available
    if 'views_3d' in df.columns:
        velocity_cols += ['views_3d', 'growth_24h_3d', 'log_views_3d']
    
    video_cols = [
        'duration_mins', 'is_short', 'is_long',
        'hour_of_day', 'day_of_week', 'is_weekend',
    ]
    
    thumbnail_cols = [
        'brightness', 'saturation', 'contrast',
        'has_face', 'has_text', 'visual_complexity',
    ]
    
    title_cols = [
        'title_length', 'has_number', 'has_question',
        'word_count', 'caps_ratio',
    ]
    
    channel_cols = [
        'log_subscribers', 'channel_videos', 'views_per_sub_24h',
    ]
    
    all_features = velocity_cols + video_cols + thumbnail_cols + title_cols + channel_cols
    feature_cols = [c for c in all_features if c in df.columns]
    
    print(f"   Using {len(feature_cols)} features")
    
    X = df[feature_cols].fillna(0)
    # Convert boolean columns to int
    for col in X.columns:
        if X[col].dtype == 'object' or X[col].dtype == 'bool':
            X[col] = X[col].astype(float)
    y = np.log1p(df['views_7d'])  # Log transform target
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    results = {}
    
    # Model 1: LightGBM
    print("\n   Training LightGBM...")
    lgbm = LGBMRegressor(
        n_estimators=1000,
        learning_rate=0.03,
        max_depth=10,
        num_leaves=63,
        min_child_samples=10,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1
    )
    lgbm.fit(X_train, y_train)
    pred_lgbm = lgbm.predict(X_test)
    r2_lgbm = r2_score(y_test, pred_lgbm)
    mape_lgbm = calc_mape(np.expm1(y_test), np.expm1(pred_lgbm))
    results['LightGBM'] = {'model': lgbm, 'r2': r2_lgbm, 'mape': mape_lgbm}
    print(f"      R²: {r2_lgbm:.3f} | MAPE: {mape_lgbm:.1f}%")
    
    # Model 2: XGBoost
    print("   Training XGBoost...")
    xgb = XGBRegressor(
        n_estimators=1000,
        learning_rate=0.03,
        max_depth=8,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=0
    )
    xgb.fit(X_train, y_train)
    pred_xgb = xgb.predict(X_test)
    r2_xgb = r2_score(y_test, pred_xgb)
    mape_xgb = calc_mape(np.expm1(y_test), np.expm1(pred_xgb))
    results['XGBoost'] = {'model': xgb, 'r2': r2_xgb, 'mape': mape_xgb}
    print(f"      R²: {r2_xgb:.3f} | MAPE: {mape_xgb:.1f}%")
    
    # Model 3: Ensemble (average)
    print("   Creating Ensemble...")
    pred_ensemble = (pred_lgbm + pred_xgb) / 2
    r2_ensemble = r2_score(y_test, pred_ensemble)
    mape_ensemble = calc_mape(np.expm1(y_test), np.expm1(pred_ensemble))
    results['Ensemble'] = {'r2': r2_ensemble, 'mape': mape_ensemble}
    print(f"      R²: {r2_ensemble:.3f} | MAPE: {mape_ensemble:.1f}%")
    
    # Find best
    best_name = max(results.keys(), key=lambda k: results[k]['r2'])
    best = results[best_name]
    
    print(f"\n🏆 BEST MODEL: {best_name}")
    print(f"   R²: {best['r2']:.3f}")
    print(f"   MAPE: {best['mape']:.1f}%")
    
    # Feature importance (from best tree model)
    if best_name == 'XGBoost':
        importance = pd.DataFrame({
            'feature': feature_cols,
            'importance': xgb.feature_importances_
        }).sort_values('importance', ascending=False)
    else:
        importance = pd.DataFrame({
            'feature': feature_cols,
            'importance': lgbm.feature_importances_
        }).sort_values('importance', ascending=False)
    
    print(f"\n🔑 TOP FEATURES:")
    for _, row in importance.head(10).iterrows():
        print(f"   {row['feature']}: {row['importance']:.0f}")
    
    return results, feature_cols

def calc_mape(y_true, y_pred):
    """Calculate MAPE avoiding divide by zero."""
    mask = y_true > 0
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100

def main():
    print("=" * 60)
    print("🚀 VELOCITY MODEL v2 - IMPROVED ACCURACY")
    print("=" * 60)
    
    # Load all data
    snap_df, video_df, feat_df, channel_df = load_data()
    
    # Create features
    df = create_features(snap_df, video_df, feat_df, channel_df)
    
    if len(df) < 100:
        print("❌ Not enough data")
        return
    
    # Train models
    results, feature_cols = train_models(df)
    
    # Compare to v1
    print("\n📊 IMPROVEMENT vs v1:")
    print("   v1: R² = 0.761, MAPE = 27.4%")
    best = max(results.values(), key=lambda x: x['r2'])
    improvement = (best['r2'] - 0.761) / 0.761 * 100
    mape_improvement = (27.4 - best['mape']) / 27.4 * 100
    print(f"   v2: R² = {best['r2']:.3f}, MAPE = {best['mape']:.1f}%")
    print(f"   R² improvement: {improvement:+.1f}%")
    print(f"   MAPE improvement: {mape_improvement:+.1f}%")
    
    # Save best model
    model_dir = Path("models")
    model_dir.mkdir(exist_ok=True)
    
    best_model = results['XGBoost']['model'] if 'XGBoost' in results else results['LightGBM']['model']
    joblib.dump({
        'model': best_model,
        'feature_cols': feature_cols,
        'metrics': {'r2': best['r2'], 'mape': best['mape']}
    }, model_dir / "velocity_model_v2.joblib")
    
    print(f"\n✅ Model saved to models/velocity_model_v2.joblib")

if __name__ == "__main__":
    main()

