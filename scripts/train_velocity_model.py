"""
Train velocity prediction model.
Predicts 7-day views from early performance (1h, 6h, 24h).
"""
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
from lightgbm import LGBMRegressor
import joblib
from pathlib import Path

from src.database.connection import get_session
from src.database.models import VideoSnapshot, Video

def load_velocity_data():
    """Load velocity snapshots and pivot to features."""
    print("📊 Loading velocity data...")
    
    with get_session() as session:
        # Get all snapshots
        # Join Video to carry channel_id for channel-grouped train/test splits.
        snapshots = session.query(
            VideoSnapshot.video_id,
            Video.channel_id,
            VideoSnapshot.checkpoint,
            VideoSnapshot.hours_since_publish,
            VideoSnapshot.view_count,
            VideoSnapshot.like_count,
            VideoSnapshot.comment_count,
            VideoSnapshot.views_per_hour,
            VideoSnapshot.engagement_rate
        ).join(Video, Video.video_id == VideoSnapshot.video_id).all()

    df = pd.DataFrame(snapshots, columns=[
        'video_id', 'channel_id', 'checkpoint', 'hours', 'views', 'likes', 'comments', 'vph', 'engagement'
    ])
    
    print(f"   Loaded {len(df):,} snapshots for {df['video_id'].nunique():,} videos")
    return df

def create_features(df):
    """Pivot snapshots to create feature matrix."""
    print("🔧 Creating features...")
    
    # Pivot to get views at each checkpoint
    pivot = df.pivot_table(
        index='video_id',
        columns='checkpoint',
        values=['views', 'likes', 'vph', 'engagement'],
        aggfunc='first'
    )
    
    # Flatten column names
    pivot.columns = [f"{col[0]}_{col[1]}" for col in pivot.columns]
    pivot = pivot.reset_index()

    # Carry channel_id (one per video) so train_model can group by channel.
    channel_map = df.groupby('video_id')['channel_id'].first().reset_index()
    pivot = pivot.merge(channel_map, on='video_id', how='left')

    # Only keep videos with 1h, 6h, 24h AND 7d data
    required = ['views_1h', 'views_6h', 'views_24h', 'views_7d']
    mask = pivot[required].notna().all(axis=1)
    pivot = pivot[mask].copy()
    
    print(f"   Videos with complete data: {len(pivot):,}")
    
    # Create derived features
    pivot['growth_1h_6h'] = pivot['views_6h'] / pivot['views_1h'].clip(lower=1)
    pivot['growth_6h_24h'] = pivot['views_24h'] / pivot['views_6h'].clip(lower=1)
    pivot['growth_1h_24h'] = pivot['views_24h'] / pivot['views_1h'].clip(lower=1)
    
    # Velocity decay
    pivot['vph_decay_1h_6h'] = pivot['vph_6h'] / pivot['vph_1h'].clip(lower=0.1)
    pivot['vph_decay_6h_24h'] = pivot['vph_24h'] / pivot['vph_6h'].clip(lower=0.1)
    
    # Engagement features
    pivot['likes_1h'] = pivot.get('likes_1h', 0)
    pivot['likes_6h'] = pivot.get('likes_6h', 0)
    pivot['likes_24h'] = pivot.get('likes_24h', 0)
    
    return pivot

