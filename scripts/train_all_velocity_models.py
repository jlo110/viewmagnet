"""
Train ALL velocity model combinations.

This creates models for every checkpoint → future checkpoint prediction:
- 24h → 3d, 7d, 14d, 30d
- 3d → 7d, 14d, 30d
- 7d → 14d, 30d
- 14d → 30d

Usage: Given a video at ANY age, predict views at ANY future milestone.
"""
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score
from xgboost import XGBRegressor
import joblib
from pathlib import Path
from datetime import datetime
from scipy.stats import spearmanr

from src.database.connection import get_session
from src.database.models import VideoSnapshot, Video, Channel


def load_all_data():
    """Load all velocity data."""
    print("📊 Loading data...")
    
    with get_session() as session:
        snapshots = session.query(
            VideoSnapshot.video_id,
            VideoSnapshot.checkpoint,
            VideoSnapshot.view_count,
            VideoSnapshot.like_count,
            VideoSnapshot.comment_count,
            VideoSnapshot.views_per_hour,
        ).all()
        
        videos = session.query(
            Video.video_id,
            Video.channel_id,
            Video.duration_seconds,
        ).all()
        
        channels = session.query(
            Channel.id,
            Channel.subscriber_count,
        ).all()
    
    snap_df = pd.DataFrame(snapshots, columns=[
        'video_id', 'checkpoint', 'views', 'likes', 'comments', 'vph'
    ])
    video_df = pd.DataFrame(videos, columns=[
        'video_id', 'channel_id', 'duration_seconds'
    ])
    channel_df = pd.DataFrame(channels, columns=['channel_id', 'subscribers'])
    channel_df['channel_id'] = channel_df['channel_id'].astype(str)
    
    # Pivot snapshots
    pivot = snap_df.pivot_table(
        index='video_id',
        columns='checkpoint',
        values=['views', 'likes', 'comments', 'vph'],
        aggfunc='first'
    )
    pivot.columns = [f'{c[0]}_{c[1]}' for c in pivot.columns]
    pivot = pivot.reset_index()
    
    # Merge metadata
    pivot = pivot.merge(video_df, on='video_id', how='left')
    pivot = pivot.merge(channel_df, on='channel_id', how='left')
    
    print(f"   Total videos with snapshots: {len(pivot):,}")
    
    return pivot


def get_features_for_stage(df, from_checkpoint):
    """
    Get feature columns available at a given checkpoint.
    
    from_checkpoint: '1h', '6h', '24h', '3d', '7d', '14d'
    """
    checkpoint_order = ['1h', '6h', '24h', '3d', '7d', '14d', '30d']
    from_idx = checkpoint_order.index(from_checkpoint)
    available_checkpoints = checkpoint_order[:from_idx + 1]
    
    features = []
    
    # Raw metrics at each available checkpoint
    for cp in available_checkpoints:
        features.extend([
            f'views_{cp}', f'vph_{cp}', f'likes_{cp}', f'comments_{cp}'
        ])
    
    # Growth ratios between checkpoints
    prev = None
    for cp in available_checkpoints:
        if prev:
            features.append(f'growth_{prev}_{cp}')
            features.append(f'vph_decay_{prev}_{cp}')
        prev = cp
    
    # Overall growth
    if '1h' in available_checkpoints and from_checkpoint != '1h':
        features.append(f'growth_1h_{from_checkpoint}')
    
    # Engagement rates
    for cp in available_checkpoints:
        features.extend([f'like_rate_{cp}', f'comment_rate_{cp}'])
    
    # Log transforms
    for cp in available_checkpoints:
        features.extend([f'log_views_{cp}', f'log_vph_{cp}'])
    
    # Channel context
    features.extend([
        'log_subscribers', f'views_per_sub_{from_checkpoint}', 'duration_seconds'
    ])
    
    return features


