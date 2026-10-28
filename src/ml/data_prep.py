"""
Data preparation for ML model training.

Prepares training data from the database with proper feature engineering.
"""
import numpy as np
import pandas as pd
from typing import Tuple, Optional, List
from sqlalchemy import and_
from sqlalchemy.orm import Session
import structlog

from src.database.models import Video, VideoFeatures, Channel

logger = structlog.get_logger()


class DataPreparation:
    """Prepares training data for ML models."""
    
    # Features to use for thumbnail model
    THUMBNAIL_FEATURES = [
        'face_count',
        'has_face',
        'face_area_ratio',
        'brightness',
        'saturation',
        'contrast',
        'edge_density',
        'composition_score',
        'dominant_color_r',
        'dominant_color_g', 
        'dominant_color_b',
        'face_emotion_intensity',
    ]
    
    # Additional context features
    CONTEXT_FEATURES = [
        'channel_size_tier',
        'primary_category',
        'niche_id',
        'duration_bucket',
    ]
    
    def __init__(self, session: Session):
        """Initialize data preparation."""
        self.session = session
    
    @staticmethod
    def _hex_to_r(hex_color: str) -> int:
        """Extract red component from hex color."""
        if not hex_color or len(hex_color) < 6:
            return 128
        try:
            hex_color = hex_color.lstrip('#')
            return int(hex_color[0:2], 16)
        except:
            return 128
    
    @staticmethod
    def _hex_to_g(hex_color: str) -> int:
        """Extract green component from hex color."""
        if not hex_color or len(hex_color) < 6:
            return 128
        try:
            hex_color = hex_color.lstrip('#')
            return int(hex_color[2:4], 16)
        except:
            return 128
    
    @staticmethod
    def _hex_to_b(hex_color: str) -> int:
        """Extract blue component from hex color."""
        if not hex_color or len(hex_color) < 6:
            return 128
        try:
            hex_color = hex_color.lstrip('#')
            return int(hex_color[4:6], 16)
        except:
            return 128
    
    def get_thumbnail_training_data(
        self,
        min_views: int = 100,
        limit: Optional[int] = None,
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Get training data for thumbnail performance model.
        
        Args:
            min_views: Minimum views to include (filter noise)
            limit: Maximum samples (None for all)
            
        Returns:
            Tuple of (features DataFrame, target Series)
        """
        logger.info("Preparing thumbnail training data...")
        
        # Query videos with features and channel info
        query = self.session.query(
            Video.video_id,
            Video.channel_id,        # for channel-grouped CV splits
            Video.published_at,      # for age-stabilization filter (see below)
            Video.view_count,
            Video.duration_seconds,
            Channel.subscriber_count,
            Channel.avg_views_per_video,
            Channel.size_tier,
            Channel.primary_category,
            Channel.niche_id,
            VideoFeatures.face_count,
            VideoFeatures.has_face,
            VideoFeatures.face_area_ratio,
            VideoFeatures.brightness,
            VideoFeatures.saturation,
            VideoFeatures.contrast,
            VideoFeatures.edge_density,
            VideoFeatures.composition_score,
            VideoFeatures.dominant_color_1,  # Hex color
            VideoFeatures.face_emotion_primary,
            VideoFeatures.face_emotion_intensity,
        ).join(
            VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).join(
            Channel, Video.channel_id == Channel.channel_id
        ).filter(
            and_(
                Video.view_count >= min_views,
                VideoFeatures.thumbnail_processed == True,
                Channel.avg_views_per_video > 0,
            )
        )
        
        if limit:
            query = query.limit(limit)
        
        results = query.all()
        logger.info(f"Retrieved {len(results)} samples")
        
        # Convert to DataFrame
        df = pd.DataFrame(results, columns=[
            'video_id', 'channel_id', 'published_at',
            'view_count', 'duration_seconds',
            'subscriber_count', 'avg_views_per_video', 'size_tier',
            'primary_category', 'niche_id',
            'face_count', 'has_face', 'face_area_ratio',
            'brightness', 'saturation', 'contrast', 'edge_density',
            'composition_score', 'dominant_color_hex',
            'face_emotion_primary', 'face_emotion_intensity',
        ])
        
        # Convert hex color to RGB
        df['dominant_color_r'] = df['dominant_color_hex'].apply(self._hex_to_r)
        df['dominant_color_g'] = df['dominant_color_hex'].apply(self._hex_to_g)
        df['dominant_color_b'] = df['dominant_color_hex'].apply(self._hex_to_b)
        
        # Calculate target: performance vs channel baseline
        df['performance_ratio'] = df['view_count'] / df['avg_views_per_video']
        
        # Cap extreme outliers (viral videos would skew the model)
        df['performance_ratio'] = df['performance_ratio'].clip(0.01, 10.0)
        
        # Calculate video age in days (for normalization and as a feature).
        # Robust to both naive and tz-aware ``published_at``: coerce everything
        # to UTC then drop the tz so the subtraction against a naive ``now`` is
        # well-defined. (This branch was previously dead — ``published_at`` was
        # never selected — so it had not been exercised before.)
        if 'published_at' in df.columns and df['published_at'].notna().any():
            now = pd.Timestamp.now(tz="UTC").tz_localize(None)
            published = pd.to_datetime(df['published_at'], utc=True).dt.tz_localize(None)
            df['age_days'] = (now - published).dt.days
            df['age_days'] = df['age_days'].clip(1, None)  # Minimum 1 day
            
            # Age-adjusted performance: views_per_day / expected_per_day
            # This gives more credit to newer videos that get views quickly
            df['views_per_day'] = df['view_count'] / df['age_days']
            expected_per_day = df['avg_views_per_video'] / 30  # Assume 30-day maturity
            df['age_adjusted_ratio'] = df['views_per_day'] / expected_per_day.clip(1, None)
            df['age_adjusted_ratio'] = df['age_adjusted_ratio'].clip(0.01, 10.0)
            
            # Filter to videos with stable performance (at least 14 days old)
            # This ensures we're training on "final" performance, not early volatility
            stable_mask = df['age_days'] >= 14
            logger.info(f"Filtering to stable videos (14+ days): {stable_mask.sum()}/{len(df)}")
            df = df[stable_mask].copy()
        else:
            df['age_days'] = 30  # Default if no published_at
            df['age_adjusted_ratio'] = df['performance_ratio']
        
        # Log transform for better distribution
        # Use age-adjusted ratio for more accurate training
        df['target'] = np.log1p(df['age_adjusted_ratio'])
        
        # Feature engineering
        df = self._engineer_features(df)
        
        # Select feature columns
        feature_cols = self._get_feature_columns(df)
        
        X = df[feature_cols]
        y = df['target']
        
        logger.info(f"Prepared {len(X)} samples with {len(feature_cols)} features")
        
        return X, y
    
    def _engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Engineer additional features."""
        
        # Duration buckets
        df['duration_bucket'] = pd.cut(
            df['duration_seconds'].fillna(0),
            bins=[0, 60, 180, 480, 900, 1800, float('inf')],
            labels=['<1min', '1-3min', '3-8min', '8-15min', '15-30min', '30min+']
        )
        
        # Channel size numeric
        size_map = {
            'nano': 0, 'micro': 1, 'small': 2, 
            'medium': 3, 'large': 4, 'mega': 5
        }
        df['size_tier_numeric'] = df['size_tier'].map(size_map).fillna(2)
        
        # Age bucket (for feature, not for prediction - helps model understand age patterns)
        if 'age_days' in df.columns:
            df['age_bucket'] = pd.cut(
                df['age_days'],
                bins=[0, 30, 90, 180, 365, float('inf')],
                labels=['<1mo', '1-3mo', '3-6mo', '6-12mo', '1yr+']
            )
        
        # Emotion encoding
        emotion_map = {
            'happy': 1, 'surprise': 2, 'neutral': 0,
            'sad': -1, 'angry': -2, 'fear': -1, 'disgust': -2
        }
        df['emotion_valence'] = df['face_emotion_primary'].map(emotion_map).fillna(0)
        
        # Fill NaN values
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df[numeric_cols] = df[numeric_cols].fillna(0)
        
        # Category encoding
        df['category_encoded'] = pd.Categorical(df['primary_category']).codes
        
        # Niche encoding (use -1 for missing)
        df['niche_encoded'] = df['niche_id'].fillna(-1).astype(int)
        
        return df
    
    def _get_feature_columns(self, df: pd.DataFrame) -> List[str]:
        """Get list of feature columns to use."""
        return [
            # Thumbnail features
            'face_count',
            'has_face',
            'face_area_ratio',
            'brightness',
            'saturation',
            'contrast',
            'edge_density',
            'composition_score',
            'dominant_color_r',
            'dominant_color_g',
            'dominant_color_b',
            'face_emotion_intensity',
            'emotion_valence',
            # Context features
            'size_tier_numeric',
            'category_encoded',
            'niche_encoded',
            'subscriber_count',
        ]
    
    def get_feature_importance_names(self) -> List[str]:
        """Get human-readable feature names for importance plotting."""
        return [
            'Face Count',
            'Has Face',
            'Face Area Ratio',
            'Brightness',
            'Saturation',
            'Contrast',
            'Edge Density',
            'Composition Score',
            'Dominant Red',
            'Dominant Green',
            'Dominant Blue',
            'Emotion Intensity',
            'Emotion Valence',
            'Channel Size',
            'Category',
            'Niche',
            'Subscriber Count',
        ]

