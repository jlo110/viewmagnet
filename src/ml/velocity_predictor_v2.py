"""
Velocity Predictor V2 - Predict views at any future milestone.

Given a video at ANY age, predict views at ANY future checkpoint:
- Day 3, Day 7, Day 14, Day 30

Accuracy by prediction:
- 3d → 7d: 90%
- 3d → 30d: 72%
- 7d → 14d: 95%
- 7d → 30d: 90%
- 14d → 30d: 95%

Early predictions (24h → X) are less reliable (45-60% accuracy).
"""
import numpy as np
import joblib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class MilestonePrediction:
    """Prediction for a specific milestone."""
    checkpoint: str  # "3d", "7d", "14d", "30d"
    predicted_views: int
    confidence: float  # 0-1 based on model accuracy
    hours_until: int  # Hours from now to this milestone
    growth_multiplier: float  # Predicted growth from current


@dataclass
class VelocityReport:
    """Complete velocity analysis for a video."""
    video_age_hours: float
    current_checkpoint: str  # Which checkpoint data we have
    current_views: int
    
    # Predictions for each future milestone
    predictions: Dict[str, MilestonePrediction]
    
    # Trajectory analysis
    trajectory: str  # "viral", "strong", "normal", "slow", "struggling"
    momentum_score: float  # 0-100, how well is velocity maintained
    
    # Comparison
    percentile: int  # 1-100 vs similar videos