def build_features(df):
    """Build all possible features."""
    df = df.copy()
    
    checkpoints = ['1h', '6h', '24h', '3d', '7d', '14d', '30d']
    
    # Growth ratios between consecutive checkpoints
    for i, cp in enumerate(checkpoints[1:], 1):
        prev = checkpoints[i-1]
        views_col = f'views_{cp}'
        prev_views = f'views_{prev}'
        vph_col = f'vph_{cp}'
        prev_vph = f'vph_{prev}'
        
        if views_col in df.columns and prev_views in df.columns:
            df[f'growth_{prev}_{cp}'] = df[views_col] / df[prev_views].clip(lower=1)
        
        if vph_col in df.columns and prev_vph in df.columns:
            df[f'vph_decay_{prev}_{cp}'] = df[vph_col] / df[prev_vph].clip(lower=0.01)
    
    # Overall growth from 1h
    for cp in checkpoints[1:]:
        views_col = f'views_{cp}'
        if views_col in df.columns and 'views_1h' in df.columns:
            df[f'growth_1h_{cp}'] = df[views_col] / df['views_1h'].clip(lower=1)
    
    # Engagement rates
    for cp in checkpoints:
        views_col = f'views_{cp}'
        likes_col = f'likes_{cp}'
        comments_col = f'comments_{cp}'
        
        if views_col in df.columns:
            if likes_col in df.columns:
                df[f'like_rate_{cp}'] = df[likes_col] / df[views_col].clip(lower=1)
            if comments_col in df.columns:
                df[f'comment_rate_{cp}'] = df[comments_col] / df[views_col].clip(lower=1)
    
    # Log transforms
    for cp in checkpoints:
        for metric in ['views', 'vph']:
            col = f'{metric}_{cp}'
            if col in df.columns:
                df[f'log_{col}'] = np.log1p(df[col])
    
    # Channel features
    df['log_subscribers'] = np.log1p(df['subscribers'].fillna(0))
    
    for cp in checkpoints:
        views_col = f'views_{cp}'
        if views_col in df.columns:
            df[f'views_per_sub_{cp}'] = df[views_col] / df['subscribers'].clip(lower=1)
    
    return df


