"""
SHAP-based explanation system for video predictions.

Provides human-readable explanations for why a video is predicted
to be a hit or miss, with actionable recommendations.
"""

import pickle
import numpy as np
import pandas as pd
import shap
from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class FeatureExplanation:
    """Explanation for a single feature's impact."""
    feature_name: str
    display_name: str
    shap_value: float
    feature_value: float
    direction: str  # "helping" or "hurting"
    recommendation: Optional[str] = None


@dataclass
class PredictionExplanation:
    """Complete explanation for a prediction."""
    video_title: str
    prediction: str  # "HIT" or "MISS"
    confidence: float
    actual_performance: Optional[float]
    
    top_helping: List[FeatureExplanation]
    top_hurting: List[FeatureExplanation]
    
    recommendations: List[str]
    title_embedding_impact: float  # Combined impact of title embeddings


class VideoExplainer:
    """Explains video predictions using SHAP values."""
    
    # Human-readable feature names
    FEATURE_LABELS = {
        'title_len': '📝 Title length',
        'title_words': '📝 Title word count',
        'has_number': '🔢 Number in title',
        'has_question': '❓ Question in title',
        'has_exclamation': '❗ Exclamation mark',
        'emotional': '😮 Emotional intensity',
        'brightness': '☀️ Thumbnail brightness',
        'saturation': '🎨 Thumbnail saturation',
        'has_face': '👤 Face in thumbnail',
        'face_count': '👥 Number of faces',
        'has_text': '📰 Text overlay',
        'text_words': '📰 Text word count',
        'hook_face_sec': '⏱️ Time to show face',
        'hook_cuts': '🎬 Cuts in first 10s',
        'hook_motion': '🏃 Motion/energy in hook',
        'wpm': '🗣️ Speaking pace',
        'audio_energy': '🔊 Audio energy level',
        'audio_variance': '📈 Audio dynamics',
        'has_music': '🎵 Music intro',
        'face_time_ratio': '👤 Face screen time',
        'total_scenes': '🎬 Scene variety',
        'cta_count': '📢 Calls to action',
        'question_count': '❓ Questions asked',
        'log_subs': '📊 Channel size',
        'log_channel_avg': '📊 Channel baseline',
        'age_days': '📅 Video age',
    }
    
    # Recommendations based on feature values
    RECOMMENDATIONS = {
        'has_face': {
            'low': "Add a face to your thumbnail - faces increase CTR",
            'high': None
        },
        'brightness': {
            'low': "Increase thumbnail brightness for better visibility",
            'high': "Consider slightly darker tones for contrast"
        },
        'saturation': {
            'low': "Boost color saturation to stand out in feeds",
            'high': None
        },
        'title_len': {
            'low': "Expand your title with more context",
            'high': "Shorten your title for mobile visibility"
        },
        'hook_face_sec': {
            'low': None,
            'high': "Show your face earlier in the video (under 2 seconds)"
        },
        'hook_cuts': {
            'low': "Add more cuts in the first 10 seconds to boost engagement",
            'high': None
        },
        'has_music': {
            'low': "Consider adding a music intro for polish",
            'high': None
        },
        'wpm': {
            'low': "Pick up the speaking pace slightly",
            'high': "Slow down your delivery for clarity"
        },
        'emotional': {
            'low': "Add more emotional language to your title",
            'high': None
        },
    }
    
    def __init__(self, model_path: str = "data/models/content_predictor.pkl"):
        """Load the model and create SHAP explainer."""
        with open(model_path, 'rb') as f:
            self.model_data = pickle.load(f)
        
        self.model = self.model_data['model']
        self.feature_cols = self.model_data['feature_cols']
        self.threshold = self.model_data['threshold']
        
        # Create SHAP explainer
        self.explainer = shap.TreeExplainer(self.model)
    
    def explain(
        self,
        features: Dict[str, float],
        title: str = "",
        actual_performance: Optional[float] = None
    ) -> PredictionExplanation:
        """
        Generate explanation for a prediction.
        
        Args:
            features: Dictionary of feature values
            title: Video title (for display)
            actual_performance: Actual performance ratio (if known)
            
        Returns:
            PredictionExplanation with details and recommendations
        """
        # Create feature vector
        X = np.array([[features.get(col, 0) for col in self.feature_cols]])
        X_df = pd.DataFrame(X, columns=self.feature_cols)
        
        # Get prediction
        prob = self.model.predict_proba(X)[0][1]
        prediction = "HIT" if prob > 0.5 else "MISS"
        
        # Get SHAP values
        shap_values = self.explainer.shap_values(X_df)
        if isinstance(shap_values, list):
            sv = shap_values[1][0]  # Class 1 (hit) SHAP values
        else:
            sv = shap_values[0]
        
        # Separate embedding vs non-embedding features
        non_emb_features = []
        emb_impact = 0.0
        
        for col, shap_val in zip(self.feature_cols, sv):
            if col.startswith('emb_'):
                emb_impact += shap_val
            else:
                non_emb_features.append((col, shap_val, features.get(col, 0)))
        
        # Sort by absolute impact (excluding age_days which can dominate)
        non_emb_features.sort(key=lambda x: abs(x[1]) if x[0] != 'age_days' else 0, reverse=True)
        
        # Build explanations
        top_helping = []
        top_hurting = []
        recommendations = []
        
        for col, shap_val, feat_val in non_emb_features:
            if col in ['age_days', 'log_subs', 'log_channel_avg']:
                continue  # Skip context features for recommendations
            
            if abs(shap_val) < 0.01:
                continue
            
            display_name = self.FEATURE_LABELS.get(col, col)
            direction = "helping" if shap_val > 0 else "hurting"
            
            # Generate recommendation
            rec = None
            if col in self.RECOMMENDATIONS:
                rec_dict = self.RECOMMENDATIONS[col]
                if shap_val < 0 and 'low' in rec_dict and feat_val < 0.5:
                    rec = rec_dict['low']
                elif shap_val < 0 and 'high' in rec_dict and feat_val > 0.5:
                    rec = rec_dict['high']
            
            explanation = FeatureExplanation(
                feature_name=col,
                display_name=display_name,
                shap_value=shap_val,
                feature_value=feat_val,
                direction=direction,
                recommendation=rec
            )
            
            if shap_val > 0.01:
                top_helping.append(explanation)
            elif shap_val < -0.01:
                top_hurting.append(explanation)
                if rec:
                    recommendations.append(rec)
        
        # Add title embedding impact as a single item
        if abs(emb_impact) > 0.1:
            emb_direction = "helping" if emb_impact > 0 else "hurting"
            emb_explanation = FeatureExplanation(
                feature_name="title_embedding",
                display_name="✍️ Title wording/style",
                shap_value=emb_impact,
                feature_value=0,
                direction=emb_direction,
                recommendation="Try different title phrasing" if emb_impact < -0.1 else None
            )
            if emb_impact > 0:
                top_helping.insert(0, emb_explanation)
            else:
                top_hurting.insert(0, emb_explanation)
                if emb_explanation.recommendation:
                    recommendations.insert(0, emb_explanation.recommendation)
        
        return PredictionExplanation(
            video_title=title,
            prediction=prediction,
            confidence=prob,
            actual_performance=actual_performance,
            top_helping=top_helping[:5],
            top_hurting=top_hurting[:5],
            recommendations=recommendations[:5],
            title_embedding_impact=emb_impact
        )
    
    def format_explanation(self, explanation: PredictionExplanation) -> str:
        """Format explanation as a string for display."""
        lines = []
        
        icon = "🔥" if explanation.prediction == "HIT" else "💤"
        lines.append(f"{icon} {explanation.video_title[:55]}")
        lines.append(f"   Prediction: {explanation.prediction} ({explanation.confidence:.0%} confidence)")
        
        if explanation.actual_performance:
            lines.append(f"   Actual: {explanation.actual_performance:.1f}x performance")
        
        lines.append("")
        lines.append("   📊 WHY THIS PREDICTION:")
        
        if explanation.top_helping:
            lines.append("   ✅ Helping factors:")
            for feat in explanation.top_helping[:3]:
                bar = "█" * min(int(abs(feat.shap_value) * 10), 20)
                lines.append(f"      {feat.display_name}: {bar} (+{feat.shap_value:.2f})")
        
        if explanation.top_hurting:
            lines.append("   ⚠️ Hurting factors:")
            for feat in explanation.top_hurting[:3]:
                bar = "█" * min(int(abs(feat.shap_value) * 10), 20)
                lines.append(f"      {feat.display_name}: {bar} ({feat.shap_value:.2f})")
        
        if explanation.recommendations:
            lines.append("")
            lines.append("   💡 RECOMMENDATIONS:")
            for rec in explanation.recommendations[:3]:
                lines.append(f"      • {rec}")
        
        return "\n".join(lines)


