"""
Thumbnail Performance Predictor

Predicts how well a thumbnail will perform relative to channel baseline.
Uses gradient boosting (LightGBM) trained on historical video data.
"""
import pickle
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import structlog

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False
    
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

from src.database.connection import get_session
from src.ml.data_prep import DataPreparation

logger = structlog.get_logger()

# Model storage path
MODEL_DIR = Path(__file__).parent.parent.parent / "models"
MODEL_PATH = MODEL_DIR / "thumbnail_predictor.pkl"


@dataclass
class PredictionResult:
    """Result of a thumbnail performance prediction."""
    score: float  # 0-100 score
    performance_ratio: float  # Predicted views vs baseline (1.0 = average)
    percentile: int  # What percentile this would be (0-100)
    suggestions: List[str]  # Improvement suggestions
    feature_impacts: Dict[str, float]  # How each feature affects the score


@dataclass
class TrainingResult:
    """Result of model training."""
    samples_used: int
    train_rmse: float
    val_rmse: float
    val_mae: float
    val_r2: float
    feature_importance: Dict[str, float]


class ThumbnailPredictor:
    """
    Predicts thumbnail performance using gradient boosting.
    
    Usage:
        predictor = ThumbnailPredictor()
        predictor.train()  # Train on historical data
        
        result = predictor.predict(thumbnail_features)
        print(f"Score: {result.score}/100")
        print(f"Suggestions: {result.suggestions}")
    """
    
    def __init__(self):
        """Initialize predictor."""
        self.model = None
        self.feature_names = None
        self.training_stats = None
        
        # Ensure model directory exists
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    def train(
        self,
        min_views: int = 100,
        test_size: float = 0.2,
        limit: Optional[int] = None,
    ) -> TrainingResult:
        """
        Train the thumbnail predictor model.
        
        Args:
            min_views: Minimum views to include samples
            test_size: Fraction for validation
            limit: Max samples (None for all)
            
        Returns:
            TrainingResult with metrics
        """
        if not HAS_LIGHTGBM:
            raise ImportError("LightGBM not installed. Run: pip install lightgbm")
        
        logger.info("Training thumbnail predictor...")
        
        # Prepare data
        with get_session() as session:
            data_prep = DataPreparation(session)
            X, y = data_prep.get_thumbnail_training_data(
                min_views=min_views,
                limit=limit
            )
            self.feature_names = list(X.columns)
            feature_display_names = data_prep.get_feature_importance_names()
        
        # Split data
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=test_size, random_state=42
        )
        
        logger.info(f"Training on {len(X_train)} samples, validating on {len(X_val)}")
        
        # Create LightGBM datasets
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        
        # Model parameters
        params = {
            'objective': 'regression',
            'metric': 'rmse',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'n_jobs': -1,
        }
        
        # Train with early stopping
        self.model = lgb.train(
            params,
            train_data,
            num_boost_round=500,
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
        
        train_rmse = np.sqrt(mean_squared_error(y_train, train_pred))
        val_rmse = np.sqrt(mean_squared_error(y_val, val_pred))
        val_mae = mean_absolute_error(y_val, val_pred)
        val_r2 = r2_score(y_val, val_pred)
        
        # Feature importance
        importance = self.model.feature_importance(importance_type='gain')
        importance_dict = {}
        for name, display_name, imp in zip(self.feature_names, feature_display_names, importance):
            importance_dict[display_name] = float(imp)
        
        # Sort by importance
        importance_dict = dict(sorted(
            importance_dict.items(), 
            key=lambda x: x[1], 
            reverse=True
        ))
        
        # Store training stats for percentile calculations
        self.training_stats = {
            'y_mean': float(y.mean()),
            'y_std': float(y.std()),
            'y_min': float(y.min()),
            'y_max': float(y.max()),
            'percentiles': {
                p: float(np.percentile(y, p)) 
                for p in [10, 25, 50, 75, 90, 95, 99]
            }
        }
        
        # Save model
        self.save()
        
        result = TrainingResult(
            samples_used=len(X),
            train_rmse=train_rmse,
            val_rmse=val_rmse,
            val_mae=val_mae,
            val_r2=val_r2,
            feature_importance=importance_dict,
        )
        
        logger.info(
            "Training complete",
            samples=len(X),
            val_rmse=f"{val_rmse:.4f}",
            val_r2=f"{val_r2:.4f}"
        )
        
        return result
    
    def predict(self, features: Dict[str, Any]) -> PredictionResult:
        """
        Predict thumbnail performance.
        
        Args:
            features: Dictionary of thumbnail features
            
        Returns:
            PredictionResult with score and suggestions
        """
        if self.model is None:
            self.load()
        
        # Prepare feature vector
        feature_vector = self._prepare_features(features)
        
        # Predict (log scale)
        log_pred = self.model.predict([feature_vector])[0]
        
        # Convert back to ratio
        performance_ratio = np.expm1(log_pred)
        performance_ratio = max(0.01, min(10.0, performance_ratio))
        
        # Calculate score (0-100)
        # 0.5x baseline = 25, 1.0x = 50, 2.0x = 75, 3.5x = 100
        score = self._ratio_to_score(performance_ratio)
        
        # Calculate percentile
        percentile = self._calculate_percentile(log_pred)
        
        # Generate suggestions
        suggestions = self._generate_suggestions(features, performance_ratio)
        
        # Feature impacts (SHAP-like analysis)
        feature_impacts = self._calculate_feature_impacts(features)
        
        return PredictionResult(
            score=score,
            performance_ratio=performance_ratio,
            percentile=percentile,
            suggestions=suggestions,
            feature_impacts=feature_impacts,
        )
    
    def _prepare_features(self, features: Dict[str, Any]) -> List[float]:
        """Prepare feature vector from dictionary."""
        vector = []
        
        # Map input features to model features
        vector.append(features.get('face_count', 0))
        vector.append(1 if features.get('has_face', False) else 0)
        vector.append(features.get('face_area_ratio', 0))
        vector.append(features.get('brightness', 0.5))
        vector.append(features.get('saturation', 0.5))
        vector.append(features.get('contrast', 0.5))
        vector.append(features.get('edge_density', 0.5))
        vector.append(features.get('composition_score', 0.5))
        vector.append(features.get('dominant_color_r', 128))
        vector.append(features.get('dominant_color_g', 128))
        vector.append(features.get('dominant_color_b', 128))
        vector.append(features.get('face_emotion_intensity', 0))
        
        # Emotion valence
        emotion = features.get('face_emotion_primary', 'neutral')
        emotion_map = {
            'happy': 1, 'surprise': 2, 'neutral': 0,
            'sad': -1, 'angry': -2, 'fear': -1, 'disgust': -2
        }
        vector.append(emotion_map.get(emotion, 0))
        
        # Context features
        size_map = {'nano': 0, 'micro': 1, 'small': 2, 'medium': 3, 'large': 4, 'mega': 5}
        vector.append(size_map.get(features.get('size_tier', 'small'), 2))
        vector.append(features.get('category_encoded', 0))
        vector.append(features.get('niche_encoded', -1))
        vector.append(features.get('subscriber_count', 10000))
        
        return vector
    
    def _ratio_to_score(self, ratio: float) -> float:
        """Convert performance ratio to 0-100 score."""
        # Logarithmic mapping
        # 0.25x -> 0, 0.5x -> 25, 1.0x -> 50, 2.0x -> 75, 4.0x -> 100
        log_ratio = np.log2(max(0.25, min(4.0, ratio)))
        score = (log_ratio + 2) * 25  # Maps -2 to 2 -> 0 to 100
        return max(0, min(100, score))
    
    def _calculate_percentile(self, log_pred: float) -> int:
        """Calculate what percentile this prediction is."""
        if self.training_stats is None:
            return 50
        
        percentiles = self.training_stats['percentiles']
        
        for p in [99, 95, 90, 75, 50, 25, 10]:
            if log_pred >= percentiles[p]:
                return p
        return 5
    
    def _generate_suggestions(
        self, 
        features: Dict[str, Any], 
        predicted_ratio: float
    ) -> List[str]:
        """Generate improvement suggestions based on features."""
        suggestions = []
        
        # Face suggestions
        if not features.get('has_face', False):
            suggestions.append(
                "🎭 Add a face — thumbnails with faces get 23% more clicks on average"
            )
        elif features.get('face_count', 0) == 1:
            if features.get('face_area_ratio', 0) < 0.1:
                suggestions.append(
                    "📏 Make the face larger — it's too small to grab attention"
                )
        
        # Emotion suggestions
        if features.get('has_face') and features.get('face_emotion_intensity', 0) < 0.5:
            suggestions.append(
                "😮 Show more expression — high-energy emotions increase CTR"
            )
        
        # Brightness suggestions
        brightness = features.get('brightness', 0.5)
        if brightness < 0.3:
            suggestions.append(
                "☀️ Brighten the thumbnail — it's too dark and may not stand out"
            )
        elif brightness > 0.85:
            suggestions.append(
                "🌙 Reduce brightness slightly — too bright can wash out details"
            )
        
        # Saturation suggestions
        saturation = features.get('saturation', 0.5)
        if saturation < 0.3:
            suggestions.append(
                "🎨 Increase color saturation — more vibrant colors grab attention"
            )
        
        # Composition suggestions
        composition = features.get('composition_score', 0.5)
        if composition < 0.4:
            suggestions.append(
                "📐 Improve composition — try placing key elements on rule-of-thirds lines"
            )
        
        # Contrast suggestions
        contrast = features.get('contrast', 0.5)
        if contrast < 0.3:
            suggestions.append(
                "⚡ Increase contrast — low contrast makes thumbnails look flat"
            )
        
        # If already good
        if predicted_ratio > 1.5 and len(suggestions) == 0:
            suggestions.append(
                "✨ Great thumbnail! This should perform above average"
            )
        
        return suggestions[:5]  # Limit to 5 suggestions
    
    def _calculate_feature_impacts(self, features: Dict[str, Any]) -> Dict[str, float]:
        """Calculate how each feature impacts the prediction."""
        # Simplified impact calculation
        # In production, you'd use SHAP values
        impacts = {}
        
        if features.get('has_face'):
            impacts['Face Present'] = 0.15
            if features.get('face_emotion_intensity', 0) > 0.7:
                impacts['Strong Expression'] = 0.10
        
        if features.get('brightness', 0.5) > 0.4 and features.get('brightness', 0.5) < 0.7:
            impacts['Good Brightness'] = 0.05
        
        if features.get('saturation', 0.5) > 0.5:
            impacts['Vibrant Colors'] = 0.08
        
        if features.get('composition_score', 0.5) > 0.6:
            impacts['Strong Composition'] = 0.07
        
        return impacts
    
    def save(self):
        """Save model to disk."""
        if self.model is None:
            raise ValueError("No model to save")
        
        data = {
            'model': self.model,
            'feature_names': self.feature_names,
            'training_stats': self.training_stats,
        }
        
        with open(MODEL_PATH, 'wb') as f:
            pickle.dump(data, f)
        
        logger.info(f"Model saved to {MODEL_PATH}")
    
    def load(self):
        """Load model from disk."""
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"No trained model found at {MODEL_PATH}. Run training first."
            )
        
        with open(MODEL_PATH, 'rb') as f:
            data = pickle.load(f)
        
        self.model = data['model']
        self.feature_names = data['feature_names']
        self.training_stats = data['training_stats']
        
        logger.info("Model loaded successfully")
    
    def is_trained(self) -> bool:
        """Check if model exists."""
        return MODEL_PATH.exists()

