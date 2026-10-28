"""
Performance Classifier - Predicts if a video will perform above or below channel average
Best model: 71.8% accuracy, 0.787 AUC
"""

import numpy as np
import pickle
from pathlib import Path
from dataclasses import dataclass
import lightgbm as lgb
from sqlalchemy import and_

from src.database.models import Video, VideoFeatures, Channel
from src.database.connection import get_session
from src.ml.niche_features import NicheFeatureCalculator
from src.features.thumbnail_analyzer import ThumbnailAnalyzer
from src.features.title_analyzer import TitleAnalyzer


MODEL_PATH = Path(__file__).parent / "performance_model.pkl"


@dataclass
class PredictionResult:
    """Result of performance prediction"""
    prediction: str  # "above_average" or "below_average"
    confidence: float  # 0-100%
    probability_above: float  # Raw probability
    
    # Component insights
    thumbnail_factors: dict
    title_factors: dict
    channel_factors: dict
    niche_comparison: dict
    
    # Recommendations
    recommendations: list[str]


class PerformanceClassifier:
    """Predicts if a video will perform above or below channel average"""
    
    def __init__(self):
        self.model = None
        self.thumbnail_analyzer = ThumbnailAnalyzer(enable_face_detection=True)
        self.title_analyzer = TitleAnalyzer()
        self.niche_calculator = None
        
        self.size_map = {'nano': 0, 'micro': 1, 'small': 2, 'medium': 3, 'large': 4, 'mega': 5, 'top': 6}
        self.emotion_map = {'neutral': 0, 'happy': 1, 'sad': 2, 'angry': 3, 'fear': 4, 'surprise': 5, 'disgust': 6}
        self.sentiment_map = {'negative': 0, 'neutral': 1, 'positive': 2}
        self.hook_map = {'listicle': 0, 'how_to': 1, 'question': 2, 'challenge': 3, 'story': 4, 
                        'reveal': 5, 'comparison': 6, 'urgency': 7, 'emotional': 8, 'tutorial': 9, 'none': 10}
    
    def train(self, save: bool = True):
        """Train the model on all available data"""
        print("🧠 Training Performance Classifier...")
        
        with get_session() as session:
            # Initialize niche calculator
            self.niche_calculator = NicheFeatureCalculator(session)
            self.niche_calculator.precompute_all_niches()
            
            # Fetch training data
            results = session.query(
                Video.view_count, Channel.avg_views_per_video, Channel.subscriber_count, 
                Channel.size_tier, Channel.niche_id, Channel.video_count, Channel.engagement_rate, 
                Video.duration_seconds, VideoFeatures.face_count, VideoFeatures.has_face, 
                VideoFeatures.face_area_ratio, VideoFeatures.brightness, VideoFeatures.saturation, 
                VideoFeatures.contrast, VideoFeatures.edge_density, VideoFeatures.composition_score, 
                VideoFeatures.has_text, VideoFeatures.text_word_count, VideoFeatures.face_emotion_primary, 
                VideoFeatures.face_emotion_intensity, VideoFeatures.title_char_length, 
                VideoFeatures.title_word_count, VideoFeatures.title_has_number, VideoFeatures.title_has_question, 
                VideoFeatures.title_caps_ratio, VideoFeatures.title_hook_type, VideoFeatures.title_emotional_score, 
                VideoFeatures.title_sentiment, VideoFeatures.title_trending_score, VideoFeatures.title_specificity_score,
            ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
            ).join(Channel, Video.channel_id == Channel.channel_id
            ).filter(and_(Video.view_count >= 100, VideoFeatures.thumbnail_processed == True,
                          Channel.avg_views_per_video > 0, Channel.niche_id.isnot(None))).all()
            
            print(f"  Training samples: {len(results):,}")
            
            X_list, y_list = [], []
            
            for row in results:
                views, avg_views, subs, size, niche_id, video_count, eng_rate, dur, \
                face_count, has_face, face_area, bright, sat, contrast, edge, comp, has_text, text_words, \
                face_emotion, face_emo_int, title_len, title_words, title_num, title_q, title_caps, \
                hook_type, emo_score, sentiment, trend_score, spec_score = row
                
                if avg_views <= 0: continue
                
                ratio = views / avg_views
                label = 1 if ratio >= 1.0 else 0
                
                vec = self._build_feature_vector(
                    face_count, has_face, face_area, bright, sat, contrast, edge, comp,
                    has_text, text_words, face_emotion, face_emo_int,
                    title_len, title_words, title_num, title_q, title_caps,
                    hook_type, emo_score, sentiment, trend_score, spec_score,
                    subs, size, video_count, eng_rate, dur, niche_id
                )
                
                X_list.append(vec)
                y_list.append(label)
            
            X = np.array(X_list)
            y = np.array(y_list)
            
            # Balance dataset
            pos_idx = np.where(y == 1)[0]
            neg_idx = np.where(y == 0)[0]
            np.random.seed(42)
            neg_idx = np.random.choice(neg_idx, size=len(pos_idx), replace=False)
            balanced_idx = np.concatenate([pos_idx, neg_idx])
            X_bal = X[balanced_idx]
            y_bal = y[balanced_idx]
            
            print(f"  Balanced samples: {len(y_bal):,}")
            
            # Train LightGBM
            from sklearn.model_selection import train_test_split
            X_train, X_val, y_train, y_val = train_test_split(
                X_bal, y_bal, test_size=0.2, random_state=42, stratify=y_bal
            )
            
            train_data = lgb.Dataset(X_train, label=y_train)
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
            
            params = {
                'objective': 'binary', 'metric': 'auc', 'num_leaves': 127, 
                'learning_rate': 0.03, 'feature_fraction': 0.7, 'bagging_fraction': 0.8, 
                'bagging_freq': 5, 'min_data_in_leaf': 30, 'lambda_l1': 0.1, 
                'lambda_l2': 0.1, 'verbose': -1
            }
            
            self.model = lgb.train(
                params, train_data, 1000, valid_sets=[val_data],
                callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)]
            )
            
            # Evaluate
            from sklearn.metrics import accuracy_score, roc_auc_score
            pred = self.model.predict(X_val)
            acc = accuracy_score(y_val, (pred > 0.5).astype(int))
            auc = roc_auc_score(y_val, pred)
            
            print(f"  ✅ Accuracy: {acc*100:.1f}%")
            print(f"  ✅ AUC-ROC: {auc:.3f}")
            
            if save:
                self.save()
                print(f"  💾 Model saved to {MODEL_PATH}")
    
    def _build_feature_vector(self, face_count, has_face, face_area, bright, sat, contrast, 
                              edge, comp, has_text, text_words, face_emotion, face_emo_int,
                              title_len, title_words, title_num, title_q, title_caps,
                              hook_type, emo_score, sentiment, trend_score, spec_score,
                              subs, size, video_count, eng_rate, dur, niche_id):
        """Build feature vector for prediction"""
        
        vec = [
            face_count or 0, 1 if has_face else 0, face_area or 0, 
            bright or 0.5, sat or 0.5, contrast or 0.5, edge or 0.5, comp or 0.5,
            1 if has_text else 0, text_words or 0,
            self.emotion_map.get(face_emotion, 0), face_emo_int or 0,
            title_len or 50, title_words or 8, 1 if title_num else 0, 1 if title_q else 0,
            title_caps or 0, self.hook_map.get(hook_type, 10), emo_score or 0,
            self.sentiment_map.get(sentiment, 1), trend_score or 0, spec_score or 0,
            np.log1p(subs or 10000), self.size_map.get(size, 2), np.log1p(video_count or 100),
            eng_rate or 0.05, np.log1p(dur or 300), niche_id or 0,
        ]
        
        # Niche-relative features
        if self.niche_calculator and niche_id:
            features = {
                'face_count': face_count or 0, 'has_face': has_face, 
                'face_area_ratio': face_area or 0, 'brightness': bright or 0.5,
                'saturation': sat or 0.5, 'contrast': contrast or 0.5,
                'edge_density': edge or 0.5, 'composition_score': comp or 0.5,
                'has_text': has_text, 'text_word_count': text_words or 0,
                'title_char_length': title_len or 50, 'title_word_count': title_words or 8,
            }
            niche_rel = self.niche_calculator.calculate_relative_features(niche_id, features)
            
            if niche_rel:
                vec.extend([
                    niche_rel.face_vs_niche, niche_rel.brightness_vs_niche,
                    niche_rel.saturation_vs_niche, niche_rel.contrast_vs_niche,
                    niche_rel.edge_vs_niche, niche_rel.composition_vs_niche,
                    niche_rel.title_length_vs_niche, niche_rel.similarity_to_top,
                ])
            else:
                vec.extend([0] * 8)
        else:
            vec.extend([0] * 8)
        
        # Feature interactions
        vec.extend([
            (face_count or 0) * (bright or 0.5),
            (1 if has_face else 0) * (1 if has_text else 0),
            (title_len or 50) * (emo_score or 0),
            np.log1p(subs or 10000) * (eng_rate or 0.05),
        ])
        
        return vec
    
    def save(self):
        """Save model to disk"""
        with open(MODEL_PATH, 'wb') as f:
            pickle.dump(self.model, f)
    
    def load(self):
        """Load model from disk"""
        if MODEL_PATH.exists():
            with open(MODEL_PATH, 'rb') as f:
                self.model = pickle.load(f)
            return True
        return False
    
    def predict(self, thumbnail_url: str, title: str, channel_id: str) -> PredictionResult:
        """
        Predict if a video will perform above or below channel average
        
        Args:
            thumbnail_url: URL to thumbnail image
            title: Video title
            channel_id: YouTube channel ID
        """
        if self.model is None:
            if not self.load():
                raise ValueError("Model not trained. Run train() first.")
        
        with get_session() as session:
            # Initialize niche calculator
            if self.niche_calculator is None:
                self.niche_calculator = NicheFeatureCalculator(session)
                self.niche_calculator.precompute_all_niches()
            
            # Get channel info
            channel = session.query(Channel).filter(Channel.channel_id == channel_id).first()
            if not channel:
                raise ValueError(f"Channel {channel_id} not found in database")
            
            # Analyze thumbnail
            thumb_features = self.thumbnail_analyzer.analyze_from_url_sync(thumbnail_url)
            if thumb_features is None:
                # Fallback to empty features if download fails
                thumb_features = self.thumbnail_analyzer._empty_features()
            
            # Analyze title
            title_features = self.title_analyzer.analyze(title)
            
            # Build feature vector
            vec = self._build_feature_vector(
                thumb_features.face_count, thumb_features.has_face, thumb_features.face_area_ratio,
                thumb_features.brightness, thumb_features.saturation, thumb_features.contrast,
                thumb_features.edge_density, thumb_features.composition_score,
                thumb_features.has_text, thumb_features.text_word_count,
                None, None,  # face emotion (not from URL analysis)
                title_features.char_length, title_features.word_count,
                title_features.has_number, title_features.has_question,
                title_features.caps_ratio, title_features.hook_type,
                title_features.emotional_score, title_features.sentiment,
                title_features.trending_score, title_features.specificity_score,
                channel.subscriber_count, channel.size_tier, channel.video_count,
                channel.engagement_rate, 600,  # assume 10 min duration
                channel.niche_id
            )
            
            # Predict
            prob = self.model.predict([vec])[0]
            prediction = "above_average" if prob > 0.5 else "below_average"
            confidence = abs(prob - 0.5) * 200  # 0-100 scale
            
            # Generate insights
            niche_rel = None
            if channel.niche_id:
                features = {
                    'face_count': thumb_features.face_count or 0, 
                    'has_face': thumb_features.has_face,
                    'face_area_ratio': thumb_features.face_area_ratio or 0, 
                    'brightness': thumb_features.brightness,
                    'saturation': thumb_features.saturation, 
                    'contrast': thumb_features.contrast,
                    'edge_density': thumb_features.edge_density, 
                    'composition_score': thumb_features.composition_score,
                    'has_text': thumb_features.has_text, 
                    'text_word_count': thumb_features.text_word_count or 0,
                    'title_char_length': title_features.char_length, 
                    'title_word_count': title_features.word_count,
                }
                niche_rel = self.niche_calculator.calculate_relative_features(channel.niche_id, features)
            
            # Build recommendations
            recommendations = []
            
            if niche_rel:
                if niche_rel.brightness_vs_niche < -0.2:
                    recommendations.append("📸 Thumbnail is darker than typical for your niche - consider brightening")
                if niche_rel.brightness_vs_niche > 0.3:
                    recommendations.append("📸 Thumbnail is brighter than typical - this can help stand out")
                if not thumb_features.has_face and niche_rel.face_vs_niche < -0.3:
                    recommendations.append("👤 Most videos in your niche use faces - consider adding one")
                if niche_rel.similarity_to_top > 0.7:
                    recommendations.append("⭐ Thumbnail style matches top performers in your niche!")
                if title_features.char_length > 70:
                    recommendations.append("✂️ Title is long - may get truncated in search results")
                if not title_features.has_number:
                    recommendations.append("🔢 Consider adding a number - they tend to get more clicks")
                if title_features.hook_type == 'none':
                    recommendations.append("🎣 No clear hook detected - try adding a question or curiosity gap")
            
            if not recommendations:
                if prediction == "above_average":
                    recommendations.append("✅ Looking good! This combination should perform well.")
                else:
                    recommendations.append("💡 Try tweaking the thumbnail brightness or adding a stronger hook to the title")
            
            return PredictionResult(
                prediction=prediction,
                confidence=confidence,
                probability_above=prob,
                thumbnail_factors={
                    'has_face': thumb_features.has_face,
                    'brightness': round(thumb_features.brightness, 2),
                    'saturation': round(thumb_features.saturation, 2),
                    'has_text': thumb_features.has_text,
                    'edge_density': round(thumb_features.edge_density, 2),
                },
                title_factors={
                    'length': title_features.char_length,
                    'hook_type': title_features.hook_type,
                    'has_number': title_features.has_number,
                    'emotional_score': round(title_features.emotional_score, 2),
                },
                channel_factors={
                    'subscribers': channel.subscriber_count,
                    'size_tier': channel.size_tier,
                    'niche_id': channel.niche_id,
                },
                niche_comparison={
                    'brightness_vs_niche': round(niche_rel.brightness_vs_niche, 2) if niche_rel else None,
                    'face_vs_niche': round(niche_rel.face_vs_niche, 2) if niche_rel else None,
                    'similarity_to_top': round(niche_rel.similarity_to_top, 2) if niche_rel else None,
                },
                recommendations=recommendations,
            )


def train_and_save():
    """Convenience function to train and save model"""
    classifier = PerformanceClassifier()
    classifier.train(save=True)
    return classifier