def explain_video(video_id: str) -> PredictionExplanation:
    """
    Convenience function to explain a video by ID.
    
    Args:
        video_id: YouTube video ID
        
    Returns:
        PredictionExplanation
    """
    from src.database.connection import get_session
    from src.database.models import Video, Channel, VideoFeatures, VideoContentAnalysis
    from sentence_transformers import SentenceTransformer
    
    explainer = VideoExplainer()
    st_model = SentenceTransformer('all-MiniLM-L6-v2')
    
    with get_session() as session:
        result = session.query(
            Video.title, Video.view_count, Video.published_at,
            Channel.subscriber_count, Channel.avg_views_per_video,
            VideoFeatures.title_char_length, VideoFeatures.title_word_count,
            VideoFeatures.title_has_number, VideoFeatures.title_has_question,
            VideoFeatures.title_has_exclamation, VideoFeatures.title_emotional_score,
            VideoFeatures.brightness, VideoFeatures.saturation,
            VideoFeatures.has_face, VideoFeatures.face_count,
            VideoFeatures.has_text, VideoFeatures.text_word_count,
            VideoContentAnalysis.hook_face_appears_seconds,
            VideoContentAnalysis.hook_scene_changes_count,
            VideoContentAnalysis.hook_avg_motion, VideoContentAnalysis.words_per_minute,
            VideoContentAnalysis.audio_energy_mean, VideoContentAnalysis.audio_energy_variance,
            VideoContentAnalysis.has_music_intro, VideoContentAnalysis.face_screen_time_ratio,
            VideoContentAnalysis.total_scene_changes,
            VideoContentAnalysis.call_to_action_count, VideoContentAnalysis.question_count,
        ).join(Channel, Video.channel_id == Channel.channel_id
        ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).join(VideoContentAnalysis, Video.video_id == VideoContentAnalysis.video_id
        ).filter(Video.video_id == video_id).first()
        
        if not result:
            raise ValueError(f"Video {video_id} not found or missing features")
        
        title, views, published_at, subs, channel_avg = result[:5]
        
        # Calculate age
        now = pd.Timestamp.now(tz=None)
        pub = pd.to_datetime(published_at)
        if pub.tzinfo:
            pub = pub.tz_localize(None)
        age_days = max((now - pub).days, 1)
        
        # Calculate performance
        age_adjusted = (views / age_days) / (channel_avg / 30) if channel_avg > 0 else 1
        
        # Build features
        features = {
            'title_len': result[5] or 0, 'title_words': result[6] or 0,
            'has_number': int(result[7] or 0), 'has_question': int(result[8] or 0),
            'has_exclamation': int(result[9] or 0), 'emotional': result[10] or 0,
            'brightness': result[11] or 0, 'saturation': result[12] or 0,
            'has_face': int(result[13] or 0), 'face_count': result[14] or 0,
            'has_text': int(result[15] or 0), 'text_words': result[16] or 0,
            'hook_face_sec': result[17] or 0, 'hook_cuts': result[18] or 0,
            'hook_motion': result[19] or 0, 'wpm': result[20] or 0,
            'audio_energy': result[21] or 0, 'audio_variance': result[22] or 0,
            'has_music': int(result[23] or 0), 'face_time_ratio': result[24] or 0,
            'total_scenes': result[25] or 0, 'cta_count': result[26] or 0,
            'question_count': result[27] or 0,
            'log_subs': np.log1p(subs), 'log_channel_avg': np.log1p(channel_avg),
            'age_days': age_days,
        }
        
        # Add title embeddings
        embedding = st_model.encode([title])[0]
        for i, val in enumerate(embedding):
            features[f'emb_{i}'] = val
        
        return explainer.explain(features, title, age_adjusted)