def train_model(df):
    """Train velocity prediction model."""
    print("🚀 Training model...")
    
    # Features to use
    feature_cols = [
        'views_1h', 'views_6h', 'views_24h',
        'vph_1h', 'vph_6h', 'vph_24h',
        'growth_1h_6h', 'growth_6h_24h', 'growth_1h_24h',
        'vph_decay_1h_6h', 'vph_decay_6h_24h',
        'likes_1h', 'likes_6h', 'likes_24h',
    ]
    
    # Filter to available columns
    feature_cols = [c for c in feature_cols if c in df.columns]
    
    X = df[feature_cols].fillna(0)
    y = df['views_7d']
    
    # Log transform target (views are highly skewed)
    y_log = np.log1p(y)

    # Channel-grouped split so the same channel can't appear in both train and
    # test (a random split leaks per-channel baselines and inflates accuracy).
    # Falls back to a random split if channel_id is unavailable.
    if 'channel_id' in df.columns and df['channel_id'].notna().any():
        from sklearn.model_selection import GroupShuffleSplit

        groups = df['channel_id'].astype(str).to_numpy()
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
        train_idx, test_idx = next(splitter.split(X, y_log, groups))
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y_log.iloc[train_idx], y_log.iloc[test_idx]
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_log, test_size=0.2, random_state=42
        )

    print(f"   Train: {len(X_train):,} | Test: {len(X_test):,}")
    print(f"   Features: {len(feature_cols)}")
    
    # Train
    model = LGBMRegressor(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=8,
        num_leaves=31,
        min_child_samples=20,
        random_state=42,
        verbose=-1
    )
    
    model.fit(X_train, y_train)
    
    # Predict
    y_pred_log = model.predict(X_test)
    y_pred = np.expm1(y_pred_log)
    y_true = np.expm1(y_test)
    
    # Metrics
    mae = mean_absolute_error(y_true, y_pred)
    # Calculate MAPE manually to avoid divide by zero
    mask = y_true > 0
    mape = np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100
    r2 = r2_score(y_true, y_pred)
    
    print("\n📈 RESULTS:")
    print(f"   MAE: {mae:,.0f} views")
    print(f"   MAPE: {mape:.1f}%")
    print(f"   R²: {r2:.3f}")
    
    # Feature importance
    print("\n🔑 TOP FEATURES:")
    importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    
    for _, row in importance.head(8).iterrows():
        print(f"   {row['feature']}: {row['importance']:.3f}")
    
    return model, feature_cols, {'mae': mae, 'mape': mape, 'r2': r2}

def test_predictions(model, df, feature_cols):
    """Show sample predictions."""
    print("\n🎯 SAMPLE PREDICTIONS:")
    
    X = df[feature_cols].fillna(0)
    
    # Get a few samples
    samples = df.sample(5, random_state=42)
    for _, row in samples.iterrows():
        row_X = X.loc[[row.name]]
        pred = np.expm1(model.predict(row_X)[0])
        true = row['views_7d']
        error_pct = abs(pred - true) / max(true, 1) * 100
        
        print(f"   {row['video_id']}:")
        print(f"      24h views: {row['views_24h']:,.0f}")
        print(f"      Predicted 7d: {pred:,.0f}")
        print(f"      Actual 7d: {true:,.0f}")
        print(f"      Error: {error_pct:.1f}%")
        print()

def main():
    print("=" * 60)
    print("🚀 VELOCITY PREDICTION MODEL")
    print("   Predict 7-day views from early performance")
    print("=" * 60)
    
    # Load data
    df = load_velocity_data()
    
    # Create features
    features_df = create_features(df)
    
    if len(features_df) < 100:
        print("❌ Not enough data with all checkpoints")
        return
    
    # Train
    model, feature_cols, metrics = train_model(features_df)
    
    # Sample predictions
    test_predictions(model, features_df, feature_cols)
    
    # Save model
    model_dir = Path("models")
    model_dir.mkdir(exist_ok=True)
    
    joblib.dump({
        'model': model,
        'feature_cols': feature_cols,
        'metrics': metrics
    }, model_dir / "velocity_model.joblib")
    
    print("✅ Model saved to models/velocity_model.joblib")
    print("\n📊 SUMMARY:")
    print(f"   Can predict 7-day views with {metrics['mape']:.1f}% average error")
    print(f"   R² = {metrics['r2']:.3f} (explains {metrics['r2']*100:.0f}% of variance)")

if __name__ == "__main__":
    main()

