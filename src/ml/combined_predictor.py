"""
Combined Performance Predictor

Uses Title + Thumbnail + Niche + Channel Size to predict video performance.
This should have better predictive power than individual features alone.
"""
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import structlog

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sqlalchemy import and_

from src.database.models import Video, VideoFeatures, Channel
from src.database.connection import get_session

logger = structlog.get_logger()

MODEL_DIR = Path(__file__).parent.parent.parent / "models"
MODEL_PATH = MODEL_DIR / "combined_predictor.pkl"


@dataclass
class CombinedPrediction:
    """Result of combined prediction."""
    score: float  # 0-100
    predicted_ratio: float  # vs channel baseline
    percentile: int
    confidence: str  # low, medium, high
    top_positive_factors: List[str]
    top_negative_factors: List[str]
    verdict: str


@dataclass
class CombinedTrainingResult:
    """Training results."""
    samples: int
    features_used: int
    train_r2: float
    val_r2: float
    val_rmse: float
    val_mae: float
    feature_importance: Dict[str, float]


class CombinedPredictor:
    """
    Predicts video performance using all available features.
    
    Features used:
    - Thumbnail: faces, brightness, saturation, composition, colors, emotions
    - Title: length, words, numbers, hooks, caps
    - Context: niche, category, channel size, subscriber count
    - Metadata: duration, posting hour, posting day
    """
    
    FEATURE_NAMES = [
        # Thumbnail features
        'face_count', 'has_face', 'face_area_ratio', 'brightness', 
        'saturation', 'contrast', 'edge_density', 'composition_score',
        'color_r', 'color_g', 'color_b', 'emotion_intensity', 'emotion_valence',
        # Title features
        'title_length', 'title_words', 'title_has_number', 'title_has_question',
        'title_has_exclamation', 'title_caps_ratio',
        # Context features
        'subscriber_count', 'size_tier_numeric', 'category_encoded', 'niche_encoded',
        # Metadata features
        'duration_seconds', 'duration_bucket', 'posting_hour', 'posting_day',
    ]
    
    FEATURE_DISPLAY_NAMES = [
        'Face Count', 'Has Face', 'Face Area', 'Brightness',
        'Saturation', 'Contrast', 'Edge Density', 'Composition',
        'Color Red', 'Color Green', 'Color Blue', 'Emotion Intensity', 'Emotion Valence',
        'Title Length', 'Title Words', 'Title Has Number', 'Title Has Question',
        'Title Has !', 'Title Caps %',
        'Subscribers', 'Channel Size', 'Category', 'Niche',
        'Duration', 'Duration Bucket', 'Post Hour', 'Post Day',
    ]
    
    def __init__(self):
        """Initialize predictor."""
        self.model = None
        self.training_stats = None
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    def train(
        self,
        min_views: int = 100,
        test_size: float = 0.2,
        limit: Optional[int] = None,
    ) -> CombinedTrainingResult:
        """Train the combined predictor."""
        if not HAS_LIGHTGBM:
            raise ImportError("LightGBM required. Run: pip install lightgbm")
        
        logger.info("Preparing training data...")
        
        with get_session() as session:
            X, y, df = self._prepare_data(session, min_views, limit)
        
        logger.info(f"Training on {len(X)} samples with {X.shape[1]} features")
        
        # Split
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=test_size, random_state=42
        )
        
        # Train
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        
        params = {
            'objective': 'regression',
            'metric': 'rmse',
            'boosting_type': 'gbdt',
            'num_leaves': 63,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'n_jobs': -1,
        }
        
        self.model = lgb.train(
            params,
            train_data,
            num_boost_round=1000,
            valid_sets=[train_data, val_data],
            valid_names=['train', 'val'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=50),
                lgb.log_evaluation(period=100)
            ]
        )
        
        # Evaluate
        train_pred = self.model.predict(X_train)
        val_pred = self.model.predict(X_val)
        
        train_r2 = r2_score(y_train, train_pred)
        val_r2 = r2_score(y_val, val_pred)
        val_rmse = np.sqrt(mean_squared_error(y_val, val_pred))
        val_mae = mean_absolute_error(y_val, val_pred)
        
        # Feature importance
        importance = self.model.feature_importance(importance_type='gain')
        importance_dict = {}
        for name, imp in zip(self.FEATURE_DISPLAY_NAMES, importance):
            importance_dict[name] = float(imp)
        importance_dict = dict(sorted(importance_dict.items(), key=lambda x: x[1], reverse=True))
        
        # Store stats
        self.training_stats = {
            'y_mean': float(y.mean()),
            'y_std': float(y.std()),
            'percentiles': {p: float(np.percentile(y, p)) for p in [10, 25, 50, 75, 90, 95]},
        }
        
        self.save()
        
        return CombinedTrainingResult(
            samples=len(X),
            features_used=X.shape[1],
            train_r2=train_r2,
            val_r2=val_r2,
            val_rmse=val_rmse,
            val_mae=val_mae,
            feature_importance=importance_dict,
        )
    
    def _prepare_data(
        self, 
        session, 
        min_views: int,
        limit: Optional[int]
    ) -> Tuple[np.ndarray, np.ndarray, pd.DataFrame]:
        """Prepare training data from database."""
        
        query = session.query(
            Video.video_id,
            Video.view_count,
            Video.duration_seconds,
            Video.published_at,
            Channel.subscriber_count,
            Channel.avg_views_per_video,
            Channel.size_tier,
            Channel.primary_category,
            Channel.niche_id,
            # Thumbnail features
            VideoFeatures.face_count,
            VideoFeatures.has_face,
            VideoFeatures.face_area_ratio,
            VideoFeatures.brightness,
            VideoFeatures.saturation,
            VideoFeatures.contrast,
            VideoFeatures.edge_density,
            VideoFeatures.composition_score,
            VideoFeatures.dominant_color_1,
            VideoFeatures.face_emotion_primary,
            VideoFeatures.face_emotion_intensity,
            # Title features
            VideoFeatures.title_char_length,
            VideoFeatures.title_word_count,
            VideoFeatures.title_has_number,
            VideoFeatures.title_has_question,
            VideoFeatures.title_has_exclamation,
            VideoFeatures.title_caps_ratio,
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
        columns = [
            'video_id', 'view_count', 'duration_seconds', 'published_at',
            'subscriber_count', 'avg_views_per_video', 'size_tier', 
            'primary_category', 'niche_id',
            'face_count', 'has_face', 'face_area_ratio', 'brightness',
            'saturation', 'contrast', 'edge_density', 'composition_score',
            'dominant_color_hex', 'face_emotion_primary', 'face_emotion_intensity',
            'title_char_length', 'title_word_count', 'title_has_number',
            'title_has_question', 'title_has_exclamation', 'title_caps_ratio',
        ]
        
        df = pd.DataFrame(results, columns=columns)
        
        # Target: performance vs baseline (age-adjusted)
        df['performance_ratio'] = df['view_count'] / df['avg_views_per_video']
        df['performance_ratio'] = df['performance_ratio'].clip(0.01, 10.0)
        
        # Calculate video age for normalization
        # Handle timezone: convert to naive UTC for comparison
        now = pd.Timestamp.now()
        published = pd.to_datetime(df['published_at']).dt.tz_localize(None)
        df['age_days'] = (now - published).dt.days
        df['age_days'] = df['age_days'].clip(1, None)  # Minimum 1 day
        
        # Age-adjusted performance: views_per_day / expected_per_day
        df['views_per_day'] = df['view_count'] / df['age_days']
        expected_per_day = df['avg_views_per_video'] / 30  # Assume 30-day maturity
        df['age_adjusted_ratio'] = df['views_per_day'] / expected_per_day.clip(1, None)
        df['age_adjusted_ratio'] = df['age_adjusted_ratio'].clip(0.01, 10.0)
        
        # Filter to stable videos (14+ days old) for training
        stable_mask = df['age_days'] >= 14
        logger.info(f"Stable videos (14+ days): {stable_mask.sum()}/{len(df)}")
        df = df[stable_mask].copy()
        
        # Use age-adjusted ratio as target
        df['target'] = np.log1p(df['age_adjusted_ratio'])
        
        # Feature engineering
        df = self._engineer_features(df)
        
        # Build feature matrix
        feature_cols = [
            'face_count', 'has_face_num', 'face_area_ratio', 'brightness',
            'saturation', 'contrast', 'edge_density', 'composition_score',
            'color_r', 'color_g', 'color_b', 'emotion_intensity', 'emotion_valence',
            'title_length', 'title_words', 'title_has_number_num', 'title_has_question_num',
            'title_has_exclamation_num', 'title_caps_ratio',
            'subscriber_count', 'size_tier_numeric', 'category_encoded', 'niche_encoded',
            'duration_seconds_clean', 'duration_bucket_encoded', 'posting_hour', 'posting_day',
        ]
        
        X = df[feature_cols].values
        y = df['target'].values
        
        return X, y, df
    
    def _engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Engineer features from raw data."""
        
        # Boolean to numeric
        df['has_face_num'] = df['has_face'].astype(int)
        df['title_has_number_num'] = df['title_has_number'].fillna(False).astype(int)
        df['title_has_question_num'] = df['title_has_question'].fillna(False).astype(int)
        df['title_has_exclamation_num'] = df['title_has_exclamation'].fillna(False).astype(int)
        
        # Title length
        df['title_length'] = df['title_char_length'].fillna(50)
        df['title_words'] = df['title_word_count'].fillna(8)
        
        # Color extraction
        def hex_to_rgb(hex_color, component):
            if not hex_color or len(str(hex_color)) < 6:
                return 128
            try:
                hex_color = str(hex_color).lstrip('#')
                if component == 'r':
                    return int(hex_color[0:2], 16)
                elif component == 'g':
                    return int(hex_color[2:4], 16)
                else:
                    return int(hex_color[4:6], 16)
            except:
                return 128
        
        df['color_r'] = df['dominant_color_hex'].apply(lambda x: hex_to_rgb(x, 'r'))
        df['color_g'] = df['dominant_color_hex'].apply(lambda x: hex_to_rgb(x, 'g'))
        df['color_b'] = df['dominant_color_hex'].apply(lambda x: hex_to_rgb(x, 'b'))
        
        # Emotion
        emotion_map = {'happy': 1, 'surprise': 2, 'neutral': 0, 'sad': -1, 'angry': -2, 'fear': -1, 'disgust': -2}
        df['emotion_valence'] = df['face_emotion_primary'].map(emotion_map).fillna(0)
        df['emotion_intensity'] = df['face_emotion_intensity'].fillna(0)
        
        # Size tier
        size_map = {'nano': 0, 'micro': 1, 'small': 2, 'medium': 3, 'large': 4, 'mega': 5, 'top': 6}
        df['size_tier_numeric'] = df['size_tier'].map(size_map).fillna(2)
        
        # Category
        df['category_encoded'] = pd.Categorical(df['primary_category']).codes
        
        # Niche
        df['niche_encoded'] = df['niche_id'].fillna(-1).astype(int)
        
        # Duration
        df['duration_seconds_clean'] = df['duration_seconds'].fillna(300).clip(0, 7200)
        
        # Duration bucket
        df['duration_bucket'] = pd.cut(
            df['duration_seconds_clean'],
            bins=[0, 60, 180, 480, 900, 1800, 7200],
            labels=[0, 1, 2, 3, 4, 5]
        )
        df['duration_bucket_encoded'] = df['duration_bucket'].astype(float).fillna(2)
        
        # Posting time
        df['posting_hour'] = pd.to_datetime(df['published_at']).dt.hour.fillna(12)
        df['posting_day'] = pd.to_datetime(df['published_at']).dt.dayofweek.fillna(3)
        
        # Fill remaining NaN
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df[numeric_cols] = df[numeric_cols].fillna(0)
        
        return df
    
    def predict(self, features: Dict[str, Any]) -> CombinedPrediction:
        """Make a prediction for a video."""
        if self.model is None:
            self.load()
        
        # Build feature vector
        vector = self._build_feature_vector(features)
        
        # Predict
        log_pred = self.model.predict([vector])[0]
        predicted_ratio = np.expm1(log_pred)
        predicted_ratio = max(0.01, min(10.0, predicted_ratio))
        
        # Score (0-100)
        score = self._ratio_to_score(predicted_ratio)
        
        # Percentile
        percentile = self._get_percentile(log_pred)
        
        # Confidence based on how complete the features are
        feature_completeness = sum(1 for v in features.values() if v is not None) / len(features)
        confidence = 'high' if feature_completeness > 0.8 else ('medium' if feature_completeness > 0.5 else 'low')
        
        # Factor analysis
        positive, negative = self._analyze_factors(features)
        
        # Verdict
        if predicted_ratio >= 1.5:
            verdict = "🔥 Strong potential - likely to outperform"
        elif predicted_ratio >= 1.0:
            verdict = "👍 Good - should perform at or above average"
        elif predicted_ratio >= 0.7:
            verdict = "😐 Average - typical performance expected"
        else:
            verdict = "⚠️ Below average - consider improvements"
        
        return CombinedPrediction(
            score=score,
            predicted_ratio=predicted_ratio,
            percentile=percentile,
            confidence=confidence,
            top_positive_factors=positive,
            top_negative_factors=negative,
            verdict=verdict,
        )
    
    def _build_feature_vector(self, features: Dict) -> List[float]:
        """Build feature vector from input dict."""
        return [
            features.get('face_count', 0),
            1 if features.get('has_face', False) else 0,
            features.get('face_area_ratio', 0),
            features.get('brightness', 0.5),
            features.get('saturation', 0.5),
            features.get('contrast', 0.5),
            features.get('edge_density', 0.5),
            features.get('composition_score', 0.5),
            features.get('color_r', 128),
            features.get('color_g', 128),
            features.get('color_b', 128),
            features.get('emotion_intensity', 0),
            features.get('emotion_valence', 0),
            features.get('title_length', 50),
            features.get('title_words', 8),
            1 if features.get('title_has_number', False) else 0,
            1 if features.get('title_has_question', False) else 0,
            1 if features.get('title_has_exclamation', False) else 0,
            features.get('title_caps_ratio', 0.1),
            features.get('subscriber_count', 10000),
            features.get('size_tier_numeric', 2),
            features.get('category_encoded', 0),
            features.get('niche_encoded', -1),
            features.get('duration_seconds', 300),
            features.get('duration_bucket', 2),
            features.get('posting_hour', 12),
            features.get('posting_day', 3),
        ]
    
    def _ratio_to_score(self, ratio: float) -> float:
        """Convert performance ratio to 0-100 score."""
        log_ratio = np.log2(max(0.25, min(4.0, ratio)))
        score = (log_ratio + 2) * 25
        return max(0, min(100, score))
    
    def _get_percentile(self, log_pred: float) -> int:
        """Get percentile of prediction."""
        if self.training_stats is None:
            return 50
        for p in [95, 90, 75, 50, 25, 10]:
            if log_pred >= self.training_stats['percentiles'].get(p, 0):
                return p
        return 5
    
    def _analyze_factors(self, features: Dict) -> Tuple[List[str], List[str]]:
        """Analyze positive and negative factors."""
        positive = []
        negative = []
        
        # Face
        if features.get('has_face'):
            positive.append("✓ Has face in thumbnail")
        else:
            negative.append("✗ No face in thumbnail")
        
        # Brightness
        brightness = features.get('brightness', 0.5)
        if 0.3 <= brightness <= 0.7:
            positive.append("✓ Good brightness")
        elif brightness < 0.3:
            negative.append("✗ Thumbnail too dark")
        
        # Title number
        if features.get('title_has_number'):
            positive.append("✓ Title has number")
        
        # Title length
        length = features.get('title_length', 50)
        if 40 <= length <= 70:
            positive.append("✓ Good title length")
        elif length < 30:
            negative.append("✗ Title too short")
        elif length > 80:
            negative.append("✗ Title too long")
        
        return positive[:3], negative[:3]
    
    def save(self):
        """Save model."""
        with open(MODEL_PATH, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'training_stats': self.training_stats,
            }, f)
        logger.info(f"Model saved to {MODEL_PATH}")
    
    def load(self):
        """Load model."""
        if not MODEL_PATH.exists():
            raise FileNotFoundError("Model not found. Train first.")
        with open(MODEL_PATH, 'rb') as f:
            data = pickle.load(f)
        self.model = data['model']
        self.training_stats = data['training_stats']
        logger.info("Model loaded")
    
    def is_trained(self) -> bool:
        """Check if model exists."""
        return MODEL_PATH.exists()