def train_model(df, feature_cols, target_col, from_cp, to_cp):
    """Train a single prediction model."""
    
    # Filter to rows with required data
    required = feature_cols + [target_col]
    required = [c for c in required if c in df.columns]
    
    subset = df.dropna(subset=[target_col])
    
    X = subset[[c for c in feature_cols if c in subset.columns]].fillna(0)
    X = X.replace([np.inf, -np.inf], 0)
    
    # Convert boolean/object columns
    for col in X.columns:
        if X[col].dtype == 'object' or X[col].dtype == 'bool':
            X[col] = X[col].astype(float)
    
    y = np.log1p(subset[target_col])

    if len(X) < 100:
        return None

    # Channel-grouped split: a channel must never appear in both train and
    # test. A plain random split leaks per-channel baselines (the model sees
    # other videos from the same channel) and massively inflates the score —
    # real traffic includes brand-new channels. Falls back to a random split
    # only if channel_id is unavailable. See scripts/evaluate_models.py for the
    # honest grouped-CV + lift-over-baseline report.
    if "channel_id" in subset.columns and subset["channel_id"].notna().any():
        from sklearn.model_selection import GroupShuffleSplit

        groups = subset["channel_id"].astype(str).to_numpy()
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
        train_idx, test_idx = next(splitter.split(X, y, groups))
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

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
    
    # MAPE
    y_true = np.expm1(y_test)
    y_pred = np.expm1(pred)
    mask = y_true > 0
    mape = np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100
    
    # Correlation
    from_col = f'views_{from_cp}'
    to_col = f'views_{to_cp}'
    if from_col in subset.columns and to_col in subset.columns:
        corr, _ = spearmanr(subset[from_col].dropna(), 
                           subset.loc[subset[from_col].notna(), to_col])
    else:
        corr = None
    
    # Feature importance
    used_features = [c for c in feature_cols if c in X.columns]
    importance = pd.DataFrame({
        'feature': used_features,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    
    return {
        'model': model,
        'feature_cols': used_features,
        'r2': r2,
        'mape': mape,
        'accuracy': 100 - mape,
        'correlation': corr,
        'train_size': len(X_train),
        'test_size': len(X_test),
        'top_features': importance.head(5)['feature'].tolist(),
    }


def main():
    print("=" * 70)
    print("🚀 TRAINING ALL VELOCITY MODEL COMBINATIONS")
    print("=" * 70)
    
    # Load and prepare data
    df = load_all_data()
    df = build_features(df)
    
    # Define all checkpoint combinations
    checkpoints = ['24h', '3d', '7d', '14d', '30d']
    
    combinations = []
    for i, from_cp in enumerate(checkpoints[:-1]):
        for to_cp in checkpoints[i+1:]:
            combinations.append((from_cp, to_cp))
    
    print(f"\n📊 Training {len(combinations)} model combinations...")
    print("-" * 70)
    
    results = {}
    
    for from_cp, to_cp in combinations:
        target_col = f'views_{to_cp}'
        
        # Get features available at from_cp
        feature_cols = get_features_for_stage(df, from_cp)
        feature_cols = [c for c in feature_cols if c in df.columns]
        
        # Filter to videos that have both checkpoints
        from_col = f'views_{from_cp}'
        mask = df[from_col].notna() & df[target_col].notna()
        subset = df[mask].copy()
        
        if len(subset) < 100:
            print(f"   {from_cp} → {to_cp}: ❌ Not enough data ({len(subset)} videos)")
            continue
        
        result = train_model(subset, feature_cols, target_col, from_cp, to_cp)
        
        if result:
            key = f'{from_cp}_to_{to_cp}'
            results[key] = result
            print(f"   {from_cp} → {to_cp}: ✅ {result['accuracy']:.1f}% accuracy "
                  f"(R²={result['r2']:.3f}, n={result['train_size']:,})")
        else:
            print(f"   {from_cp} → {to_cp}: ❌ Training failed")
    
    # Summary table
    print("\n" + "=" * 70)
    print("📊 MODEL ACCURACY MATRIX")
    print("=" * 70)
    
    # Create matrix
    _corner = "From \\ To"  # backslash kept out of the f-string expr (py<3.12)
    print(f"\n{_corner:<10}", end="")
    for to_cp in ['3d', '7d', '14d', '30d']:
        print(f"{to_cp:>10}", end="")
    print()
    print("-" * 50)
    
    for from_cp in ['24h', '3d', '7d', '14d']:
        print(f"{from_cp:<10}", end="")
        for to_cp in ['3d', '7d', '14d', '30d']:
            key = f'{from_cp}_to_{to_cp}'
            if key in results:
                acc = results[key]['accuracy']
                print(f"{acc:>9.1f}%", end="")
            else:
                print(f"{'--':>10}", end="")
        print()
    
    # Save all models
    print("\n" + "=" * 70)
    print("💾 SAVING MODELS")
    print("=" * 70)
    
    model_dir = Path("models")
    model_dir.mkdir(exist_ok=True)
    
    for key, result in results.items():
        filename = f"velocity_{key}.joblib"
        from_cp, to_cp = key.split('_to_')
        
        joblib.dump({
            'model': result['model'],
            'feature_cols': result['feature_cols'],
            'metrics': {
                'r2': result['r2'],
                'mape': result['mape'],
                'accuracy': result['accuracy'],
                'correlation': result['correlation'],
            },
            'from_checkpoint': from_cp,
            'to_checkpoint': to_cp,
            'training_samples': result['train_size'],
            'trained_at': datetime.now().isoformat(),
        }, model_dir / filename)
        print(f"   ✅ {filename}")
    
    # Create model index
    index = {
        'models': {},
        'created_at': datetime.now().isoformat(),
    }
    
    for key, result in results.items():
        from_cp, to_cp = key.split('_to_')
        index['models'][key] = {
            'file': f"velocity_{key}.joblib",
            'from': from_cp,
            'to': to_cp,
            'accuracy': result['accuracy'],
            'r2': result['r2'],
            'samples': result['train_size'],
        }
    
    joblib.dump(index, model_dir / "velocity_models_index.joblib")
    print("   ✅ velocity_models_index.joblib (model registry)")
    
    # Final summary
    print("\n" + "=" * 70)
    print("🎉 TRAINING COMPLETE!")
    print("=" * 70)
    print(f"\n   Models trained: {len(results)}")
    print(f"   Best accuracy: {max(r['accuracy'] for r in results.values()):.1f}%")
    print(f"   Worst accuracy: {min(r['accuracy'] for r in results.values()):.1f}%")
    
    print("\n   Usage: For a video at Day X, predict views at Day Y:")
    print("   - Load velocity_{X}_to_{Y}.joblib")
    print("   - Pass features available at Day X")
    print("   - Get predicted views at Day Y")


if __name__ == "__main__":
    main()





