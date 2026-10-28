"""
Improved Performance Predictor

Uses ALL features from the guide:
- Thumbnail: faces, emotions, text (OCR), colors, composition
- Title: length, numbers, hooks, caps
- Niche-relative: comparison to top performers
- Context: channel size, category, timing
"""
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple
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
from src.ml.niche_features import NicheFeatureCalculator

logger = structlog.get_logger()

MODEL_DIR = Path(__file__).parent.parent.parent / "models"
MODEL_PATH = MODEL_DIR / "improved_predictor.pkl"


@dataclass 
class ImprovedTrainingResult:
    """Training results."""
    samples: int
    features_used: int
    train_r2: float
    val_r2: float
    val_rmse: float
    val_mae: float
    feature_importance: Dict[str, float]


class ImprovedPredictor:
    """
    Predicts video performance using ALL available features.
    
    Features from guide:
    1. Thumbnail (18 features):
       - Face count, face size, face emotion
       - Text present, text word count, text readability
       - Colors, brightness, saturation, contrast
       - Edge density, composition, complexity
    2. Niche-relative (12 features):
       - Similarity to top performers
       - Each feature compared to niche average
    3. Title (6 features):
       - Length, words, numbers, questions, caps
    4. Context (6 features):
       - Subscribers, size tier, category, niche
       - Duration, posting time
    """
    
    def __init__(self):
        """Initialize predictor."""
        self.model = None
        self.training_stats = None
        self.niche_calculator = None
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    def train(
        self,
        min_views: int = 100,
        test_size: float = 0.2,
        limit: Optional[int] = None,
    ) -> ImprovedTrainingResult:
        """Train with all features."""
        if not HAS_LIGHTGBM:
            raise ImportError("LightGBM required")
        
        logger.info("Preparing training data with niche-relative features...")
        
        with get_session() as session:
            self.niche_calculator = NicheFeatureCalculator(session)
            
            # Precompute niche benchmarks
            logger.info("Precomputing niche benchmarks...")
            self.niche_calculator.precompute_all_niches()
            
            # Prepare data
            X, y, feature_names = self._prepare_data(session, min_views, limit)
        
        logger.info(f"Training on {len(X)} samples with {len(feature_names)} features")
        
        # Split
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=test_size, random_state=42
        )
        
        # Train
        train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_names)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        
        params = {
            'objective': 'regression',
            'metric': 'rmse',
            'boosting_type': 'gbdt',
            'num_leaves': 63,
            'learning_rate': 0.03,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'min_child_samples': 20,
            'verbose': -1,
            'n_jobs': -1,
        }
        
        self.model = lgb.train(
            params,
            train_data,
            num_boost_round=1500,
            valid_sets=[train_data, val_data],
            valid_names=['train', 'val'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=100),
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
        importance_dict = {name: float(imp) for name, imp in zip(feature_names, importance)}
        importance_dict = dict(sorted(importance_dict.items(), key=lambda x: x[1], reverse=True))
        
        # Store stats
        self.training_stats = {
            'y_mean': float(y.mean()),
            'y_std': float(y.std()),
            'percentiles': {p: float(np.percentile(y, p)) for p in [10, 25, 50, 75, 90, 95]},
            'feature_names': feature_names,
        }
        
        self.save()
        
        return ImprovedTrainingResult(
            samples=len(X),
            features_used=len(feature_names),
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
    ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """Prepare training data with all features."""
        
        # Query all relevant data
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
            VideoFeatures.face_emotion_primary,
            VideoFeatures.face_emotion_intensity,
            VideoFeatures.has_text,
            VideoFeatures.text_word_count,
            VideoFeatures.text_area_ratio,
            VideoFeatures.brightness,
            VideoFeatures.saturation,
            VideoFeatures.contrast,
            VideoFeatures.edge_density,
            VideoFeatures.composition_score,
            VideoFeatures.dominant_color_1,
            VideoFeatures.dominant_color_2,
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
                Channel.niche_id.isnot(None),  # Only videos with niche
            )
        )
        
        if limit:
            query = query.limit(limit)
        
        results = query.all()
        logger.info(f"Retrieved {len(results)} samples")
        
        # Process each row
        feature_rows = []
        targets = []
        
        for row in results:
            (video_id, view_count, duration, published_at, sub_count, avg_views,
             size_tier, category, niche_id,
             face_count, has_face, face_area, face_emotion, face_intensity,
             has_text, text_words, text_area,
             brightness, saturation, contrast, edge_density, composition,
             color1, color2,
             title_length, title_words, title_number, title_question, 
             title_exclamation, title_caps) = row
            
            # Calculate target
            if avg_views <= 0:
                continue
            perf_ratio = view_count / avg_views
            perf_ratio = max(0.01, min(10.0, perf_ratio))
            target = np.log1p(perf_ratio)
            
            # Build feature dict
            features = {
                'face_count': face_count or 0,
                'has_face': has_face,
                'face_area_ratio': face_area or 0,
                'face_emotion_intensity': face_intensity or 0,
                'has_text': has_text,
                'text_word_count': text_words or 0,
                'text_area_ratio': text_area or 0,
                'brightness': brightness or 0.5,
                'saturation': saturation or 0.5,
                'contrast': contrast or 0.5,
                'edge_density': edge_density or 0.5,
                'composition_score': composition or 0.5,
                'title_char_length': title_length or 50,
                'title_word_count': title_words or 8,
            }
            
            # Calculate niche-relative features
            niche_rel = self.niche_calculator.calculate_relative_features(niche_id, features)
            
            # Build feature vector
            feature_vec = self._build_feature_vector(
                row, features, niche_rel
            )
            
            feature_rows.append(feature_vec)
            targets.append(target)
        
        X = np.array(feature_rows)
        y = np.array(targets)
        
        feature_names = self._get_feature_names()
        
        return X, y, feature_names
    
    def _build_feature_vector(self, row, features: Dict, niche_rel) -> List[float]:
        """Build complete feature vector."""
        (video_id, view_count, duration, published_at, sub_count, avg_views,
         size_tier, category, niche_id,
         face_count, has_face, face_area, face_emotion, face_intensity,
         has_text, text_words, text_area,
         brightness, saturation, contrast, edge_density, composition,
         color1, color2,
         title_length, title_words, title_number, title_question, 
         title_exclamation, title_caps) = row
        
        # Color extraction
        def hex_to_rgb(hex_color, component):
            if not hex_color:
                return 128
            try:
                hex_color = str(hex_color).lstrip('#')
                idx = {'r': 0, 'g': 2, 'b': 4}[component]
                return int(hex_color[idx:idx+2], 16)
            except:
                return 128
        
        # Emotion encoding
        emotion_map = {'happy': 1, 'surprise': 2, 'neutral': 0, 'sad': -1, 'angry': -2, 'fear': -1, 'disgust': -2}
        emotion_valence = emotion_map.get(face_emotion, 0)
        
        # Size tier encoding
        size_map = {'nano': 0, 'micro': 1, 'small': 2, 'medium': 3, 'large': 4, 'mega': 5, 'top': 6}
        size_numeric = size_map.get(size_tier, 2)
        
        # Category encoding (hash for consistency)
        category_hash = hash(category or '') % 20
        
        # Posting time
        try:
            posting_hour = pd.to_datetime(published_at).hour
            posting_day = pd.to_datetime(published_at).dayofweek
        except:
            posting_hour = 12
            posting_day = 3
        
        # Duration bucket
        dur = duration or 300
        if dur < 60:
            dur_bucket = 0
        elif dur < 180:
            dur_bucket = 1
        elif dur < 480:
            dur_bucket = 2
        elif dur < 900:
            dur_bucket = 3
        else:
            dur_bucket = 4
        
        # Build vector
        vec = [
            # Thumbnail features (13)
            face_count or 0,
            1 if has_face else 0,
            face_area or 0,
            face_intensity or 0,
            emotion_valence,
            1 if has_text else 0,
            text_words or 0,
            text_area or 0,
            brightness or 0.5,
            saturation or 0.5,
            contrast or 0.5,
            edge_density or 0.5,
            composition or 0.5,
            
            # Color features (6)
            hex_to_rgb(color1, 'r'),
            hex_to_rgb(color1, 'g'),
            hex_to_rgb(color1, 'b'),
            hex_to_rgb(color2, 'r'),
            hex_to_rgb(color2, 'g'),
            hex_to_rgb(color2, 'b'),
            
            # Title features (6)
            title_length or 50,
            title_words or 8,
            1 if title_number else 0,
            1 if title_question else 0,
            1 if title_exclamation else 0,
            title_caps or 0,
            
            # Context features (6)
            sub_count or 10000,
            size_numeric,
            category_hash,
            niche_id or -1,
            dur,
            dur_bucket,
            
            # Posting time (2)
            posting_hour,
            posting_day,
        ]
        
        # Niche-relative features (12)
        if niche_rel:
            vec.extend([
                niche_rel.face_vs_niche,
                niche_rel.face_count_vs_niche,
                niche_rel.face_area_vs_niche,
                niche_rel.text_vs_niche,
                niche_rel.text_words_vs_niche,
                niche_rel.brightness_vs_niche,
                niche_rel.saturation_vs_niche,
                niche_rel.contrast_vs_niche,
                niche_rel.edge_vs_niche,
                niche_rel.composition_vs_niche,
                niche_rel.title_length_vs_niche,
                niche_rel.similarity_to_top,
            ])
        else:
            vec.extend([0] * 12)
        
        return vec
    
    def _get_feature_names(self) -> List[str]:
        """Get feature names."""
        return [
            # Thumbnail (13)
            'face_count', 'has_face', 'face_area', 'face_intensity', 'emotion_valence',
            'has_text', 'text_words', 'text_area',
            'brightness', 'saturation', 'contrast', 'edge_density', 'composition',
            # Colors (6)
            'color1_r', 'color1_g', 'color1_b', 'color2_r', 'color2_g', 'color2_b',
            # Title (6)
            'title_length', 'title_words', 'title_number', 'title_question', 'title_exclamation', 'title_caps',
            # Context (6)
            'subscribers', 'size_tier', 'category', 'niche_id', 'duration', 'duration_bucket',
            # Posting (2)
            'posting_hour', 'posting_day',
            # Niche-relative (12)
            'niche_face', 'niche_face_count', 'niche_face_area',
            'niche_text', 'niche_text_words',
            'niche_brightness', 'niche_saturation', 'niche_contrast',
            'niche_edge', 'niche_composition', 'niche_title_length',
            'similarity_to_top',
        ]
    
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
    
    def is_trained(self) -> bool:
        return MODEL_PATH.exists()

