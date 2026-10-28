"""
Improved Video Performance Predictor v2
- Uses class weights (not undersampling)
- Includes title embeddings (384-dim)
- SHAP explanations
"""

import numpy as np
import joblib
import os
from dataclasses import dataclass
from typing import List, Tuple
from datetime import datetime
import logging

import lightgbm as lgb
from sentence_transformers import SentenceTransformer
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score
import shap

from sqlalchemy import and_
from src.database.models import Video, VideoFeatures, Channel
from src.database.connection import get_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_DIR = "data/models"
MODEL_PATH = os.path.join(MODEL_DIR, "predictor_v2.pkl")
EMBEDDER_NAME = "all-MiniLM-L6-v2"


@dataclass
class PredictionResult:
    """Result of a video performance prediction."""
    prediction: str  # "ABOVE AVERAGE" or "BELOW AVERAGE"
    probability: float  # 0-1
    confidence: float  # 0-100%
    top_positive_factors: List[Tuple[str, float]]
    top_negative_factors: List[Tuple[str, float]]
    recommendations: List[str]


class ImprovedPredictor:
    """Video performance predictor with improved accuracy."""
    
    FEATURE_NAMES = [
        'has_face', 'brightness', 'saturation', 'has_text',
        'title_length', 'title_words', 'has_number', 'has_question', 
        'emotional_score', 'log_subscribers', 'size_tier', 
        'channel_hit_rate', 'log_avg_views'
    ] + [f'title_emb_{i}' for i in range(384)]
    
    HUMAN_NAMES = {
        'has_face': 'Face in thumbnail',
        'brightness': 'Thumbnail brightness',
        'saturation': 'Color saturation',
        'has_text': 'Text in thumbnail',
        'title_length': 'Title length',
        'title_words': 'Title word count',
        'has_number': 'Number in title',
        'has_question': 'Question in title',
        'emotional_score': 'Emotional words',
        'log_subscribers': 'Channel size',
        'size_tier': 'Channel tier',
        'channel_hit_rate': 'Channel success rate',
        'log_avg_views': 'Channel avg views',
    }
    
    SIZE_MAP = {'nano': 0, 'micro': 1, 'small': 2, 'medium': 3, 'large': 4, 'mega': 5, 'top': 6}
    
    def __init__(self):
        self.model = None
        self.explainer = None
        self.embedder = None
        self.hit_rates = {}
        
    def load_or_train(self):
        """Load existing model or train a new one."""
        os.makedirs(MODEL_DIR, exist_ok=True)
        
        if os.path.exists(MODEL_PATH):
            logger.info("Loading existing model...")
            data = joblib.load(MODEL_PATH)
            self.model = data['model']
            self.explainer = data['explainer']
            self.hit_rates = data['hit_rates']
            logger.info("Model loaded successfully")
        else:
            logger.info("Training new model...")
            self.train()
            
        # Always load embedder
        if self.embedder is None:
            logger.info(f"Loading embedder: {EMBEDDER_NAME}")
            self.embedder = SentenceTransformer(EMBEDDER_NAME)
    
    def train(self):
        """Train the improved model."""
        logger.info("Fetching training data...")
        
        with get_session() as session:
            results = session.query(
                Video.view_count, Video.channel_id, Video.title,
                Channel.avg_views_per_video, Channel.subscriber_count, Channel.size_tier,
                VideoFeatures.has_face, VideoFeatures.brightness, VideoFeatures.saturation,
                VideoFeatures.has_text, VideoFeatures.title_char_length,
                VideoFeatures.title_word_count, VideoFeatures.title_has_number,
                VideoFeatures.title_has_question, VideoFeatures.title_emotional_score,
                Video.published_at,  # For age normalization
            ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
            ).join(Channel, Video.channel_id == Channel.channel_id
            ).filter(and_(
                Video.view_count >= 100, 
                Channel.avg_views_per_video > 0,
                Video.title.isnot(None)
            )).limit(50000).all()
        
        logger.info(f"Got {len(results):,} samples")
        
        # Calculate hit rates
        channel_perfs = {}
        for r in results:
            cid = r[1]
            if cid not in channel_perfs:
                channel_perfs[cid] = {'total': 0, 'hits': 0}
            channel_perfs[cid]['total'] += 1
            if r[0] >= r[3]:
                channel_perfs[cid]['hits'] += 1
        self.hit_rates = {cid: p['hits']/max(p['total'],1) for cid, p in channel_perfs.items()}
        
        # Load embedder
        logger.info(f"Loading embedder: {EMBEDDER_NAME}")
        self.embedder = SentenceTransformer(EMBEDDER_NAME)
        
        # Build features - two-pass approach for percentile-based labeling
        
        # First pass: collect all data and calculate ratios
        processed_data = []
        all_ratios = []
        
        now = datetime.utcnow()
        for r in results:
            views, cid, title, avg, subs, size, face, bright, sat, text, \
            title_len, title_words, title_num, title_q, emo, published_at = r
            
            if avg <= 0 or not title or not published_at: 
                continue
            
            # Calculate video age in days
            pub = published_at.replace(tzinfo=None) if published_at.tzinfo else published_at
            age_days = max(1, (now - pub).days)
            
            # Skip videos less than 14 days old (performance still volatile)
            if age_days < 14:
                continue
            
            # Age-adjusted performance
            views_per_day = views / age_days
            expected_per_day = avg / 30
            ratio = views_per_day / max(expected_per_day, 1)
            
            base_vec = [
                1 if face else 0, 
                bright or 0.5, 
                sat or 0.5, 
                1 if text else 0,
                title_len or 50, 
                title_words or 8, 
                1 if title_num else 0,
                1 if title_q else 0, 
                emo or 0,
                np.log1p(subs or 10000), 
                self.SIZE_MAP.get(size, 2),
                self.hit_rates.get(cid, 0.5), 
                np.log1p(avg)
            ]
            
            processed_data.append((title, base_vec, ratio))
            all_ratios.append(ratio)
        
        # Calculate threshold for TOP 30% (more balanced classes)
        threshold = np.percentile(all_ratios, 70)  # Top 30%
        logger.info(f"Using top 30% threshold: {threshold:.3f}x expected")
        
        # Second pass: create labels
        titles = []
        X_base = []
        y = []
        
        for title, base_vec, ratio in processed_data:
            label = 1 if ratio >= threshold else 0  # Top 30% = positive
            titles.append(title)
            X_base.append(base_vec)
            y.append(label)
        
        X_base = np.array(X_base)
        y = np.array(y)
        
        logger.info(f"Samples: {len(y):,}, Positive: {sum(y):,} ({sum(y)/len(y)*100:.1f}%)")
        
        # Generate title embeddings
        logger.info("Generating title embeddings...")
        title_embeddings = self.embedder.encode(titles, show_progress_bar=True, batch_size=64)
        
        # Combine features
        X = np.hstack([X_base, title_embeddings])
        logger.info(f"Combined features: {X.shape[1]} dimensions")
        
        # Split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )
        
        # Calculate class weights
        pos_weight = sum(y_train) / len(y_train)
        neg_weight = 1 - pos_weight
        sample_weights = np.where(y_train == 1, 1/pos_weight, 1/neg_weight)
        
        # Train model
        logger.info("Training LightGBM with class weights...")
        params = {
            'objective': 'binary', 
            'metric': 'auc', 
            'num_leaves': 63, 
            'learning_rate': 0.05, 
            'verbose': -1, 
            'n_jobs': -1,
            'n_estimators': 300
        }
        
        self.model = lgb.LGBMClassifier(**params)
        self.model.fit(X_train, y_train, sample_weight=sample_weights)
        
        # Evaluate with proper metrics for imbalanced data
        from sklearn.metrics import (
            balanced_accuracy_score, f1_score, precision_score, 
            recall_score
        )
        
        probs = self.model.predict_proba(X_test)[:, 1]
        preds = (probs > 0.5).astype(int)
        
        # Standard metrics
        acc = accuracy_score(y_test, preds)
        auc = roc_auc_score(y_test, probs)
        
        # Better metrics for imbalanced data
        balanced_acc = balanced_accuracy_score(y_test, preds)
        f1 = f1_score(y_test, preds)
        precision = precision_score(y_test, preds, zero_division=0)
        recall = recall_score(y_test, preds)
        
        logger.info("")
        logger.info("📊 MODEL EVALUATION (Test Set)")
        logger.info("="*50)
        logger.info(f"⚠️  Raw Accuracy: {acc*100:.1f}% (misleading due to imbalance)")
        logger.info("")
        logger.info("✅ REAL METRICS:")
        logger.info(f"   AUC-ROC:          {auc:.3f} (0.5=random, 1.0=perfect)")
        logger.info(f"   Balanced Accuracy: {balanced_acc*100:.1f}%")
        logger.info(f"   F1-Score:          {f1:.3f}")
        logger.info(f"   Precision:         {precision*100:.1f}% (when I say ABOVE, I'm right this often)")
        logger.info(f"   Recall:            {recall*100:.1f}% (of all ABOVE videos, I catch this many)")
        logger.info("")
        
        # Store metrics
        self.metrics = {
            'accuracy': acc, 'balanced_accuracy': balanced_acc,
            'auc': auc, 'f1': f1, 'precision': precision, 'recall': recall
        }
        
        # Create SHAP explainer
        logger.info("Creating SHAP explainer...")
        self.explainer = shap.TreeExplainer(self.model)
        
        # Save
        joblib.dump({
            'model': self.model,
            'explainer': self.explainer,
            'hit_rates': self.hit_rates
        }, MODEL_PATH)
        logger.info(f"Model saved to {MODEL_PATH}")
    
    def predict(self, title: str, thumbnail_features: dict, 
                channel_subscribers: int = 10000,
                channel_size_tier: str = "small",
                channel_hit_rate: float = 0.5,
                channel_avg_views: float = 5000) -> PredictionResult:
        """
        Predict video performance.
        
        Args:
            title: Video title
            thumbnail_features: Dict with has_face, brightness, saturation, has_text
            channel_subscribers: Channel subscriber count
            channel_size_tier: nano/micro/small/medium/large/mega/top
            channel_hit_rate: Historical success rate (0-1)
            channel_avg_views: Channel's average views per video
        
        Returns:
            PredictionResult with prediction and explanations
        """
        if self.model is None:
            self.load_or_train()
        
        # Build base features
        base_vec = [
            1 if thumbnail_features.get('has_face', False) else 0,
            thumbnail_features.get('brightness', 0.5),
            thumbnail_features.get('saturation', 0.5),
            1 if thumbnail_features.get('has_text', False) else 0,
            len(title),
            len(title.split()),
            1 if any(c.isdigit() for c in title) else 0,
            1 if '?' in title else 0,
            thumbnail_features.get('emotional_score', 0),
            np.log1p(channel_subscribers),
            self.SIZE_MAP.get(channel_size_tier, 2),
            channel_hit_rate,
            np.log1p(channel_avg_views)
        ]
        
        # Get title embedding
        title_embedding = self.embedder.encode([title])[0]
        
        # Combine
        X = np.array([base_vec + list(title_embedding)])
        
        # Predict
        prob = self.model.predict_proba(X)[0, 1]
        prediction = "ABOVE AVERAGE" if prob >= 0.5 else "BELOW AVERAGE"
        confidence = abs(prob - 0.5) * 200
        
        # SHAP explanation
        shap_values = self.explainer.shap_values(X)[0]
        
        # Get top factors (only base features, not embeddings)
        base_impacts = list(zip(self.FEATURE_NAMES[:13], shap_values[:13], X[0, :13]))
        
        positive = [(self.HUMAN_NAMES.get(f, f), s, v) for f, s, v in base_impacts if s > 0.01]
        negative = [(self.HUMAN_NAMES.get(f, f), s, v) for f, s, v in base_impacts if s < -0.01]
        
        positive.sort(key=lambda x: -x[1])
        negative.sort(key=lambda x: x[1])
        
        # Generate recommendations
        recommendations = []
        for name, shap_val, value in negative[:5]:
            if 'Face' in name and value < 0.5:
                recommendations.append(f"🔴 Add a FACE to thumbnail (+{abs(shap_val)*100:.0f}% boost)")
            elif 'brightness' in name.lower() and value < 0.4:
                recommendations.append(f"🟡 Make thumbnail BRIGHTER (+{abs(shap_val)*100:.0f}% boost)")
            elif 'Text' in name and value < 0.5:
                recommendations.append(f"🟡 Add TEXT to thumbnail (+{abs(shap_val)*100:.0f}% boost)")
            elif 'Number' in name and value < 0.5:
                recommendations.append(f"🟡 Add a NUMBER to title (+{abs(shap_val)*100:.0f}% boost)")
            elif 'Question' in name and value < 0.5:
                recommendations.append(f"🟡 Try a QUESTION title (+{abs(shap_val)*100:.0f}% boost)")
            elif 'Emotional' in name and value < 0.3:
                recommendations.append(f"🟡 Add EMOTION words to title (+{abs(shap_val)*100:.0f}% boost)")
            elif 'success rate' in name.lower():
                recommendations.append("⚠️ Channel history is hurting - focus on quality")
        
        return PredictionResult(
            prediction=prediction,
            probability=prob,
            confidence=confidence,
            top_positive_factors=[(n, s) for n, s, v in positive[:5]],
            top_negative_factors=[(n, s) for n, s, v in negative[:5]],
            recommendations=recommendations[:4]
        )