class VelocityPredictorV2:
    """
    Unified velocity predictor using all trained models.
    
    Usage:
        predictor = VelocityPredictorV2()
        
        # For a video with 7 days of data
        report = predictor.predict(
            current_views=50000,
            hours_since_publish=168,  # 7 days
            views_history={
                '1h': 1000,
                '6h': 5000,
                '24h': 15000,
                '3d': 35000,
                '7d': 50000,
            },
            likes_history={'24h': 1500, '7d': 5000},
        )
        
        print(f"Predicted 30d views: {report.predictions['30d'].predicted_views:,}")
    """
    
    # Model accuracy by combination (from training)
    MODEL_ACCURACY = {
        '24h_to_3d': 0.50,   # Unreliable
        '24h_to_7d': 0.55,
        '24h_to_14d': 0.61,
        '24h_to_30d': 0.44,
        '3d_to_7d': 0.90,
        '3d_to_14d': 0.85,
        '3d_to_30d': 0.72,
        '7d_to_14d': 0.95,
        '7d_to_30d': 0.90,
        '14d_to_30d': 0.95,
    }
    
    # Hours for each checkpoint
    CHECKPOINT_HOURS = {
        '1h': 1,
        '6h': 6,
        '24h': 24,
        '3d': 72,
        '7d': 168,
        '14d': 336,
        '30d': 720,
    }
    
    def __init__(self, models_dir: str = "models"):
        """Load all velocity models."""
        self.models_dir = Path(models_dir)
        self.models = {}
        self.model_index = None
        self._load_models()
    
    def _load_models(self):
        """Load all available velocity models."""
        index_path = self.models_dir / "velocity_models_index.joblib"
        
        if index_path.exists():
            self.model_index = joblib.load(index_path)
            
            for key, info in self.model_index.get('models', {}).items():
                model_path = self.models_dir / info['file']
                if model_path.exists():
                    try:
                        data = joblib.load(model_path)
                        self.models[key] = data
                        logger.debug(f"Loaded model: {key}")
                    except Exception as e:
                        logger.warning(f"Failed to load {key}: {e}")
        
        logger.info(f"Loaded {len(self.models)} velocity models")
    
    def get_current_checkpoint(self, hours_since_publish: float) -> str:
        """Determine which checkpoint data we should have."""
        if hours_since_publish >= 336:
            return '14d'
        elif hours_since_publish >= 168:
            return '7d'
        elif hours_since_publish >= 72:
            return '3d'
        elif hours_since_publish >= 24:
            return '24h'
        elif hours_since_publish >= 6:
            return '6h'
        else:
            return '1h'
    
    def predict(
        self,
        current_views: int,
        hours_since_publish: float,
        views_history: Dict[str, int],
        likes_history: Optional[Dict[str, int]] = None,
        comments_history: Optional[Dict[str, int]] = None,
        vph_history: Optional[Dict[str, float]] = None,
        subscriber_count: int = 0,
        duration_seconds: int = 0,
    ) -> VelocityReport:
        """
        Predict future views at all remaining milestones.
        
        Args:
            current_views: Current view count
            hours_since_publish: Hours since video was published
            views_history: Dict of checkpoint → views (e.g. {'1h': 1000, '24h': 15000})
            likes_history: Optional dict of checkpoint → likes
            comments_history: Optional dict of checkpoint → comments
            vph_history: Optional dict of checkpoint → views per hour
            subscriber_count: Channel subscriber count
            duration_seconds: Video duration
            
        Returns:
            VelocityReport with predictions for all future milestones
        """
        likes_history = likes_history or {}
        comments_history = comments_history or {}
        vph_history = vph_history or {}
        
        # Determine current checkpoint
        current_cp = self.get_current_checkpoint(hours_since_publish)
        
        # Calculate VPH if not provided
        if not vph_history:
            for cp, hours in self.CHECKPOINT_HOURS.items():
                if cp in views_history:
                    vph_history[cp] = views_history[cp] / hours
        
        # Build features
        features = self._build_features(
            views_history, likes_history, comments_history, vph_history,
            subscriber_count, duration_seconds
        )
        
        # Get future checkpoints
        future_checkpoints = self._get_future_checkpoints(current_cp)
        
        # Make predictions
        predictions = {}
        for target_cp in future_checkpoints:
            model_key = f"{current_cp}_to_{target_cp}"
            
            if model_key in self.models:
                pred = self._predict_single(
                    model_key, features, current_views, 
                    hours_since_publish, target_cp
                )
                if pred:
                    predictions[target_cp] = pred
        
        # Calculate trajectory
        trajectory, momentum = self._analyze_trajectory(
            views_history, vph_history, current_views, hours_since_publish
        )
        
        # Calculate percentile (simplified)
        percentile = self._estimate_percentile(
            current_views, hours_since_publish, subscriber_count
        )
        
        return VelocityReport(
            video_age_hours=hours_since_publish,
            current_checkpoint=current_cp,
            current_views=current_views,
            predictions=predictions,
            trajectory=trajectory,
            momentum_score=momentum,
            percentile=percentile,
        )
    
    def _build_features(
        self,
        views: Dict[str, int],
        likes: Dict[str, int],
        comments: Dict[str, int],
        vph: Dict[str, float],
        subscribers: int,
        duration: int,
    ) -> Dict[str, float]:
        """Build feature dict from input data."""
        features = {}
        
        # Raw metrics
        for cp in ['1h', '6h', '24h', '3d', '7d', '14d']:
            if cp in views:
                features[f'views_{cp}'] = views[cp]
                features[f'log_views_{cp}'] = np.log1p(views[cp])
            if cp in likes:
                features[f'likes_{cp}'] = likes[cp]
            if cp in comments:
                features[f'comments_{cp}'] = comments[cp]
            if cp in vph:
                features[f'vph_{cp}'] = vph[cp]
                features[f'log_vph_{cp}'] = np.log1p(vph[cp])
        
        # Growth ratios
        checkpoints = ['1h', '6h', '24h', '3d', '7d', '14d']
        for i, cp in enumerate(checkpoints[1:], 1):
            prev = checkpoints[i-1]
            if f'views_{cp}' in features and f'views_{prev}' in features:
                features[f'growth_{prev}_{cp}'] = (
                    features[f'views_{cp}'] / max(features[f'views_{prev}'], 1)
                )
            if f'vph_{cp}' in features and f'vph_{prev}' in features:
                features[f'vph_decay_{prev}_{cp}'] = (
                    features[f'vph_{cp}'] / max(features[f'vph_{prev}'], 0.01)
                )
        
        # Overall growth
        if 'views_1h' in features:
            for cp in checkpoints[1:]:
                if f'views_{cp}' in features:
                    features[f'growth_1h_{cp}'] = (
                        features[f'views_{cp}'] / max(features['views_1h'], 1)
                    )
        
        # Engagement rates
        for cp in checkpoints:
            if f'views_{cp}' in features and f'likes_{cp}' in features:
                features[f'like_rate_{cp}'] = (
                    features[f'likes_{cp}'] / max(features[f'views_{cp}'], 1)
                )
            if f'views_{cp}' in features and f'comments_{cp}' in features:
                features[f'comment_rate_{cp}'] = (
                    features[f'comments_{cp}'] / max(features[f'views_{cp}'], 1)
                )
        
        # Channel features
        features['log_subscribers'] = np.log1p(subscribers)
        features['duration_seconds'] = duration
        
        for cp in checkpoints:
            if f'views_{cp}' in features:
                features[f'views_per_sub_{cp}'] = (
                    features[f'views_{cp}'] / max(subscribers, 1)
                )
        
        return features
    
    def _predict_single(
        self,
        model_key: str,
        features: Dict[str, float],
        current_views: int,
        hours_since_publish: float,
        target_cp: str,
    ) -> Optional[MilestonePrediction]:
        """Make a single prediction."""
        model_data = self.models.get(model_key)
        if not model_data:
            return None
        
        model = model_data.get('model')
        feature_cols = model_data.get('feature_cols', [])
        
        if not model or not feature_cols:
            return None
        
        # Build feature vector
        X = np.array([[features.get(col, 0) for col in feature_cols]])
        X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)
        
        # Predict (model outputs log views)
        log_pred = model.predict(X)[0]
        predicted_views = int(np.expm1(log_pred))
        
        # Ensure prediction is at least current views
        predicted_views = max(predicted_views, current_views)
        
        # Calculate growth multiplier
        growth = predicted_views / max(current_views, 1)
        
        # Get confidence from model accuracy
        confidence = self.MODEL_ACCURACY.get(model_key, 0.5)
        
        # Hours until milestone
        target_hours = self.CHECKPOINT_HOURS.get(target_cp, 720)
        hours_until = max(0, target_hours - hours_since_publish)
        
        return MilestonePrediction(
            checkpoint=target_cp,
            predicted_views=predicted_views,
            confidence=confidence,
            hours_until=int(hours_until),
            growth_multiplier=growth,
        )
    
    def _get_future_checkpoints(self, current_cp: str) -> List[str]:
        """Get checkpoints that are in the future."""
        all_checkpoints = ['3d', '7d', '14d', '30d']
        current_idx = ['1h', '6h', '24h', '3d', '7d', '14d', '30d'].index(current_cp)
        
        return [cp for cp in all_checkpoints 
                if self.CHECKPOINT_HOURS[cp] > self.CHECKPOINT_HOURS[current_cp]]
    
    def _analyze_trajectory(
        self,
        views: Dict[str, int],
        vph: Dict[str, float],
        current_views: int,
        hours: float,
    ) -> Tuple[str, float]:
        """Analyze video trajectory based on velocity patterns."""
        
        # Calculate momentum from VPH decay
        decay_values = []
        checkpoints = ['1h', '6h', '24h', '3d', '7d']
        
        for i in range(1, len(checkpoints)):
            prev, curr = checkpoints[i-1], checkpoints[i]
            if prev in vph and curr in vph and vph[prev] > 0:
                decay = vph[curr] / vph[prev]
                decay_values.append(decay)
        
        if decay_values:
            avg_decay = np.mean(decay_values)
            # Higher decay = maintaining momentum better
            momentum = min(100, avg_decay * 100)
        else:
            momentum = 50  # Default
        
        # Classify trajectory
        if momentum >= 70:
            trajectory = "viral"
        elif momentum >= 55:
            trajectory = "strong"
        elif momentum >= 40:
            trajectory = "normal"
        elif momentum >= 25:
            trajectory = "slow"
        else:
            trajectory = "struggling"
        
        return trajectory, momentum
    
    def _estimate_percentile(
        self,
        views: int,
        hours: float,
        subscribers: int,
    ) -> int:
        """Estimate percentile vs similar videos (simplified)."""
        if subscribers <= 0:
            return 50
        
        views_per_sub = views / subscribers
        
        # Rough percentile based on views/subscriber ratio
        if views_per_sub >= 5.0:
            return 99
        elif views_per_sub >= 2.0:
            return 90
        elif views_per_sub >= 1.0:
            return 75
        elif views_per_sub >= 0.5:
            return 50
        elif views_per_sub >= 0.2:
            return 25
        else:
            return 10


def get_predictor() -> VelocityPredictorV2:
    """Get singleton predictor instance."""
    global _predictor
    if '_predictor' not in globals() or _predictor is None:
        _predictor = VelocityPredictorV2()
    return _predictor


# Convenience function
def predict_views(
    current_views: int,
    hours_since_publish: float,
    views_history: Dict[str, int],
    **kwargs
) -> VelocityReport:
    """
    Quick prediction function.
    
    Example:
        report = predict_views(
            current_views=50000,
            hours_since_publish=168,
            views_history={'1h': 1000, '24h': 15000, '7d': 50000}
        )
        print(f"30d prediction: {report.predictions['30d'].predicted_views:,}")
    """
    predictor = get_predictor()
    return predictor.predict(
        current_views=current_views,
        hours_since_publish=hours_since_publish,
        views_history=views_history,
        **kwargs
    )