def demo():
    """Run demo predictions on sample videos."""
    predictor = ImprovedPredictor()
    predictor.load_or_train()
    
    print("\n" + "="*70)
    print("🎯 IMPROVED PREDICTOR v2 - DEMO")
    print("="*70)
    
    # Test cases
    test_cases = [
        {
            "title": "10 SECRETS The Government Doesn't Want You To Know",
            "thumbnail": {"has_face": True, "brightness": 0.7, "saturation": 0.8, "has_text": True},
            "channel": {"subscribers": 500000, "size_tier": "large", "hit_rate": 0.6, "avg_views": 100000}
        },
        {
            "title": "My morning routine vlog",
            "thumbnail": {"has_face": False, "brightness": 0.4, "saturation": 0.3, "has_text": False},
            "channel": {"subscribers": 1000, "size_tier": "nano", "hit_rate": 0.2, "avg_views": 200}
        },
        {
            "title": "How I Made $50,000 in One Month (Step by Step)",
            "thumbnail": {"has_face": True, "brightness": 0.8, "saturation": 0.7, "has_text": True},
            "channel": {"subscribers": 100000, "size_tier": "medium", "hit_rate": 0.55, "avg_views": 30000}
        },
        {
            "title": "gaming stream",
            "thumbnail": {"has_face": False, "brightness": 0.3, "saturation": 0.5, "has_text": False},
            "channel": {"subscribers": 500, "size_tier": "nano", "hit_rate": 0.1, "avg_views": 50}
        },
        {
            "title": "Why Everyone Is Wrong About AI (And What's Really Coming)",
            "thumbnail": {"has_face": True, "brightness": 0.6, "saturation": 0.6, "has_text": True},
            "channel": {"subscribers": 2000000, "size_tier": "mega", "hit_rate": 0.7, "avg_views": 500000}
        },
    ]
    
    for i, case in enumerate(test_cases, 1):
        result = predictor.predict(
            title=case["title"],
            thumbnail_features=case["thumbnail"],
            channel_subscribers=case["channel"]["subscribers"],
            channel_size_tier=case["channel"]["size_tier"],
            channel_hit_rate=case["channel"]["hit_rate"],
            channel_avg_views=case["channel"]["avg_views"]
        )
        
        print(f"\n{'─'*70}")
        print(f"📹 Example {i}: \"{case['title'][:50]}...\"")
        print(f"   Channel: {case['channel']['subscribers']:,} subs, {case['channel']['hit_rate']*100:.0f}% hit rate")
        print(f"   Thumbnail: Face={'✅' if case['thumbnail']['has_face'] else '❌'}, "
              f"Text={'✅' if case['thumbnail']['has_text'] else '❌'}, "
              f"Bright={case['thumbnail']['brightness']:.1f}")
        print()
        
        emoji = "🟢" if result.prediction == "ABOVE AVERAGE" else "🔴"
        print(f"   {emoji} Prediction: {result.prediction} ({result.confidence:.0f}% confidence)")
        print(f"   📊 Probability: {result.probability*100:.1f}%")
        
        if result.top_positive_factors:
            print("\n   📈 Helping factors:")
            for name, impact in result.top_positive_factors[:3]:
                print(f"      +{impact*100:.0f}% {name}")
        
        if result.top_negative_factors:
            print("\n   📉 Hurting factors:")
            for name, impact in result.top_negative_factors[:3]:
                print(f"      {impact*100:.0f}% {name}")
        
        if result.recommendations:
            print("\n   💡 Recommendations:")
            for rec in result.recommendations:
                print(f"      {rec}")
    
    print("\n" + "="*70)
    print("✅ Demo complete!")
    print("="*70)


if __name__ == "__main__":
    demo()

