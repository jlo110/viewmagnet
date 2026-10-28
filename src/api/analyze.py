"""
Video Analysis Service

Complete pipeline for analyzing a YouTube video:
1. Fetch metadata from YouTube API
2. Extract title features
3. Analyze thumbnail
4. Get/calculate channel context
5. Run ML prediction
6. Generate SHAP-based explanations
7. Return recommendations
"""

import re
import pickle
import numpy as np
from dataclasses import dataclass
from typing import Optional, Dict, List, Any
from pathlib import Path

import structlog

logger = structlog.get_logger()


@dataclass
class AnalysisResult:
    """Complete analysis result for a video."""
    # Video info
    video_id: str
    title: str
    channel_id: str
    channel_name: str
    thumbnail_url: str
    
    # Score (meaning is mode-scoped — see `mode`/`score_label`)
    prediction_score: float  # 0-100
    prediction_tier: str  # coaching/detection/evaluation labels (see mode)
    probability: float  # Raw probability 0-1
    
    # Component scores
    title_score: float  # 0-100
    thumbnail_score: float  # 0-100
    channel_score: float  # 0-100
    
    # Explanations
    explanations: List[Dict[str, Any]]  # SHAP-based feature explanations
    recommendations: List[str]  # Actionable recommendations
    
    # Niche context
    niche: str
    niche_comparison: Dict[str, Any]

    # Honest framing (which claim this analysis is actually making)
    #   coaching   = pre-launch: packaging strength, NOT a performance prediction
    #   detection  = 1-7d: breaking out vs the channel's own norm (validated)
    #   evaluation = 7d+: realized performance vs the channel
    mode: str = "evaluation"
    score_label: str = "Performance vs your channel"
    headline: str = ""
    disclaimer: Optional[str] = None

    # Raw features (for debugging)
    features: Optional[Dict[str, float]] = None


class VideoAnalyzer:
    """
    Analyzes YouTube videos for performance prediction.
    """
    
    # Adjusted thresholds based on model calibration
    # Model predicts probability of being in top 30%
    # So 30% = average, 50% = good, 70% = great
    TIER_THRESHOLDS = {
        'viral': 70,   # Top ~5% of predictions
        'high': 50,    # Top ~20% of predictions  
        'medium': 30,  # Average
        'low': 0       # Below average
    }
    
    def __init__(self, model_path: str = "data/models/clean_predictor.pkl"):
        """
        Initialize the analyzer.
        
        Args:
            model_path: Path to the trained ML model
        """
        self.model_path = Path(model_path)
        self.model = None
        self.feature_cols = None
        self.st_model = None  # Sentence transformer
        
        self._load_model()
        self._load_embedder()
    
    def _load_model(self):
        """Load the trained ML model."""
        # Try multiple model paths in order of preference
        model_paths = [
            Path("data/models/clean_predictor.pkl"),  # New clean model (73% accuracy)
            Path("data/models/content_predictor.pkl"),
            self.model_path,
        ]
        
        for path in model_paths:
            if not path.exists():
                continue
            
            try:
                with open(path, 'rb') as f:
                    model_data = pickle.load(f)
                
                self.model = model_data.get('model')
                self.feature_cols = model_data.get('feature_cols', [])
                
                if self.model and self.feature_cols:
                    logger.info(f"Loaded model from {path} with {len(self.feature_cols)} features")
                    return
                elif self.model:
                    logger.info(f"Loaded model from {path} (no feature_cols)")
                    return
                    
            except Exception as e:
                logger.debug(f"Failed to load model from {path}: {e}")
        
        # No model loaded - will use heuristic
        logger.info("Using heuristic prediction (no ML model loaded)")
    
    def _needs_embeddings(self) -> bool:
        """True only if the loaded model actually consumes ``emb_*`` features.

        Phase 6.1 found title embeddings add no signal, so the lean model
        (25 hand-crafted features) doesn't need them — and we can skip loading
        the SentenceTransformer + per-request encoding entirely.
        """
        return any(str(c).startswith("emb_") for c in (self.feature_cols or []))

    def _load_embedder(self):
        """Load sentence transformer for title embeddings (only if the model uses them)."""
        if not self._needs_embeddings():
            logger.info("Model uses no embedding features; skipping SentenceTransformer load")
            return
        try:
            from sentence_transformers import SentenceTransformer
            self.st_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Loaded sentence transformer")
        except ImportError:
            logger.warning("sentence-transformers not installed")
    
    def analyze(
        self,
        video_url: str,
        channel_id: Optional[str] = None
    ) -> AnalysisResult:
        """
        Analyze a YouTube video.
        
        For EXISTING videos (with views): Evaluates ACTUAL performance
        For PRE-UPLOAD/NEW videos: Predicts expected performance
        
        Args:
            video_url: YouTube video URL
            channel_id: Optional channel ID for context
            
        Returns:
            AnalysisResult with prediction/evaluation and recommendations
        """
        # Extract video ID
        video_id = self._extract_video_id(video_url)
        if not video_id:
            raise ValueError("Invalid YouTube URL")
        
        # Fetch video metadata
        video_info = self._fetch_video_info(video_id)
        if not video_info:
            raise ValueError(f"Could not fetch video: {video_id}")
        
        # Override channel_id if provided
        if not channel_id:
            channel_id = video_info.channel_id
        
        # Get channel features FIRST (this does the full channel analysis)
        channel_features = self._get_channel_features(channel_id)
        
        # Extract video features
        features = self._extract_features(video_info, channel_id)
        # Merge channel features into video features
        features.update(channel_features)
        
        # ============================================
        # DETERMINE MODE: Based on VIDEO AGE
        # ============================================
        video_views = video_info.view_count or 0
        median_views = channel_features.get('median_views', 0)
        subs = channel_features.get('subscriber_count', 0)
        
        # Calculate video age in days
        video_age_days = 0
        if video_info.published_at:
            try:
                from datetime import datetime, timezone
                if isinstance(video_info.published_at, str):
                    # Parse ISO format
                    pub_date = datetime.fromisoformat(video_info.published_at.replace('Z', '+00:00'))
                else:
                    pub_date = video_info.published_at
                
                now = datetime.now(timezone.utc)
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                video_age_days = (now - pub_date).days
            except Exception as e:
                logger.warning(f"Could not parse publish date: {e}")
                video_age_days = 0
        
        logger.info(f"Video age: {video_age_days} days, views: {video_views:,}")
        
        # Mode selection based on AGE
        # < 1 day: Prediction mode (too early)
        # 1-7 days: Velocity mode (early signals)
        # > 7 days: Evaluation mode (matured)
        is_mature_video = video_age_days >= 7
        is_velocity_phase = 1 <= video_age_days < 7

        # Honest framing, set per mode below (defaults = evaluation).
        mode = "evaluation"
        score_label = "Performance vs your channel"
        headline = ""
        disclaimer = None

        if is_mature_video and median_views > 0:
            # ============================================
            # EVALUATION MODE: Video is 7+ days old
            # Score based on ACTUAL performance
            # ============================================
            logger.info(f"Evaluation mode: Video is {video_age_days} days old with {video_views:,} views (median: {median_views:,.0f})")
            
            # Calculate actual performance ratio
            performance_ratio = video_views / median_views
            
            # View/sub ratio for this specific video
            video_view_sub_ratio = video_views / subs if subs > 0 else 0
            
            # Convert performance to score (50 = median, 100 = 3x+ median)
            if performance_ratio >= 3.0:
                score = 95  # Viral hit
            elif performance_ratio >= 2.0:
                score = 85  # Strong performer
            elif performance_ratio >= 1.5:
                score = 75  # Above average
            elif performance_ratio >= 1.0:
                score = 60  # At median
            elif performance_ratio >= 0.7:
                score = 45  # Slightly below
            elif performance_ratio >= 0.5:
                score = 35  # Below average
            else:
                score = 25  # Underperforming
            
            # Boost for excellent view/sub ratio
            if video_view_sub_ratio >= 3.0:
                score = min(98, score + 10)
            elif video_view_sub_ratio >= 2.0:
                score = min(95, score + 5)
            
            tier = self._label_tier(score, "evaluation")
            probability = score / 100
            mode = "evaluation"
            score_label = "Performance vs your channel"
            _rt = f"{performance_ratio:.1f}× your channel's median"
            headline = (
                f"Strong performer — {_rt}" if performance_ratio >= 1.5
                else f"On track — {_rt}" if performance_ratio >= 1.0
                else f"Below your channel — {_rt}"
            )

            # Store actual performance in features for explanations
            features['actual_views'] = video_views
            features['performance_ratio'] = performance_ratio
            features['video_view_sub_ratio'] = video_view_sub_ratio
            features['is_evaluation'] = True
            features['is_velocity'] = False
            features['video_age_days'] = video_age_days
            
            # Calculate engagement rate for evaluation mode
            likes = getattr(video_info, 'like_count', 0) or 0
            comments = getattr(video_info, 'comment_count', 0) or 0
            if video_views > 0:
                like_rate = (likes / video_views) * 100
                comment_rate = (comments / video_views) * 100
                engagement_rate = like_rate + comment_rate
                
                # Determine engagement label
                if engagement_rate >= 10:
                    eng_label = "exceptional"
                elif engagement_rate >= 5:
                    eng_label = "strong"
                elif engagement_rate >= 3:
                    eng_label = "good"
                elif engagement_rate >= 1:
                    eng_label = "average"
                else:
                    eng_label = "low"
                
                features['engagement'] = {
                    'engagement_rate': round(engagement_rate, 2),
                    'like_rate': round(like_rate, 2),
                    'comment_rate': round(comment_rate, 2),
                    'label': eng_label,
                }
            
        elif is_velocity_phase:
            # ============================================
            # VELOCITY MODE: Video is 1-7 days old
            # Use velocity model to predict Day 30 performance
            # ============================================
            logger.info(f"Velocity mode: Video is {video_age_days} days old with {video_views:,} views")
            
            # Import and use velocity predictor
            try:
                from src.ml.velocity_predictor import get_velocity_predictor
                
                velocity_predictor = get_velocity_predictor()
                
                # Calculate hours since publish
                hours_since_publish = video_age_days * 24
                
                # Get engagement counts
                likes = getattr(video_info, 'like_count', 0) or 0
                comments = getattr(video_info, 'comment_count', 0) or 0
                
                # Build video features dict for velocity model
                video_features_for_velocity = {
                    'brightness': features.get('brightness', 0.5),
                    'saturation': features.get('saturation', 0.5),
                    'contrast': features.get('contrast', 0.5),
                    'has_face': features.get('has_face', False),
                    'has_text': features.get('has_text', False),
                    'title_len': features.get('title_len', 50),
                    'has_number': features.get('has_number', False),
                    'has_question': features.get('has_question', False),
                    'word_count': features.get('word_count', 10),
                    'caps_ratio': features.get('caps_ratio', 0.1),
                }
                
                # Get velocity prediction
                velocity_result = velocity_predictor.predict(
                    current_views=video_views,
                    hours_since_publish=hours_since_publish,
                    likes=likes,
                    comments=comments,
                    subscriber_count=subs,
                    video_features=video_features_for_velocity
                )
                
                # Convert velocity prediction to score
                # Compare predicted Day 30 views to channel median
                predicted_views = velocity_result.predicted_views_day30
                
                # Calculate velocity component (how the video is actually performing)
                if median_views > 0:
                    predicted_ratio = predicted_views / median_views
                    logger.info(f"Velocity scoring: predicted={predicted_views:,}, median={median_views:,.0f}, ratio={predicted_ratio:.2f}x")
                    if predicted_ratio >= 3.0:
                        velocity_score = 95  # Predicted viral
                    elif predicted_ratio >= 2.0:
                        velocity_score = 85  # Predicted strong
                    elif predicted_ratio >= 1.5:
                        velocity_score = 75  # Predicted above average
                    elif predicted_ratio >= 1.0:
                        velocity_score = 60  # Predicted at median
                    elif predicted_ratio >= 0.7:
                        velocity_score = 45  # Predicted slightly below
                    else:
                        velocity_score = 35  # Predicted below average
                else:
                    # Use velocity percentile as score
                    velocity_score = velocity_result.percentile
                    logger.info(f"Velocity scoring: median_views=0, using percentile={velocity_score}")
                
                # Calculate packaging component (title + thumbnail quality)
                # This provides context: strong packaging = potential to improve with promotion
                # Compute component scores ONCE here and reuse below.
                title_score = self._calculate_title_score(features)
                thumbnail_score = self._calculate_thumbnail_score(features)
                packaging_score = (title_score * 0.4 + thumbnail_score * 0.6)  # Thumbnail weighted more
                features["__component_scores_precomputed"] = True
                features["__title_score"] = title_score
                features["__thumbnail_score"] = thumbnail_score
                
                # Blend velocity (70%) with packaging (30%)
                # Velocity matters more since it's actual performance, but packaging still counts
                score = (velocity_score * 0.7) + (packaging_score * 0.3)
                
                logger.info(f"Velocity score: velocity={velocity_score}, packaging={packaging_score:.1f}, blended={score:.1f}")
                
                probability = score / 100
                tier = self._get_tier(score)
                
                # Store velocity prediction details in features
                features['is_evaluation'] = False
                features['is_velocity'] = True
                features['video_age_days'] = video_age_days
                
                # Format milestones for API response
                milestones_data = []
                if velocity_result.milestones:
                    for m in velocity_result.milestones:
                        milestones_data.append({
                            'milestone': m.milestone,
                            'predicted_views': m.predicted_views,
                            'hours_from_now': m.hours_from_now,
                            'days_from_now': round(m.hours_from_now / 24, 1),
                            'growth_percent': m.growth_from_current,
                        })
                
                # Format engagement metrics
                engagement_data = None
                if velocity_result.engagement:
                    eng = velocity_result.engagement
                    engagement_data = {
                        'engagement_rate': eng.engagement_rate,
                        'like_rate': eng.like_rate,
                        'comment_rate': eng.comment_rate,
                        'label': eng.engagement_label,
                    }
                
                features['velocity_prediction'] = {
                    'predicted_views_day30': predicted_views,
                    'trajectory': velocity_result.trajectory,
                    'percentile': velocity_result.percentile,
                    'confidence': velocity_result.confidence,
                    'views_per_hour': round(velocity_result.views_per_hour, 1),
                    'vs_expected': round(velocity_result.vs_expected, 2),
                    'expected_at_this_point': velocity_result.expected_at_this_point,
                    'engagement': engagement_data,
                    'milestones': milestones_data,
                }
                
                logger.info(f"Velocity prediction: {predicted_views:,} views by Day 30 ({velocity_result.trajectory}) with {len(milestones_data)} milestones")
                
            except Exception as e:
                logger.warning(f"Velocity model failed, using fallback: {e}")
                # Fallback to original logic
                probability = self._predict(features)
                
                if video_views > 0 and median_views > 0:
                    early_ratio = video_views / median_views
                    if early_ratio >= 1.5:
                        probability = min(0.95, probability + 0.15)
                    elif early_ratio >= 1.0:
                        probability = min(0.90, probability + 0.08)
                    elif early_ratio >= 0.5:
                        pass
                    else:
                        probability = max(0.25, probability - 0.10)
                
                score = probability * 100
                tier = self._get_tier(score)
                features['is_evaluation'] = False
                features['is_velocity'] = True
                features['video_age_days'] = video_age_days
            
        else:
            # ============================================
            # COACHING MODE: Video is < 1 day old (pre-launch)
            # Performance CANNOT be predicted from packaging (proven AUC 0.50,
            # see memory/content-classifier-title-no-signal). So we do NOT predict
            # — we score PACKAGING STRENGTH via the rubric and say so plainly.
            # ============================================
            logger.info(f"Coaching mode: Video is {video_age_days} days old (pre-launch)")
            mode = "coaching"
            score_label = "Packaging Strength"
            disclaimer = (
                "Performance can't be predicted before launch — no one honestly can. "
                "Post it and we'll tell you within hours if it's breaking out."
            )
            try:
                from src.features.packaging_rubric import score_title
                rubric = score_title(video_info.title)
                score = float(rubric.get("overall_score") or 50)
                if rubric.get("biggest_weakness"):
                    features['rubric_weakness'] = rubric["biggest_weakness"]
                if rubric.get("stronger_titles"):
                    features['rubric_rewrites'] = rubric["stronger_titles"]
                features['rubric_principles'] = rubric.get("principles")
            except Exception as e:
                logger.warning(f"Packaging rubric unavailable, neutral coaching score: {e}")
                score = 50.0
            probability = score / 100
            tier = self._label_tier(score, "coaching")
            headline = (
                "Strong packaging" if score >= 75
                else "Solid packaging" if score >= 50
                else "Packaging needs work"
            )
            features['is_evaluation'] = False
            features['is_velocity'] = False
            features['is_coaching'] = True
            features['video_age_days'] = video_age_days

        # 1-7d: reframe from a Day-30 view FORECAST to honest breakout DETECTION
        # against the channel's own early norm (the validated residual signal).
        if is_velocity_phase and median_views > 0:
            try:
                import math as _math

                from src.features.breakout_detector import assess
                a = assess(float(video_views), _math.log1p(float(median_views)))
                ratio = video_views / median_views if median_views else 1.0
                mode = "detection"
                score_label = "Breakout vs your channel"
                if a.probability is not None:
                    score = round(float(a.probability) * 100, 1)
                    tier = a.level  # breakout / heating_up / normal
                else:
                    tier = a.level
                headline = (
                    f"Breaking out — {ratio:.1f}× your channel's pace" if a.level == "breakout"
                    else f"Heating up — {ratio:.1f}× your channel" if a.level == "heating_up"
                    else f"On pace with your channel ({ratio:.1f}×)" if ratio >= 0.9
                    else f"Below your channel's norm ({ratio:.1f}×)"
                )
            except Exception as e:
                logger.warning(f"Breakout detection override failed, keeping velocity score: {e}")

        # Calculate component scores (reuse if velocity branch already computed them)
        if features.pop("__component_scores_precomputed", False):
            title_score = features.pop("__title_score")
            thumbnail_score = features.pop("__thumbnail_score")
        else:
            title_score = self._calculate_title_score(features)
            thumbnail_score = self._calculate_thumbnail_score(features)
        channel_score = self._calculate_channel_score(features)
        
        # Add scores to features dict so recommendations can use them
        features['title_score'] = title_score
        features['thumbnail_score'] = thumbnail_score
        features['channel_score'] = channel_score
        
        # Get niche context early for recommendations
        niche = self._determine_niche(channel_id)
        features['niche'] = niche
        
        # Generate explanations (including channel context)
        explanations = self._generate_explanations(features, probability)
        recommendations = self._generate_recommendations(features, explanations, channel_features)
        
        # Get niche comparison (niche already determined above)
        niche_comparison = self._get_niche_comparison(score, niche, channel_features, features)
        
        # Convert numpy types to Python native types for JSON serialization
        return AnalysisResult(
            video_id=video_id,
            title=video_info.title,
            channel_id=channel_id,
            channel_name=self._get_channel_name(channel_id, channel_features),
            thumbnail_url=video_info.thumbnail_url or "",
            prediction_score=float(round(score, 1)),
            prediction_tier=tier,
            probability=float(round(probability, 3)),
            title_score=float(round(title_score, 1)),
            thumbnail_score=float(round(thumbnail_score, 1)),
            channel_score=float(round(channel_score, 1)),
            explanations=explanations,
            recommendations=recommendations,
            niche=niche,
            niche_comparison=niche_comparison,
            mode=mode,
            score_label=score_label,
            headline=headline,
            disclaimer=disclaimer,
            features=None  # Only include in debug mode
        )
    
    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from YouTube URL."""
        patterns = [
            r'youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
            r'youtu\.be/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/v/([a-zA-Z0-9_-]{11})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        # Maybe it's just the ID
        if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
            return url
        
        return None
    
    def _fetch_video_info(self, video_id: str):
        """Fetch video metadata from YouTube API."""
        try:
            from src.youtube.client import YouTubeClient
            client = YouTubeClient()
            videos = client.get_video_details([video_id])
            return videos[0] if videos else None
        except Exception as e:
            logger.error(f"Failed to fetch video: {e}")
            return None
    
    def _extract_features(self, video_info, channel_id: str) -> Dict[str, float]:
        """Extract video features (title, thumbnail). Channel features merged separately."""
        features = {}
        
        # Store raw title for pattern detection
        features['title'] = video_info.title
        
        # Title features
        title_features = self._extract_title_features(video_info.title)
        features.update(title_features)
        
        # Thumbnail features
        if video_info.thumbnail_url:
            thumb_features = self._extract_thumbnail_features(video_info.thumbnail_url)
            features.update(thumb_features)
        
        # Note: Channel features are fetched separately in analyze() and merged
        # This avoids duplicate API calls
        
        # Title embeddings (cached by sha256(title))
        if self.st_model:
            from src.cache.analyze import get_title_embedding_cached, set_title_embedding_cached
            cached_embedding = get_title_embedding_cached(video_info.title)
            if cached_embedding is None:
                embedding = self.st_model.encode([video_info.title])[0]
                cached_embedding = [float(v) for v in embedding]
                set_title_embedding_cached(video_info.title, cached_embedding)
            for i, val in enumerate(cached_embedding):
                features[f'emb_{i}'] = float(val)
        
        return features
    
    def _extract_title_features(self, title: str) -> Dict[str, float]:
        """Extract title features."""
        try:
            from src.features.title_analyzer import TitleAnalyzer
            analyzer = TitleAnalyzer()
            features = analyzer.analyze(title)
            
            return {
                'title_len': features.char_length,
                'title_words': features.word_count,
                'has_number': int(features.has_number),
                'has_question': int(features.has_question),
                'has_exclamation': int(features.has_exclamation),
                'has_brackets': int(features.has_brackets),
                'caps_ratio': features.caps_ratio,
                'emotional': features.emotional_score,
                'sentiment': features.sentiment,
                'trending_score': features.trending_score,
                'specificity': features.specificity_score,
            }
        except Exception as e:
            logger.error(f"Title feature extraction failed: {e}")
            return {
                'title_len': len(title),
                'title_words': len(title.split()),
                'has_number': int(any(c.isdigit() for c in title)),
                'has_question': int('?' in title),
                'has_exclamation': int('!' in title),
                'has_brackets': 0,
                'caps_ratio': 0.0,
                'emotional': 0.0,
                'sentiment': 0.0,
                'trending_score': 0.0,
                'specificity': 0.5,
            }
    
    def _extract_thumbnail_features(self, url: str) -> Dict[str, float]:
        """Extract thumbnail features (cached by sha256(url) in Redis)."""
        from src.cache.analyze import get_thumbnail_features_cached, set_thumbnail_features_cached
        
        cached = get_thumbnail_features_cached(url)
        if cached is not None:
            return cached
        
        try:
            from src.features.thumbnail_analyzer import ThumbnailAnalyzer
            analyzer = ThumbnailAnalyzer(
                enable_face_detection=True,
                enable_text_detection=False,  # Slower, skip for API
            )
            features = analyzer.analyze_from_url_sync(url)
            
            if features:
                result = {
                    'brightness': features.brightness,
                    'saturation': features.saturation,
                    'contrast': features.contrast,
                    'has_face': int(features.has_face),
                    'face_count': features.face_count,
                    'face_area_ratio': features.face_area_ratio,
                    'has_text': int(features.has_text),
                    'visual_complexity': features.visual_complexity,
                    'edge_density': features.edge_density,
                }
                set_thumbnail_features_cached(url, result)
                return result
        except Exception as e:
            logger.error(f"Thumbnail feature extraction failed: {e}")
        
        # Default thumbnail features
        return {
            'brightness': 0.5,
            'saturation': 0.5,
            'contrast': 0.5,
            'has_face': 0,
            'face_count': 0,
            'face_area_ratio': 0.0,
            'has_text': 0,
            'visual_complexity': 0.5,
            'edge_density': 0.5,
        }
    
    def _get_channel_features(self, channel_id: str) -> Dict[str, float]:
        """Get channel context features with full analysis."""
        # First try database
        db_features = self._get_channel_from_db(channel_id)
        if db_features:
            return db_features
        
        # Not in DB - fetch from YouTube API with FULL channel analysis
        api_features = self._analyze_channel_from_api(channel_id)
        if api_features:
            return api_features
        
        # Fallback: Default channel features (unknown channel)
        logger.warning(f"Using default channel features for {channel_id}")
        return {
            'log_subs': float(np.log1p(10000)),  # Assume 10K subs
            'log_channel_avg': float(np.log1p(5000)),  # Assume 5K avg views
            'hit_rate': 0.15,  # Assume average hit rate
            'avg_ratio': 1.0,
            'std_ratio': 0.5,
            'video_count': 30,
            'channel_name': 'Unknown Channel',
            'recent_momentum': 0.0,
            'view_sub_ratio': 0.5,  # Assume average reach
            'median_views': 5000,
            'subscriber_count': 10000,
        }
    
    def _get_channel_from_db(self, channel_id: str) -> Optional[Dict[str, float]]:
        """Try to get channel features from database."""
        try:
            from src.database.connection import get_session
            from src.database.models import Channel, Video
            
            with get_session() as session:
                channel = session.query(Channel).filter_by(channel_id=channel_id).first()
                
                if channel:
                    videos = session.query(Video).filter_by(channel_id=channel_id).all()
                    
                    if videos:
                        views = [v.view_count for v in videos if v.view_count]
                        avg_views = channel.avg_views_per_video or np.mean(views) if views else 0
                        median_views = np.median(views) if views else 0
                        subs = channel.subscriber_count or 0
                        
                        # Use MEDIAN for hit threshold (handles outliers)
                        hit_threshold = median_views * 2
                        hit_count = sum(1 for v in views if v > hit_threshold)
                        hit_rate = hit_count / len(views) if views else 0.15
                        
                        # View/sub ratio (absolute performance)
                        view_sub_ratio = median_views / subs if subs > 0 else 0
                        
                        ratios = [v / median_views for v in views if median_views > 0]
                        avg_ratio = np.mean(ratios) if ratios else 1.0
                        std_ratio = np.std(ratios) if ratios else 0.0
                        
                        logger.info(f"Got channel from DB: {channel.channel_name} ({len(videos)} videos, {view_sub_ratio:.1f}x subs)")
                        
                        return {
                            'log_subs': float(np.log1p(subs)),
                            'log_channel_avg': float(np.log1p(avg_views)),
                            'hit_rate': float(hit_rate),
                            'avg_ratio': float(avg_ratio),
                            'std_ratio': float(std_ratio),
                            'video_count': len(videos),
                            'channel_name': channel.channel_name,
                            'subscriber_count': int(subs),
                            'avg_views': float(avg_views),
                            'median_views': float(median_views),
                            'recent_momentum': 0.0,
                            'view_sub_ratio': float(view_sub_ratio),
                        }
        except Exception as e:
            logger.debug(f"Channel not in database: {e}")
        
        return None
    
    def _analyze_channel_from_api(self, channel_id: str) -> Optional[Dict[str, float]]:
        """
        Fetch channel data from YouTube API including recent videos.
        
        This performs a FULL channel analysis:
        1. Get channel details (subs, total views)
        2. Fetch last 30 videos
        3. Get view counts for each video
        4. Calculate REAL hit rate and performance metrics
        """
        try:
            from src.youtube.client import YouTubeClient
            client = YouTubeClient()
            
            # Step 1: Get channel details
            channels = client.get_channel_details([channel_id])
            if not channels:
                logger.warning(f"Channel not found: {channel_id}")
                return None
            
            ch = channels[0]
            subs = ch.subscriber_count or 0
            channel_name = ch.channel_name or "Unknown"
            
            logger.info(f"Analyzing channel: {channel_name} ({subs:,} subs)")
            
            # Step 2: Fetch recent videos (last 50 to ensure we get mature ones)
            # For prolific channels like NBA that post 10+ videos/day, we need more videos
            # to find at least 5 that are 7+ days old for a stable baseline
            uploads_playlist_id = "UU" + channel_id[2:] if channel_id.startswith("UC") else channel_id
            
            video_ids = []
            try:
                # Use playlistItems to get channel videos
                playlist_response = client.get_channel_videos(
                    uploads_playlist_id=uploads_playlist_id,
                    max_results=50,  # Fetch 50 to ensure we get mature videos
                )
                
                # Extract video IDs from playlist response
                if playlist_response and 'items' in playlist_response:
                    for item in playlist_response['items']:
                        vid_id = item.get('contentDetails', {}).get('videoId')
                        if vid_id:
                            video_ids.append(vid_id)
                            
            except Exception as e:
                logger.warning(f"Could not fetch channel videos: {e}")
            
            if not video_ids:
                # Fall back to estimated metrics based on channel size
                return self._estimate_channel_metrics(ch)
            
            # Step 3: Get video statistics
            video_stats = {}
            try:
                # Use get_video_details (returns VideoInfo objects with view_count)
                video_details = client.get_video_details(video_ids)
                video_stats = {v.video_id: v for v in video_details}
            except Exception as e:
                logger.warning(f"Could not fetch video stats: {e}")
            
            # Step 4: Calculate REAL metrics
            # IMPORTANT: Only use MATURE videos (7+ days old) for median calculation
            # New videos haven't reached their full view count yet and would artificially lower the median
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            
            all_views = []
            mature_views = []  # Videos 7+ days old (have reached full view count)
            video_ages = []  # For debugging
            
            for vid_id in video_ids:
                if vid_id in video_stats:
                    video = video_stats[vid_id]
                    view_count = video.view_count or 0
                    all_views.append(view_count)
                    
                    # Check if video is mature (7+ days old)
                    try:
                        if video.published_at:
                            if isinstance(video.published_at, str):
                                pub_date = datetime.fromisoformat(video.published_at.replace('Z', '+00:00'))
                            else:
                                pub_date = video.published_at
                            if pub_date.tzinfo is None:
                                pub_date = pub_date.replace(tzinfo=timezone.utc)
                            
                            video_age_days = (now - pub_date).days
                            video_ages.append(video_age_days)
                            if video_age_days >= 7:
                                mature_views.append(view_count)
                    except Exception as e:
                        logger.debug(f"Could not parse date for {vid_id}: {e}")
                        # If we can't parse date, include in mature as fallback
                        mature_views.append(view_count)
            
            if not all_views:
                return self._estimate_channel_metrics(ch)
            
            # Debug: log video age distribution
            if video_ages:
                max_age = max(video_ages)
                min_age = min(video_ages)
                logger.debug(f"Video ages: min={min_age}d, max={max_age}d, mature(7+d)={len(mature_views)}/{len(video_ages)}")
            
            # Use mature views for median if we have enough (at least 5 videos)
            # This gives a stable baseline that doesn't fluctuate with new uploads
            if len(mature_views) >= 5:
                avg_views = np.mean(mature_views)
                median_views = np.median(mature_views)
                logger.info(f"Using {len(mature_views)} mature videos for baseline (median: {median_views:,.0f})")
            else:
                # Not enough mature videos - this channel posts very frequently
                # For high-velocity channels, estimate mature performance by:
                # 1. Finding the oldest videos we have
                # 2. Using their views as a rough baseline
                # 3. Or using a multiplier on current views to estimate mature views
                
                if video_ages and max(video_ages) > 0:
                    # Get views from the OLDEST videos we have (even if < 7 days)
                    # These are closest to mature and give a better baseline
                    videos_with_age = list(zip(video_ages, all_views))
                    videos_with_age.sort(key=lambda x: x[0], reverse=True)  # Sort by age, oldest first
                    
                    # Take the top 10 oldest videos for baseline
                    oldest_videos = videos_with_age[:min(10, len(videos_with_age))]
                    oldest_views = [v[1] for v in oldest_videos]
                    oldest_ages = [v[0] for v in oldest_videos]
                    
                    avg_views = np.mean(oldest_views)
                    median_views = np.median(oldest_views)
                    
                    # If even the oldest videos are very new (< 3 days), apply growth multiplier
                    avg_oldest_age = np.mean(oldest_ages)
                    if avg_oldest_age < 3:
                        # Videos typically get 50-70% of their views in the first 3 days
                        # Apply 1.5x multiplier to estimate mature performance
                        growth_multiplier = 1.5
                        median_views = median_views * growth_multiplier
                        avg_views = avg_views * growth_multiplier
                        logger.info(f"High-velocity channel: using {len(oldest_videos)} oldest videos (avg age {avg_oldest_age:.1f}d) with {growth_multiplier}x growth estimate (median: {median_views:,.0f})")
                    else:
                        logger.info(f"Using {len(oldest_videos)} oldest videos (avg age {avg_oldest_age:.1f}d) for baseline (median: {median_views:,.0f})")
                else:
                    # Fallback: use all views
                    avg_views = np.mean(all_views)
                    median_views = np.median(all_views)
                    logger.warning(f"No age data available, using all {len(all_views)} videos for baseline (median: {median_views:,.0f})")
            
            views = all_views  # Keep all views for hit rate calculation
            
            # Use MEDIAN for hit threshold to handle viral outliers better
            # A "hit" is a video that got 2x the MEDIAN (not mean)
            # This prevents one viral video from making all others look bad
            hit_threshold = median_views * 2
            hit_count = sum(1 for v in views if v > hit_threshold)
            hit_rate = hit_count / len(views)
            
            # Also calculate view/sub ratio (absolute performance metric)
            view_sub_ratio = median_views / subs if subs > 0 else 0
            
            # Performance ratios (relative to median, not mean)
            ratios = [v / median_views for v in views if median_views > 0]
            avg_ratio = np.mean(ratios) if ratios else 1.0
            std_ratio = np.std(ratios) if ratios else 0.0
            
            # Recent momentum: compare last 10 videos to previous 20
            if len(views) >= 15:
                recent_avg = float(np.mean(views[:10]))
                older_avg = float(np.mean(views[10:]))
                momentum = (recent_avg - older_avg) / older_avg if older_avg > 0 else 0.0
            else:
                momentum = 0.0
            
            logger.info(
                f"Channel analysis complete: {channel_name} | "
                f"Avg views: {avg_views:,.0f} | Hit rate: {hit_rate:.1%} | "
                f"Momentum: {momentum:+.1%}"
            )
            
            return {
                'log_subs': float(np.log1p(subs)),
                'log_channel_avg': float(np.log1p(avg_views)),
                'hit_rate': float(hit_rate),
                'avg_ratio': float(avg_ratio),
                'std_ratio': float(std_ratio),
                'video_count': len(views),
                'channel_name': channel_name,
                'subscriber_count': int(subs),
                'avg_views': float(avg_views),
                'median_views': float(median_views),
                'recent_momentum': float(momentum),
                'view_sub_ratio': float(view_sub_ratio),  # NEW: absolute performance metric
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze channel from API: {e}")
            return None
    
    def _estimate_channel_metrics(self, channel) -> Dict[str, float]:
        """Estimate metrics when we can't fetch individual videos."""
        subs = channel.subscriber_count or 0
        total_views = channel.total_views or 0
        video_count = channel.video_count or 1
        
        avg_views = total_views / max(video_count, 1)
        median_views = avg_views * 0.8  # Estimate median as 80% of average
        
        # Calculate view/sub ratio
        view_sub_ratio = median_views / subs if subs > 0 else 0
        
        # Estimate hit rate based on channel size
        if subs > 50_000_000:
            hit_rate = 0.50
        elif subs > 10_000_000:
            hit_rate = 0.35
        elif subs > 1_000_000:
            hit_rate = 0.25
        elif subs > 100_000:
            hit_rate = 0.18
        else:
            hit_rate = 0.12
                
        logger.info(f"Estimated metrics for {channel.channel_name}: {subs:,} subs, ~{avg_views:,.0f} avg views, {view_sub_ratio:.1f}x ratio")
                
        return {
            'log_subs': float(np.log1p(subs)),
            'log_channel_avg': float(np.log1p(avg_views)),
            'hit_rate': float(hit_rate),
            'avg_ratio': 1.0,
            'std_ratio': 0.5,
            'video_count': int(video_count),
            'channel_name': channel.channel_name,
            'subscriber_count': int(subs),
            'avg_views': float(avg_views),
            'median_views': float(median_views),
            'recent_momentum': 0.0,
            'view_sub_ratio': float(view_sub_ratio),
        }
    
    def _predict(self, features: Dict[str, float]) -> float:
        """Run ML prediction."""
        # For mega-channels (>10M subs), use adjusted scoring
        # But allow variation WITHIN the range for differentiation
        log_subs = features.get('log_subs', 0)
        subs = np.expm1(log_subs)
        
        # Define floor and ceiling for mega-channels
        # This allows differentiation within the channel's typical range
        if subs > 50_000_000:  # 50M+ subs (MrBeast, PewDiePie tier)
            base_floor = 0.55
            base_ceiling = 0.95
        elif subs > 10_000_000:  # 10M+ subs
            base_floor = 0.45
            base_ceiling = 0.90
        elif subs > 1_000_000:  # 1M+ subs
            base_floor = 0.35
            base_ceiling = 0.85
        else:
            base_floor = 0.0  # Use normal model
            base_ceiling = 1.0
        
        # Calculate heuristic prediction (always reliable)
        heuristic_prob = self._heuristic_prediction(features)
        
        if not self.model or not self.feature_cols:
            # No ML model - scale heuristic within range
            if base_floor > 0:
                scaled_prob = base_floor + (heuristic_prob * (base_ceiling - base_floor))
                return float(max(0.20, min(0.98, scaled_prob)))
            return float(max(0.20, heuristic_prob))
        
        # Check how many features we actually have
        # The model expects 409 features, mostly embeddings
        # If we're missing many, don't trust the model as much
        available_features = sum(1 for col in self.feature_cols if features.get(col, 0) != 0)
        feature_coverage = available_features / len(self.feature_cols) if self.feature_cols else 0
        
        # Build feature vector in correct order
        X = np.array([[features.get(col, 0) for col in self.feature_cols]])
        
        try:
            ml_prob = self.model.predict_proba(X)[0][1]
            
            # Blend ML and heuristic based on feature coverage
            # Low coverage = trust heuristic more
            # High coverage = trust ML more
            if feature_coverage < 0.3:
                # Very few features - mostly use heuristic
                blended_prob = 0.2 * ml_prob + 0.8 * heuristic_prob
                logger.info(f"Low feature coverage ({feature_coverage:.1%}), using blended prediction")
            elif feature_coverage < 0.6:
                # Moderate coverage - balanced blend
                blended_prob = 0.5 * ml_prob + 0.5 * heuristic_prob
            else:
                # Good coverage - trust ML more
                blended_prob = 0.7 * ml_prob + 0.3 * heuristic_prob
            
            # Scale the blended probability within the channel's floor/ceiling range
            # This provides differentiation while respecting mega-channel status
            if base_floor > 0:
                # Map 0-1 probability to floor-ceiling range
                scaled_prob = base_floor + (blended_prob * (base_ceiling - base_floor))
                final_prob = scaled_prob
            else:
                final_prob = blended_prob
            
            # Set a reasonable floor (no video should be below 20%)
            final_prob = max(0.20, min(0.98, final_prob))
            
            # Ensure Python float for JSON serialization
            return float(final_prob)
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            # Scale heuristic within range for mega-channels
            if base_floor > 0:
                scaled_prob = base_floor + (heuristic_prob * (base_ceiling - base_floor))
                return float(max(0.20, min(0.98, scaled_prob)))
            return float(max(0.20, heuristic_prob))
    
    def _heuristic_prediction(self, features: Dict[str, float]) -> float:
        """
        Heuristic prediction based on BOTH relative and absolute performance.
        
        NEW APPROACH:
        - 30% weight: ABSOLUTE performance (view/sub ratio, raw views)
        - 20% weight: RELATIVE performance (vs channel history)
        - 50% weight: Content signals (title, thumbnail quality) - MOST IMPORTANT for differentiation
        
        This ensures videos from the SAME channel get DIFFERENT scores
        based on their individual title and thumbnail quality.
        """
        title = features.get('title', '')
        title_lower = title.lower() if isinstance(title, str) else ''
        
        # Start with lower baseline to allow more room for content signals
        score = 0.30
        
        # ========================================
        # ABSOLUTE PERFORMANCE (30% weight) - reduced for more content variation
        # ========================================
        log_subs = features.get('log_subs', 0)
        subs = np.expm1(log_subs) if log_subs > 0 else 0
        view_sub_ratio = features.get('view_sub_ratio', 0)
        median_views = features.get('median_views', 0)
        avg_views = features.get('avg_views', 0)
        
        # View/Subscriber ratio - scaled down
        if view_sub_ratio >= 5.0:
            score += 0.12
        elif view_sub_ratio >= 2.0:
            score += 0.09
        elif view_sub_ratio >= 1.0:
            score += 0.06
        elif view_sub_ratio >= 0.5:
            score += 0.03
        elif view_sub_ratio > 0:
            score += 0.01
        
        # Absolute view benchmarks - scaled down
        if subs < 10_000:
            if median_views >= 50_000:
                score += 0.10
            elif median_views >= 10_000:
                score += 0.06
            elif median_views >= 5_000:
                score += 0.03
        elif subs < 100_000:
            if median_views >= 100_000:
                score += 0.08
            elif median_views >= 25_000:
                score += 0.05
            elif median_views >= 10_000:
                score += 0.02
        elif subs < 1_000_000:
            if median_views >= 500_000:
                score += 0.06
            elif median_views >= 100_000:
                score += 0.04
            elif median_views >= 50_000:
                score += 0.02
        else:
            # Mega channel benchmarks - minimal boost (content matters more)
            if median_views >= 1_000_000:
                score += 0.06
            elif median_views >= 500_000:
                score += 0.03
        
        # ========================================
        # RELATIVE PERFORMANCE (20% weight) - reduced
        # Compare to channel's own history
        # ========================================
        hit_rate = features.get('hit_rate', 0.15)
        
        # Hit rate - scaled down
        if hit_rate > 0.35:
            score += 0.06
        elif hit_rate > 0.25:
            score += 0.04
        elif hit_rate > 0.15:
            score += 0.02
        
        # Channel momentum - scaled down
        momentum = features.get('recent_momentum', 0)
        if momentum > 0.30:
            score += 0.06
        elif momentum > 0.15:
            score += 0.04
        elif momentum > 0.05:
            score += 0.02
        elif momentum < -0.20:
            score -= 0.02
        
        # ========================================
        # CONTENT SIGNALS (50% weight) - MOST IMPORTANT for differentiation
        # Title + Thumbnail quality - this is what makes each video unique
        # ========================================
        
        # --- TITLE FACTORS (up to +0.30) ---
        title_len = features.get('title_len', 0)
        if 40 <= title_len <= 60:
            score += 0.06
        elif 25 <= title_len < 40:
            score += 0.03
        elif title_len < 15 or title_len > 80:
            score -= 0.03  # Penalty for bad length
        
        # Numbers in title (lists, rankings, etc.)
        if features.get('has_number'):
            score += 0.05
        
        # Emotional language
        emotional = features.get('emotional', 0)
        if emotional > 0.6:
            score += 0.08
        elif emotional > 0.3:
            score += 0.04
        elif emotional < 0.1:
            score -= 0.02  # Too bland
        
        # Exclamation marks = energy (great for sports, gaming, entertainment)
        exclamation_count = title.count('!') if isinstance(title, str) else 0
        if exclamation_count >= 3:
            score += 0.06
        elif exclamation_count >= 1:
            score += 0.03
        
        # Emoji presence (common in modern YouTube titles)
        emoji_patterns = ['🔥', '😱', '😳', '👀', '💯', '🏀', '⚡', '🎯', '😤', '🤯']
        emoji_count = sum(1 for e in emoji_patterns if e in title)
        if emoji_count >= 2:
            score += 0.06
        elif emoji_count >= 1:
            score += 0.03
        
        # High-engagement content patterns
        viral_patterns = ['compilation', 'highlights', 'best', 'top', 'challenge', 
                         'vs', 'fail', 'win', 'exposed', 'caught', 'shocking', 
                         'insane', 'crazy', 'worst', 'ultimate', 'epic',
                         'part', 'reaction', 'try not to', 'full game', 'clutch',
                         'buzzer', 'poster', 'dunk', 'block', 'steal']
        pattern_matches = sum(1 for p in viral_patterns if p in title_lower)
        if pattern_matches >= 3:
            score += 0.12  # Multiple viral patterns = strong hook
        elif pattern_matches >= 2:
            score += 0.08
        elif pattern_matches >= 1:
            score += 0.04
        
        # Question marks (curiosity gap)
        if '?' in title:
            score += 0.03
        
        # CAPS usage (attention grabbing)
        if isinstance(title, str):
            caps_ratio = sum(1 for c in title if c.isupper()) / max(1, len(title))
            if 0.15 <= caps_ratio <= 0.40:  # Some caps, not all caps
                score += 0.04
            elif caps_ratio > 0.60:  # Too much caps
                score -= 0.02
        
        # Series indicator (Part X) shows returning audience
        if 'part' in title_lower and any(c.isdigit() for c in title):
            score += 0.04
        
        # --- THUMBNAIL FACTORS (up to +0.20) ---
        if features.get('has_face'):
            score += 0.08  # Faces are crucial
        
        brightness = features.get('brightness', 0.5)
        if 0.35 <= brightness <= 0.70:
            score += 0.04
        elif brightness < 0.25 or brightness > 0.85:
            score -= 0.02  # Too dark or too washed out
        
        saturation = features.get('saturation', 0.5)
        if saturation > 0.5:
            score += 0.04  # Vibrant colors
        elif saturation > 0.3:
            score += 0.02
        
        contrast = features.get('contrast', 0.5)
        if contrast > 0.4:
            score += 0.04  # Good contrast
        
        # ========================================
        # FINAL SCORE
        # ========================================
        # Lower floor (25%) and high ceiling (95%) for maximum differentiation
        return max(0.25, min(0.95, score))
    
    def _get_tier(self, score: float) -> str:
        """Convert score to tier."""
        for tier, threshold in self.TIER_THRESHOLDS.items():
            if score >= threshold:
                return tier
        return 'low'

    def _label_tier(self, score: float, mode: str) -> str:
        """Honest, mode-scoped tier label (never 'viral' — we don't predict that)."""
        if mode == "coaching":
            return "strong" if score >= 75 else "solid" if score >= 50 else "needs_work"
        # evaluation (detection sets its own label from the breakout level)
        if score >= 75:
            return "strong"
        if score >= 50:
            return "on_track"
        if score >= 35:
            return "below"
        return "underperforming"
    
    def _calculate_title_score(self, features: Dict[str, float]) -> float:
        """Calculate title-specific score with nuanced analysis."""
        score = 50
        title = features.get('title', '')
        title_lower = title.lower() if isinstance(title, str) else ''
        
        # Length optimization (more nuanced)
        title_len = features.get('title_len', 0)
        if 45 <= title_len <= 65:
            score += 12  # Sweet spot
        elif 35 <= title_len <= 75:
            score += 6  # Good range
        elif 25 <= title_len < 35:
            score += 2  # Short but acceptable
        elif title_len > 80:
            score -= 8  # Gets truncated
        elif title_len < 20:
            score -= 5  # Too short for SEO
        
        # Hook elements - cumulative
        if features.get('has_number'):
            score += 7
        if features.get('has_question'):
            score += 5
        
        # Emotional intensity (key driver)
        emotional = features.get('emotional', 0)
        if emotional > 0.7:
            score += 12
        elif emotional > 0.5:
            score += 8
        elif emotional > 0.3:
            score += 4
        elif emotional < 0.15:
            score -= 3  # Too dry/neutral
        
        # Exclamation marks - diminishing returns
        exclamation_count = title.count('!') if isinstance(title, str) else 0
        if exclamation_count == 1:
            score += 4
        elif exclamation_count == 2:
            score += 5
        elif exclamation_count >= 3:
            score += 3  # Too many can feel spammy
        
        # Trending score boost
        if features.get('trending_score', 0) > 0.5:
            score += 10
        elif features.get('trending_score', 0) > 0.3:
            score += 5
        
        # High-performing patterns (validated from data)
        high_impact_patterns = ['you need to', 'world record', 'speedrun', 'official', 
                               'music video', 'first time', 'reaction']
        for pattern in high_impact_patterns:
            if pattern in title_lower:
                score += 8
                break  # Only count once
        
        # Medium-impact patterns
        viral_patterns = ['compilation', 'challenge', 'vs', 'battle', 'fail', 
                         'exposed', 'caught', 'best', 'worst', 'top 10', 
                         'ultimate', 'insane', 'crazy', 'epic', 'finally',
                         'truth about', 'what happened', 'never']
        matches = sum(1 for word in viral_patterns if word in title_lower)
        score += min(10, matches * 4)  # Up to +10
        
        # Negative patterns (overused/spammy)
        overused_patterns = ['gone wrong', 'not clickbait', 'you wont believe']
        for pattern in overused_patterns:
            if pattern in title_lower:
                score -= 5
                break
        
        # ALL CAPS penalty (unless very short)
        if title.isupper() and title_len > 20:
            score -= 8
        
        return max(0, min(100, score))
    
    def _calculate_thumbnail_score(self, features: Dict[str, float]) -> float:
        """Calculate thumbnail-specific score with comprehensive analysis."""
        score = 50
        
        # Face detection - most important factor for CTR
        if features.get('has_face'):
            score += 15
            # Face emotion adds extra boost
            face_emotion = features.get('face_emotion', '')
            if face_emotion in ('surprised', 'fear', 'happy'):
                score += 5  # Expressive emotions
            elif face_emotion in ('neutral', 'sad'):
                score += 0  # Neutral faces are less compelling
            
            # Face area ratio (bigger faces = more impact)
            face_area = features.get('face_area_ratio', 0)
            if face_area > 0.15:
                score += 5  # Face is prominent
            elif face_area > 0.08:
                score += 2  # Face is visible but not dominant
        
        # Brightness - optimal range is bright but not washed out
        brightness = features.get('brightness', 0.5)
        if 0.45 <= brightness <= 0.65:
            score += 10  # Optimal
        elif 0.35 <= brightness <= 0.75:
            score += 5  # Good
        elif brightness < 0.3:
            score -= 8  # Too dark - gets skipped
        elif brightness > 0.85:
            score -= 3  # Too washed out
        
        # Saturation - vibrant colors stand out
        saturation = features.get('saturation', 0.5)
        if saturation > 0.55:
            score += 10  # Vibrant
        elif saturation > 0.4:
            score += 6  # Good
        elif saturation > 0.25:
            score += 2  # Acceptable
        else:
            score -= 5  # Dull/desaturated
        
        # Contrast - helps elements pop
        contrast = features.get('contrast', 0.5)
        if contrast > 0.5:
            score += 8  # High contrast
        elif contrast > 0.35:
            score += 4  # Good contrast
        elif contrast < 0.2:
            score -= 5  # Flat/muddy
        
        # Text overlay - can help or hurt
        has_text = features.get('has_text', False)
        text_area = features.get('text_area_ratio', 0)
        if has_text:
            if 0.05 <= text_area <= 0.25:
                score += 5  # Good amount of text
            elif text_area > 0.4:
                score -= 3  # Too much text
        
        # Edge density - visual complexity
        edge_density = features.get('edge_density', 0.5)
        if 0.3 <= edge_density <= 0.6:
            score += 3  # Good visual interest without clutter
        elif edge_density > 0.8:
            score -= 3  # Too busy/cluttered
        
        # Color harmony (if available)
        if features.get('color_harmony_score', 0) > 0.7:
            score += 4
        
        return max(0, min(100, score))
    
    def _calculate_channel_score(self, features: Dict[str, float]) -> float:
        """Calculate channel context score."""
        hit_rate = features.get('hit_rate', 0.15)
        
        # Hit rate is the main factor
        # Average channels have ~15% hit rate
        # Top channels have 30%+
        score = 50 + (hit_rate - 0.15) * 200
        
        return max(0, min(100, score))
    
    def _generate_explanations(
        self,
        features: Dict[str, float],
        probability: float
    ) -> List[Dict[str, Any]]:
        """Generate explanations based on mode (evaluation vs prediction)."""
        explanations = []
        
        # ============================================
        # EVALUATION MODE: Show ACTUAL performance
        # ============================================
        if features.get('is_evaluation'):
            actual_views = features.get('actual_views', 0)
            performance_ratio = features.get('performance_ratio', 1.0)
            video_view_sub_ratio = features.get('video_view_sub_ratio', 0)
            median_views = features.get('median_views', 0)
            
            # Actual views achieved - scale: -10 to +10 based on performance ratio
            if performance_ratio >= 3.0:
                views_impact = '+10'
            elif performance_ratio >= 2.0:
                views_impact = '+8'
            elif performance_ratio >= 1.5:
                views_impact = '+5'
            elif performance_ratio >= 1.0:
                views_impact = '+2'
            elif performance_ratio >= 0.7:
                views_impact = '-3'
            elif performance_ratio >= 0.5:
                views_impact = '-6'
            else:
                views_impact = '-9'
            
            explanations.append({
                'feature': 'Actual Views',
                'value': f'{actual_views:,}',
                'impact': views_impact,
                'direction': 'positive' if performance_ratio >= 1 else 'negative',
                'explanation': f'This video achieved {actual_views:,} views'
            })
            
            # Performance vs channel median - scale: -10 to +10
            if performance_ratio >= 3.0:
                explanations.append({
                    'feature': 'vs Channel Median',
                    'value': f'{performance_ratio:.1f}x median',
                    'impact': '+10',
                    'direction': 'positive',
                    'explanation': f'Viral hit! {performance_ratio:.1f}x better than your typical video ({median_views:,.0f} median)'
                })
            elif performance_ratio >= 2.0:
                explanations.append({
                    'feature': 'vs Channel Median',
                    'value': f'{performance_ratio:.1f}x median',
                    'impact': '+8',
                    'direction': 'positive',
                    'explanation': f'Strong performer! {performance_ratio:.1f}x better than typical ({median_views:,.0f} median)'
                })
            elif performance_ratio >= 1.5:
                explanations.append({
                    'feature': 'vs Channel Median',
                    'value': f'{performance_ratio:.1f}x median',
                    'impact': '+5',
                    'direction': 'positive',
                    'explanation': f'Above average performance ({median_views:,.0f} median)'
                })
            elif performance_ratio >= 1.0:
                explanations.append({
                    'feature': 'vs Channel Median',
                    'value': f'{performance_ratio:.1f}x median',
                    'impact': '+2',
                    'direction': 'positive',
                    'explanation': f'At or above your typical video ({median_views:,.0f} median)'
                })
            elif performance_ratio >= 0.7:
                explanations.append({
                    'feature': 'vs Channel Median',
                    'value': f'{performance_ratio:.1f}x median',
                    'impact': '-4',
                    'direction': 'negative',
                    'explanation': f'Slightly below typical ({median_views:,.0f} median)'
                })
            else:
                explanations.append({
                    'feature': 'vs Channel Median',
                    'value': f'{performance_ratio:.1f}x median',
                    'impact': '-7',
                    'direction': 'negative',
                    'explanation': f'Below your typical video ({median_views:,.0f} median)'
                })
            
            # Video's view/sub ratio - scale: -10 to +10
            if video_view_sub_ratio >= 5.0:
                explanations.append({
                    'feature': 'Video Reach',
                    'value': f'{video_view_sub_ratio:.1f}x subs',
                    'impact': '+10',
                    'direction': 'positive',
                    'explanation': f'Viral reach! {video_view_sub_ratio:.1f}x your subscriber count'
                })
            elif video_view_sub_ratio >= 3.0:
                explanations.append({
                    'feature': 'Video Reach',
                    'value': f'{video_view_sub_ratio:.1f}x subs',
                    'impact': '+8',
                    'direction': 'positive',
                    'explanation': f'Excellent reach - {video_view_sub_ratio:.1f}x your subscriber count'
                })
            elif video_view_sub_ratio >= 2.0:
                explanations.append({
                    'feature': 'Video Reach',
                    'value': f'{video_view_sub_ratio:.1f}x subs',
                    'impact': '+6',
                    'direction': 'positive',
                    'explanation': f'Strong reach - {video_view_sub_ratio:.1f}x your subscriber count'
                })
            elif video_view_sub_ratio >= 1.0:
                explanations.append({
                    'feature': 'Video Reach',
                    'value': f'{video_view_sub_ratio:.1f}x subs',
                    'impact': '+3',
                    'direction': 'positive',
                    'explanation': 'Good reach - matched or exceeded your subscriber count'
                })
            elif video_view_sub_ratio >= 0.5:
                explanations.append({
                    'feature': 'Video Reach',
                    'value': f'{video_view_sub_ratio:.1f}x subs',
                    'impact': '+0',
                    'direction': 'neutral',
                    'explanation': 'Moderate reach - about half your subscriber count'
                })
            else:
                explanations.append({
                    'feature': 'Video Reach',
                    'value': f'{video_view_sub_ratio:.1f}x subs',
                    'impact': '-4',
                    'direction': 'negative',
                    'explanation': 'Limited reach - below half your subscriber count'
                })
            
            # Engagement rate for evaluation mode - scale: -10 to +10
            engagement = features.get('engagement', {})
            if engagement:
                eng_rate = engagement.get('engagement_rate', 0)
                like_rate = engagement.get('like_rate', 0)
                comment_rate = engagement.get('comment_rate', 0)
                eng_label = engagement.get('label', 'average')
                
                # Determine impact based on engagement level
                if eng_label == 'exceptional':
                    impact = '+10'
                    direction = 'positive'
                elif eng_label == 'strong':
                    impact = '+7'
                    direction = 'positive'
                elif eng_label == 'good':
                    impact = '+4'
                    direction = 'positive'
                elif eng_label == 'average':
                    impact = '+0'
                    direction = 'neutral'
                else:  # low
                    impact = '-5'
                    direction = 'negative'
                
                explanations.append({
                    'feature': 'Engagement Rate',
                    'value': f'{eng_rate:.1f}% ({eng_label})',
                    'impact': impact,
                    'direction': direction,
                    'explanation': f'Likes: {like_rate:.1f}% | Comments: {comment_rate:.2f}% of views'
                })
            
            # Sort and return top explanations for evaluation mode
            explanations.sort(key=lambda x: abs(int(x['impact'].replace('%', '').replace('+', ''))), reverse=True)
            return explanations[:6]
        
        # ============================================
        # VELOCITY MODE: Show early performance + prediction
        # ============================================
        if features.get('is_velocity') and features.get('velocity_prediction'):
            velocity_pred = features.get('velocity_prediction', {})
            predicted_views = velocity_pred.get('predicted_views_day30', 0)
            trajectory = velocity_pred.get('trajectory', 'normal')
            percentile = velocity_pred.get('percentile', 50)
            confidence = velocity_pred.get('confidence', 0.5)
            vph = velocity_pred.get('views_per_hour', 0)
            vs_expected = velocity_pred.get('vs_expected', 1.0)
            expected_views = velocity_pred.get('expected_at_this_point', 0)
            
            current_views = features.get('views', 0)
            
            # Current velocity - scale: -10 to +10
            if vph >= 100:
                explanations.append({
                    'feature': 'Current Velocity',
                    'value': f'{vph:,.0f} views/hour',
                    'impact': '+8',
                    'direction': 'positive',
                    'explanation': f'Strong early momentum at {vph:,.0f} views per hour'
                })
            elif vph >= 50:
                explanations.append({
                    'feature': 'Current Velocity',
                    'value': f'{vph:,.0f} views/hour',
                    'impact': '+5',
                    'direction': 'positive',
                    'explanation': f'Good velocity at {vph:,.0f} views per hour'
                })
            elif vph >= 10:
                explanations.append({
                    'feature': 'Current Velocity',
                    'value': f'{vph:,.0f} views/hour',
                    'impact': '+2',
                    'direction': 'neutral',
                    'explanation': f'Moderate pace: {vph:,.0f} views per hour'
                })
            elif vph > 0:
                explanations.append({
                    'feature': 'Current Velocity',
                    'value': f'{vph:,.0f} views/hour',
                    'impact': '-3',
                    'direction': 'negative',
                    'explanation': f'Slow pace: {vph:,.0f} views per hour'
                })
            
            # Engagement rate - scale: -10 to +10
            engagement = velocity_pred.get('engagement', {})
            if engagement:
                eng_rate = engagement.get('engagement_rate', 0)
                like_rate = engagement.get('like_rate', 0)
                comment_rate = engagement.get('comment_rate', 0)
                eng_label = engagement.get('label', 'average')
                
                # Determine impact based on engagement level
                if eng_label == 'exceptional':
                    impact = '+10'
                    direction = 'positive'
                elif eng_label == 'strong':
                    impact = '+7'
                    direction = 'positive'
                elif eng_label == 'good':
                    impact = '+4'
                    direction = 'positive'
                elif eng_label == 'average':
                    impact = '+0'
                    direction = 'neutral'
                else:  # low
                    impact = '-5'
                    direction = 'negative'
                
                explanations.append({
                    'feature': 'Engagement Rate',
                    'value': f'{eng_rate:.1f}% ({eng_label})',
                    'impact': impact,
                    'direction': direction,
                    'explanation': f'Likes: {like_rate:.1f}% | Comments: {comment_rate:.2f}% of views'
                })
            
            # Predicted Day 30 views - scale based on percentile
            # Percentile 99 = +10, 75 = +5, 50 = 0, 25 = -5, 10 = -8
            if percentile >= 90:
                pred_impact = '+10'
            elif percentile >= 75:
                pred_impact = '+6'
            elif percentile >= 50:
                pred_impact = '+2'
            elif percentile >= 25:
                pred_impact = '-4'
            else:
                pred_impact = '-8'
            
            explanations.append({
                'feature': 'Day 30 Prediction',
                'value': f'{predicted_views:,}',
                'impact': pred_impact,
                'direction': 'positive' if percentile >= 50 else 'negative',
                'explanation': f'Projected to reach {predicted_views:,} views by Day 30 (top {100-percentile}%)'
            })
            
            # Trajectory - scale: -10 to +10
            trajectory_impacts = {
                'viral': ('+10', 'positive'),
                'strong': ('+7', 'positive'),
                'above_average': ('+4', 'positive'),
                'normal': ('+0', 'neutral'),
                'slow': ('-5', 'negative'),
                'struggling': ('-8', 'negative'),
            }
            impact, direction = trajectory_impacts.get(trajectory, ('+0', 'neutral'))
            explanations.append({
                'feature': 'Trajectory',
                'value': trajectory.replace('_', ' ').title(),
                'impact': impact,
                'direction': direction,
                'explanation': f'Video is on a {trajectory.replace("_", " ")} trajectory based on early performance'
            })
            
            # vs Expected - scale: -10 to +10
            if vs_expected >= 2.0:
                explanations.append({
                    'feature': 'vs Expected',
                    'value': f'{vs_expected:.1f}x ahead',
                    'impact': '+9',
                    'direction': 'positive',
                    'explanation': f'Performing {vs_expected:.1f}x better than expected at this point'
                })
            elif vs_expected >= 1.5:
                explanations.append({
                    'feature': 'vs Expected',
                    'value': f'{vs_expected:.1f}x ahead',
                    'impact': '+6',
                    'direction': 'positive',
                    'explanation': f'Performing {vs_expected:.1f}x better than expected at this point'
                })
            elif vs_expected >= 1.0:
                explanations.append({
                    'feature': 'vs Expected',
                    'value': f'{vs_expected:.1f}x (on track)',
                    'impact': '+2',
                    'direction': 'positive',
                    'explanation': 'On track with expected performance'
                })
            elif vs_expected >= 0.7:
                explanations.append({
                    'feature': 'vs Expected',
                    'value': f'{vs_expected:.1f}x behind',
                    'impact': '-4',
                    'direction': 'negative',
                    'explanation': 'Slightly behind expected pace'
                })
            else:
                explanations.append({
                    'feature': 'vs Expected',
                    'value': f'{vs_expected:.1f}x behind',
                    'impact': '-7',
                    'direction': 'negative',
                    'explanation': 'Behind expected pace - may need promotion or adjustment'
                })
            
            # Show upcoming milestones - impact based on growth potential
            milestones = velocity_pred.get('milestones', [])
            if milestones:
                # Show next 2 milestones in explanations
                for m in milestones[:2]:
                    milestone_name = m.get('milestone', '').replace('_', ' ').title()
                    pred_views = m.get('predicted_views', 0)
                    growth = m.get('growth_percent', 0)
                    days = m.get('days_from_now', 0)
                    
                    # Impact based on growth potential: high growth = positive
                    if growth >= 100:
                        impact = '+6'
                    elif growth >= 50:
                        impact = '+4'
                    elif growth >= 20:
                        impact = '+2'
                    else:
                        impact = '+0'
                    
                    explanations.append({
                        'feature': f'{milestone_name}',
                        'value': f'{pred_views:,} views (+{growth:.0f}%)',
                        'impact': impact,
                        'direction': 'positive' if growth > 20 else 'neutral',
                        'explanation': f'Predicted to reach {pred_views:,} views by {milestone_name} ({days:.0f} days from now)'
                    })
            
            # Model confidence - scale: higher confidence = more reliable
            if confidence >= 0.8:
                conf_impact = '+3'
            elif confidence >= 0.6:
                conf_impact = '+1'
            else:
                conf_impact = '-2'
            
            explanations.append({
                'feature': 'Confidence',
                'value': f'{int(confidence * 100)}%',
                'impact': conf_impact,
                'direction': 'positive' if confidence >= 0.6 else 'negative',
                'explanation': f'Prediction confidence: {int(confidence * 100)}% (based on data available)'
            })
            
            return explanations[:8]  # Allow more explanations for velocity mode
        
        # ============================================
        # PREDICTION MODE: Show predicted factors
        # ============================================
        
        # === ABSOLUTE PERFORMANCE (View/Sub Ratio) ===
        view_sub_ratio = features.get('view_sub_ratio', 0)
        subs = np.expm1(features.get('log_subs', 0))
        median_views = features.get('median_views', 0)
        
        # View/Sub ratio - scale: -10 to +10
        if view_sub_ratio >= 5.0:
            explanations.append({
                'feature': 'View/Sub Ratio',
                'value': f'{view_sub_ratio:.1f}x subs',
                'impact': '+10',
                'direction': 'positive',
                'explanation': f'Viral reach! Your videos get {view_sub_ratio:.1f}x your subscriber count'
            })
        elif view_sub_ratio >= 2.0:
            explanations.append({
                'feature': 'View/Sub Ratio',
                'value': f'{view_sub_ratio:.1f}x subs',
                'impact': '+7',
                'direction': 'positive',
                'explanation': f'Excellent reach! {view_sub_ratio:.1f}x your subscriber count'
            })
        elif view_sub_ratio >= 1.0:
            explanations.append({
                'feature': 'View/Sub Ratio',
                'value': f'{view_sub_ratio:.1f}x subs',
                'impact': '+4',
                'direction': 'positive',
                'explanation': 'Strong reach - matching or exceeding your subscriber count'
            })
        elif view_sub_ratio >= 0.5:
            explanations.append({
                'feature': 'View/Sub Ratio',
                'value': f'{view_sub_ratio:.1f}x subs',
                'impact': '+2',
                'direction': 'positive',
                'explanation': 'Good reach - engaging a solid portion of your audience'
            })
        elif view_sub_ratio > 0:
            explanations.append({
                'feature': 'View/Sub Ratio',
                'value': f'{view_sub_ratio:.1f}x subs',
                'impact': '-3',
                'direction': 'negative',
                'explanation': 'Low reach - most videos miss subscriber base'
            })
        
        # Absolute view benchmark (by channel size)
        if subs < 10_000 and median_views >= 10_000:
            explanations.append({
                'feature': 'Viral Potential',
                'value': f'{median_views:,.0f} median',
                'impact': '+9',
                'direction': 'positive',
                'explanation': 'Outstanding! 10K+ views with under 10K subs shows viral potential'
            })
        elif subs < 100_000 and median_views >= 50_000:
            explanations.append({
                'feature': 'Strong Reach',
                'value': f'{median_views:,.0f} median',
                'impact': '+7',
                'direction': 'positive',
                'explanation': 'Excellent reach for your channel size'
            })
        
        # Channel hit rate - scale: -10 to +10
        hit_rate = features.get('hit_rate', 0.15)
        if hit_rate > 0.30:
            explanations.append({
                'feature': 'Channel Hit Rate',
                'value': f'{hit_rate:.0%} hit',
                'impact': '+6',
                'direction': 'positive',
                'explanation': 'Your channel consistently produces breakout videos'
            })
        elif hit_rate > 0.20:
            explanations.append({
                'feature': 'Channel Hit Rate',
                'value': f'{hit_rate:.0%} hit',
                'impact': '+3',
                'direction': 'positive',
                'explanation': 'Good hit rate - you know how to make videos that connect'
            })
        elif hit_rate < 0.08:
            explanations.append({
                'feature': 'Channel Hit Rate',
                'value': f'{hit_rate:.0%} hit',
                'impact': '-4',
                'direction': 'negative',
                'explanation': 'Low hit rate - study your top performers'
            })
        
        # Title length - scale: -10 to +10
        title_len = features.get('title_len', 0)
        if 40 <= title_len <= 60:
            explanations.append({
                'feature': 'Title Length',
                'value': f'{title_len} chars',
                'impact': '+3',
                'direction': 'positive',
                'explanation': 'Optimal length for visibility'
            })
        elif title_len > 70:
            explanations.append({
                'feature': 'Title Length',
                'value': f'{title_len} chars',
                'impact': '-4',
                'direction': 'negative',
                'explanation': 'May get truncated on mobile'
            })
        elif title_len < 25:
            explanations.append({
                'feature': 'Title Length',
                'value': f'{title_len} chars',
                'impact': '-2',
                'direction': 'negative',
                'explanation': 'Title might be too short for SEO'
            })
        
        # Has face - scale: -10 to +10
        if features.get('has_face'):
            explanations.append({
                'feature': 'Face in Thumbnail',
                'value': 'Yes',
                'impact': '+5',
                'direction': 'positive',
                'explanation': 'Faces increase click-through rate'
            })
        else:
            explanations.append({
                'feature': 'Face in Thumbnail',
                'value': 'No',
                'impact': '-2',
                'direction': 'negative',
                'explanation': 'Consider adding a face for higher CTR'
            })
        
        # Emotional intensity - scale: -10 to +10
        emotional = features.get('emotional', 0)
        if emotional > 0.7:
            explanations.append({
                'feature': 'Emotional Title',
                'value': f'{emotional:.0%}',
                'impact': '+5',
                'direction': 'positive',
                'explanation': 'Strong emotional language drives clicks'
            })
        elif emotional > 0.5:
            explanations.append({
                'feature': 'Emotional Title',
                'value': f'{emotional:.0%}',
                'impact': '+3',
                'direction': 'positive',
                'explanation': 'Good emotional appeal'
            })
        
        # Number in title - scale: -10 to +10
        if features.get('has_number'):
            explanations.append({
                'feature': 'Number in Title',
                'value': 'Yes',
                'impact': '+3',
                'direction': 'positive',
                'explanation': 'Specific numbers improve CTR'
            })
        
        # Brightness - scale: -10 to +10
        brightness = features.get('brightness', 0.5)
        if brightness < 0.3:
            explanations.append({
                'feature': 'Thumbnail Brightness',
                'value': 'Low',
                'impact': '-4',
                'direction': 'negative',
                'explanation': 'Dark thumbnails get less attention in feeds'
            })
        elif brightness > 0.65:
            explanations.append({
                'feature': 'Thumbnail Brightness',
                'value': 'High',
                'impact': '+3',
                'direction': 'positive',
                'explanation': 'Bright thumbnails stand out and get more clicks'
            })
        
        # Saturation
        saturation = features.get('saturation', 0.5)
        if saturation < 0.25:
            explanations.append({
                'feature': 'Color Saturation',
                'value': 'Low',
                'impact': '-3',
                'direction': 'negative',
                'explanation': 'Dull colors blend into the feed—boost saturation'
            })
        elif saturation > 0.55:
            explanations.append({
                'feature': 'Color Saturation',
                'value': 'Vibrant',
                'impact': '+3',
                'direction': 'positive',
                'explanation': 'Vibrant colors grab attention'
            })
        
        # Contrast
        contrast = features.get('contrast', 0.5)
        if contrast < 0.2:
            explanations.append({
                'feature': 'Visual Contrast',
                'value': 'Low',
                'impact': '-3',
                'direction': 'negative',
                'explanation': 'Low contrast makes elements hard to distinguish'
            })
        elif contrast > 0.5:
            explanations.append({
                'feature': 'Visual Contrast',
                'value': 'High',
                'impact': '+2',
                'direction': 'positive',
                'explanation': 'High contrast makes key elements pop'
            })
        
        # Overall title score summary
        title_score = features.get('title_score', 50)
        if title_score >= 75:
            explanations.append({
                'feature': 'Title Quality',
                'value': f'{title_score:.0f}/100',
                'impact': '+5',
                'direction': 'positive',
                'explanation': 'Strong title with good hooks and length'
            })
        elif title_score < 40:
            explanations.append({
                'feature': 'Title Quality',
                'value': f'{title_score:.0f}/100',
                'impact': '-5',
                'direction': 'negative',
                'explanation': 'Title lacks hooks—add emotion, numbers, or questions'
            })
        
        # Overall thumbnail score summary
        thumbnail_score = features.get('thumbnail_score', 50)
        if thumbnail_score >= 75:
            explanations.append({
                'feature': 'Thumbnail Quality',
                'value': f'{thumbnail_score:.0f}/100',
                'impact': '+5',
                'direction': 'positive',
                'explanation': 'Strong thumbnail with good colors and composition'
            })
        elif thumbnail_score < 40:
            explanations.append({
                'feature': 'Thumbnail Quality',
                'value': f'{thumbnail_score:.0f}/100',
                'impact': '-5',
                'direction': 'negative',
                'explanation': 'Thumbnail needs work—improve brightness, add face, or boost colors'
            })
        
        # Sort by absolute impact (now just integers)
        explanations.sort(key=lambda x: abs(int(str(x['impact']).replace('+', '').replace('-', ''))), reverse=True)
        
        return explanations[:8]  # Top 8
    
    def _generate_recommendations(
        self,
        features: Dict[str, float],
        explanations: List[Dict[str, Any]],
        channel_features: Optional[Dict] = None
    ) -> List[str]:
        """Generate actionable recommendations based on video and channel context."""
        recommendations = []
        priority_recs = []  # High priority recommendations
        
        # Get scores upfront for context-aware recommendations
        title_score = features.get('title_score', 50)
        thumbnail_score = features.get('thumbnail_score', 50)
        niche = features.get('niche', 'General')
        
        # ============================================
        # EVALUATION MODE: Recommendations based on actual performance
        # ============================================
        if features.get('is_evaluation'):
            actual_views = features.get('actual_views', 0)
            performance_ratio = features.get('performance_ratio', 1.0)
            video_view_sub_ratio = features.get('video_view_sub_ratio', 0)
            
            if performance_ratio >= 2.0:
                priority_recs.append(f"🏆 This video is a HIT! {actual_views:,} views = {performance_ratio:.1f}x your median")
                priority_recs.append("📝 Study this video's title/thumbnail formula and replicate it")
            elif performance_ratio >= 1.0:
                priority_recs.append(f"✅ Solid performer! {actual_views:,} views = above your median")
                recommendations.append("This format is working - consider creating more content like this")
            else:
                # Underperforming - give context-aware advice
                priority_recs.append(f"📊 Below your typical performance ({performance_ratio:.0%} of median)")
                
                # Diagnose WHY it underperformed based on packaging quality
                if title_score >= 60 and thumbnail_score >= 60:
                    # Packaging was decent/good, so the issue is elsewhere
                    priority_recs.append(f"✅ Packaging was solid (Title: {title_score:.0f}, Thumb: {thumbnail_score:.0f})")
                    
                    # Give specific non-packaging insights
                    recommendations.append("🎯 Topic may not have resonated with your audience")
                    recommendations.append("📅 Check posting time—was it optimal for your viewers?")
                    recommendations.append("🔍 Look at impressions in YouTube Studio—low impressions = algorithm didn't push it")
                    recommendations.append("🏆 Compare to your hits: what topic/format differences do you notice?")
                    
                    if video_view_sub_ratio and video_view_sub_ratio < 0.3:
                        recommendations.append("📢 Low reach suggests the video didn't get recommended beyond subscribers")
                        
                elif title_score < 50 and thumbnail_score < 50:
                    recommendations.append("⚠️ Both title and thumbnail were weak—prioritize packaging on future videos")
                    recommendations.append("Study your top performers' titles and thumbnails")
                elif title_score < thumbnail_score - 15:
                    recommendations.append(f"Title (score: {title_score:.0f}) was weaker than thumbnail ({thumbnail_score:.0f})")
                    recommendations.append("Weak titles reduce CTR even with great thumbnails")
                    recommendations.append("Next time: test title hooks before publishing")
                elif thumbnail_score < title_score - 15:
                    recommendations.append(f"Thumbnail (score: {thumbnail_score:.0f}) was weaker than title ({title_score:.0f})")
                    recommendations.append("Weak thumbnails are the #1 CTR killer")
                    recommendations.append("Next time: create 3+ thumbnail variations and pick the strongest")
                else:
                    recommendations.append("Compare this video's title/thumbnail to your better performers")
                    recommendations.append("Small packaging improvements compound over time")
            
            if video_view_sub_ratio >= 2.0:
                priority_recs.append(f"🚀 Excellent reach! This video got {video_view_sub_ratio:.1f}x your subscriber count")
            elif video_view_sub_ratio >= 1.0:
                recommendations.append("Good reach - this video matched your subscriber count in views")
            elif video_view_sub_ratio < 0.3 and video_view_sub_ratio > 0:
                recommendations.append("Low reach beyond subscribers—consider more shareable hooks or trending topics")
            
            return priority_recs + recommendations[:4]  # Max 6 recommendations
        
        # ============================================
        # VELOCITY MODE: Recommendations for 1-7 day old videos
        # ============================================
        if features.get('is_velocity') and features.get('velocity_prediction'):
            velocity_pred = features.get('velocity_prediction', {})
            predicted_views = velocity_pred.get('predicted_views_day30', 0)
            trajectory = velocity_pred.get('trajectory', 'normal')
            vs_expected = velocity_pred.get('vs_expected', 1.0)
            vph = velocity_pred.get('views_per_hour', 0)
            milestones = velocity_pred.get('milestones', [])
            engagement_rate = features.get('engagement_rate', 0)
            video_age_days = features.get('video_age_days', 1)
            
            # Format milestone summary
            milestone_summary = ""
            if milestones:
                next_milestone = milestones[0]
                m_name = next_milestone.get('milestone', '').replace('_', ' ').title()
                m_views = next_milestone.get('predicted_views', 0)
                milestone_summary = f" → {m_views:,} by {m_name}"
            
            if trajectory in ('viral', 'strong'):
                priority_recs.append(f"🚀 {trajectory.title()} trajectory! {predicted_views:,} views by Day 30{milestone_summary}")
                priority_recs.append("📢 Promote this video now while momentum is high")
                recommendations.append("Reply to comments to boost engagement and extend reach")
                recommendations.append("Pin a comment with a CTA to drive subscriptions")
                # Add context about what's working
                if title_score >= 70:
                    recommendations.append(f"Title is performing well (score: {title_score:.0f})—use similar hooks in future videos")
                if thumbnail_score >= 70:
                    recommendations.append(f"Thumbnail is strong (score: {thumbnail_score:.0f})—save this style for reference")
                    
            elif trajectory == 'above_average':
                priority_recs.append(f"📈 Above average momentum! {predicted_views:,} by Day 30{milestone_summary}")
                recommendations.append("Share to social media to boost visibility")
                recommendations.append("Create a community post linking to this video")
                if engagement_rate and engagement_rate > 5:
                    recommendations.append(f"High engagement ({engagement_rate:.1f}%)—algorithm will likely extend reach")
                    
            elif trajectory == 'normal':
                priority_recs.append(f"📊 On track - {predicted_views:,} views by Day 30{milestone_summary}")
                
                # Context-aware suggestions based on what's weak
                if title_score >= 65 and thumbnail_score >= 65:
                    # Packaging is good - give promotion advice instead
                    recommendations.append("✅ Title & thumbnail are solid—boost with promotion")
                    recommendations.append("🎬 Create a Short teaser to drive more traffic")
                    recommendations.append("💬 Engage with early comments to signal activity")
                    if engagement_rate and engagement_rate >= 4:
                        recommendations.append("📈 Good engagement—audience likes it, help algorithm find more viewers")
                elif title_score < 50 and thumbnail_score >= 60:
                    recommendations.append(f"Title (score: {title_score:.0f}) may be limiting CTR")
                    recommendations.append("Consider A/B testing a new hook while views are building")
                elif thumbnail_score < 50 and title_score >= 60:
                    recommendations.append(f"Thumbnail (score: {thumbnail_score:.0f}) may be limiting CTR")
                    recommendations.append("Try a brighter/more expressive thumbnail version")
                elif title_score < 65 and thumbnail_score < 65:
                    recommendations.append("Both title and thumbnail have room to improve")
                    recommendations.append("If views stall by Day 3, update packaging")
                else:
                    recommendations.append("Consider creating a YouTube Short linking to this video")
                    
            else:  # slow or struggling
                priority_recs.append(f"⚠️ Slow start - {vph:.0f} views/hour{milestone_summary}")
                
                # Smart diagnosis based on scores
                if title_score >= 60 and thumbnail_score >= 60:
                    # Good packaging, other factors at play - give actionable non-packaging advice
                    priority_recs.append(f"✅ Packaging is solid (Title: {title_score:.0f}, Thumb: {thumbnail_score:.0f})—focus on distribution")
                    
                    # Promotion strategies
                    recommendations.append("📱 Share to Instagram/Twitter/TikTok with a hook clip")
                    recommendations.append("💬 Post in relevant Reddit/Discord communities (don't spam)")
                    recommendations.append("🎬 Create a YouTube Short teaser linking to this video")
                    
                    # YouTube-specific tactics
                    if video_age_days <= 2:
                        recommendations.append("⏳ Day 1-2 is testing phase—YouTube may increase impressions after 48hrs")
                    recommendations.append("📌 Pin a comment asking a question to boost engagement")
                    recommendations.append("🔗 Add end screens from your popular videos to drive traffic here")
                    
                    # Topic/timing insights
                    if engagement_rate and engagement_rate > 4:
                        recommendations.append("💡 High engagement suggests topic resonates—low impressions may be the issue")
                    else:
                        recommendations.append("🎯 Consider if this topic matches what your audience typically watches")
                        
                elif title_score < 50 and thumbnail_score >= 60:
                    priority_recs.append(f"Title (score: {title_score:.0f}) is likely hurting CTR")
                    recommendations.append("Rewrite title with a stronger hook—your thumbnail is fine")
                    recommendations.append("Try: curiosity gap, specific numbers, or emotional words")
                    recommendations.append("Example hooks: 'I Finally...', 'The Truth About...', 'X Things You Need...'")
                elif thumbnail_score < 50 and title_score >= 60:
                    priority_recs.append(f"Thumbnail (score: {thumbnail_score:.0f}) is likely hurting CTR")
                    recommendations.append("Update thumbnail—your title is fine")
                    if not features.get('has_face'):
                        recommendations.append("Add a face with expression to thumbnail")
                    if features.get('brightness', 0.5) < 0.4:
                        recommendations.append("Increase brightness—dark thumbnails get skipped")
                    if features.get('saturation', 0.5) < 0.35:
                        recommendations.append("Boost color saturation to stand out in feeds")
                elif title_score < 60 and thumbnail_score < 60:
                    priority_recs.append("Both title and thumbnail need work")
                    recommendations.append("Priority 1: Update thumbnail (has bigger CTR impact)")
                    recommendations.append("Priority 2: Strengthen title hook")
                    recommendations.append("📱 Also promote on social while you optimize")
                else:
                    # Moderate scores (50-60) - still room to improve but also consider other factors
                    priority_recs.append("Packaging is decent but has room for improvement")
                    recommendations.append("Test a new thumbnail variation—small changes can boost CTR")
                    recommendations.append("Try tweaking title hook while keeping core topic")
                    recommendations.append("📱 Promote to kickstart the algorithm")
            
            # Show next milestone target
            if len(milestones) >= 2:
                m2 = milestones[1]
                m2_name = m2.get('milestone', '').replace('_', ' ').title()
                m2_views = m2.get('predicted_views', 0)
                recommendations.append(f"📅 Target: {m2_views:,} views by {m2_name}")
            
            if vs_expected >= 1.5:
                recommendations.append(f"✨ Outperforming expectations by {(vs_expected-1)*100:.0f}%!")
            elif vs_expected < 0.7 and trajectory not in ('slow', 'struggling'):
                recommendations.append("Slightly behind expected pace—active promotion could help")
            
            return priority_recs + recommendations[:6]  # Max 8 recommendations
        
        # ============================================
        # PREDICTION MODE: Original recommendations
        # ============================================
        
        # === CHANNEL-SPECIFIC RECOMMENDATIONS ===
        if channel_features:
            hit_rate = channel_features.get('hit_rate', 0.15)
            momentum = channel_features.get('recent_momentum', 0)
            median_views = channel_features.get('median_views', 0)
            avg_views = channel_features.get('avg_views', 0)
            subs = channel_features.get('subscriber_count', 0)
            view_sub_ratio = channel_features.get('view_sub_ratio', 0)
            
            # === ABSOLUTE PERFORMANCE RECOMMENDATIONS ===
            # This is the most important signal
            if view_sub_ratio >= 2.0:
                priority_recs.append(f"🚀 Outstanding reach! Your videos get {view_sub_ratio:.1f}x your subscriber count - you're reaching well beyond your base")
            elif view_sub_ratio >= 1.0:
                priority_recs.append(f"✅ Strong reach ({view_sub_ratio:.1f}x subs) - your content resonates beyond just subscribers")
            elif view_sub_ratio >= 0.5:
                priority_recs.append(f"📊 Decent reach ({view_sub_ratio:.1f}x subs) - focus on shareable hooks to expand beyond subscribers")
            elif view_sub_ratio > 0 and view_sub_ratio < 0.3:
                recommendations.append("Focus on shareable hooks to reach beyond your subscriber base")
            
            # Small channel killing it
            if subs < 10_000 and median_views >= 10_000:
                priority_recs.append(f"🔥 You're outperforming for your channel size! {median_views:,.0f} median views with {subs:,.0f} subs is excellent")
            elif subs < 50_000 and median_views >= 25_000:
                priority_recs.append("💪 Strong performance for your size! Keep this momentum going")
            
            # Momentum-based recommendations
            if momentum > 0.30:
                priority_recs.append("🔥 You're on a hot streak! Your recent videos are crushing it")
            elif momentum > 0.15:
                priority_recs.append("📈 Growing momentum! Your recent content is outperforming your average")
            elif momentum < -0.20:
                recommendations.append("⚠️ Recent videos underperforming vs your average - consider refreshing your format")
            
            # Hit rate recommendations (secondary to absolute metrics)
            if hit_rate >= 0.35:
                priority_recs.append(f"🎯 Excellent hit rate ({hit_rate:.0%})! You consistently make videos that pop")
            elif hit_rate >= 0.25:
                recommendations.append(f"Good hit rate ({hit_rate:.0%}) - you know what resonates with your audience")
        
        # === COMBINED TITLE + THUMBNAIL ANALYSIS ===
        # Give smarter, prioritized recommendations
        title_len = features.get('title_len', 0)
        has_face = features.get('has_face', False)
        brightness = features.get('brightness', 0.5)
        saturation = features.get('saturation', 0.5)
        contrast = features.get('contrast', 0.5)
        emotional = features.get('emotional', 0)
        has_number = features.get('has_number', False)
        has_question = features.get('has_question', False)
        
        # Determine the biggest issue and prioritize
        title_issues = []
        thumb_issues = []
        
        if title_score < 70:
            if title_len > 70:
                title_issues.append(("length", "Too long", "Shorten to 50-60 characters for mobile"))
            elif title_len < 30:
                title_issues.append(("length", "Too short", "Expand with more context (40-60 chars)"))
            if emotional < 0.3:
                title_issues.append(("emotion", "Low emotion", "Add power words (amazing, shocking, ultimate)"))
            if not has_number and not has_question:
                title_issues.append(("hook", "Missing hook", "Add a number or question to create curiosity"))
        
        if thumbnail_score < 70:
            if not has_face:
                thumb_issues.append(("face", "No face", "Add a face—faces increase CTR by ~20%"))
            if brightness < 0.35:
                thumb_issues.append(("brightness", "Too dark", "Increase brightness for feed visibility"))
            if saturation < 0.3:
                thumb_issues.append(("saturation", "Low color", "Boost saturation to stand out"))
            if contrast < 0.3:
                thumb_issues.append(("contrast", "Flat", "Add contrast—make elements pop"))
        
        # Smart prioritization based on score gap
        score_gap = abs(title_score - thumbnail_score)
        
        if title_score >= 70 and thumbnail_score >= 70:
            # Both are strong
            priority_recs.append(f"✅ Title ({title_score:.0f}) and thumbnail ({thumbnail_score:.0f}) are both strong")
            if title_score >= 80 and thumbnail_score >= 80:
                recommendations.append("Excellent packaging—focus on content quality and promotion")
        elif title_score >= 70 and thumbnail_score < 70:
            # Title strong, thumbnail weak
            priority_recs.append(f"⚠️ Thumbnail (score: {thumbnail_score:.0f}) is limiting your CTR")
            for _, _, fix in thumb_issues[:2]:  # Top 2 thumbnail fixes
                recommendations.append(fix)
            recommendations.append(f"Title is good ({title_score:.0f})—no changes needed there")
        elif thumbnail_score >= 70 and title_score < 70:
            # Thumbnail strong, title weak
            priority_recs.append(f"⚠️ Title (score: {title_score:.0f}) is limiting your CTR")
            for _, _, fix in title_issues[:2]:  # Top 2 title fixes
                recommendations.append(fix)
            recommendations.append(f"Thumbnail is good ({thumbnail_score:.0f})—no changes needed there")
        elif title_score < 50 and thumbnail_score < 50:
            # Both weak
            priority_recs.append("⚠️ Both title and thumbnail need significant improvement")
            recommendations.append("Priority 1: Fix thumbnail (bigger impact on CTR)")
            if thumb_issues:
                recommendations.append(f"Thumbnail: {thumb_issues[0][2]}")
            recommendations.append("Priority 2: Strengthen title hook")
            if title_issues:
                recommendations.append(f"Title: {title_issues[0][2]}")
        else:
            # Moderate scores - give specific fixes
            if title_issues:
                recommendations.append(f"Title ({title_score:.0f}): {title_issues[0][2]}")
            if thumb_issues:
                recommendations.append(f"Thumbnail ({thumbnail_score:.0f}): {thumb_issues[0][2]}")
        
        # Niche-specific advice
        if niche and niche != 'General':
            niche_lower = niche.lower()
            if 'gaming' in niche_lower and not has_face:
                recommendations.append("Gaming tip: Reaction faces in thumbnails boost CTR significantly")
            elif 'education' in niche_lower and emotional < 0.3:
                recommendations.append("Education tip: Titles like 'You need to know...' perform +80% better")
            elif 'music' in niche_lower and 'official' not in features.get('title', '').lower():
                recommendations.append("Music tip: Adding 'Official' can boost views significantly")
        
        # Combine priority + regular recommendations
        all_recs = priority_recs + recommendations
        return all_recs[:7]  # Top 7
    
    def _determine_niche(self, channel_id: str) -> str:
        """Determine the channel's niche."""
        try:
            from src.database.connection import get_session
            from src.database.models import Channel
            
            with get_session() as session:
                channel = session.query(Channel).filter_by(channel_id=channel_id).first()
                if channel:
                    return channel.primary_category
        except Exception as e:
            logger.debug("analyze.niche_lookup_failed", channel_id=channel_id, error=str(e))
        
        return "General"
    
    def _get_niche_comparison(
        self, 
        score: float, 
        niche: str, 
        channel_features: Optional[Dict] = None,
        video_features: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Get comparison to niche benchmarks with real channel context."""
        
        # Determine mode from video features
        is_evaluation = video_features.get('is_evaluation', False) if video_features else False
        is_velocity = video_features.get('is_velocity', False) if video_features else False
        video_age_days = video_features.get('video_age_days', 0) if video_features else 0
        
        # Calculate percentile based on score
        # Score of 50 = 50th percentile, 75 = 90th percentile, 90 = 99th percentile
        if score >= 90:
            percentile = 99
        elif score >= 75:
            percentile = 90 + int((score - 75) * 0.6)
        elif score >= 50:
            percentile = 50 + int((score - 50) * 1.6)
        else:
            percentile = max(1, int(score))
        
        # Determine mode and description
        if is_evaluation:
            mode = 'evaluation'
            mode_desc = f'Based on actual performance ({video_age_days} days since upload)'
        elif is_velocity:
            mode = 'velocity'
            mode_desc = f'Early signals analysis ({video_age_days} days since upload)'
        else:
            mode = 'prediction'
            mode_desc = 'Predicted performance before upload' if video_age_days == 0 else f'Fresh upload ({video_age_days} days old)'
        
        comparison = {
            'niche': niche,
            'your_score': float(round(score, 1)),
            'niche_average': 50.0,
            'top_10_threshold': 75.0,
            'top_1_threshold': 90.0,
            'percentile': int(percentile),
            'analysis_mode': mode,
            'mode_description': mode_desc,
            'video_age_days': video_age_days,
        }
        
        # Add actual performance data if in evaluation mode
        if is_evaluation and video_features:
            comparison['actual_performance'] = {
                'views': int(video_features.get('actual_views', 0)),
                'vs_median': float(round(video_features.get('performance_ratio', 1.0), 2)),
                'view_sub_ratio': float(round(video_features.get('video_view_sub_ratio', 0), 2)),
                'engagement': video_features.get('engagement'),
            }
        
        # Add velocity prediction data if in velocity mode
        if is_velocity and video_features and video_features.get('velocity_prediction'):
            velocity_pred = video_features.get('velocity_prediction', {})
            comparison['velocity_prediction'] = {
                'predicted_views_day30': int(velocity_pred.get('predicted_views_day30', 0)),
                'trajectory': velocity_pred.get('trajectory', 'normal'),
                'percentile': int(velocity_pred.get('percentile', 50)),
                'confidence': float(round(velocity_pred.get('confidence', 0.5), 2)),
                'views_per_hour': float(round(velocity_pred.get('views_per_hour', 0), 1)),
                'vs_expected': float(round(velocity_pred.get('vs_expected', 1.0), 2)),
                'expected_at_this_point': int(velocity_pred.get('expected_at_this_point', 0)),
                'engagement': velocity_pred.get('engagement'),
                'milestones': velocity_pred.get('milestones', []),
            }
        
        # Add channel-specific context if available
        if channel_features:
            channel_name = channel_features.get('channel_name', 'Your Channel')
            avg_views = channel_features.get('avg_views', 0)
            median_views = channel_features.get('median_views', 0)
            hit_rate = channel_features.get('hit_rate', 0.15)
            momentum = channel_features.get('recent_momentum', 0)
            subs = channel_features.get('subscriber_count', 0)
            view_sub_ratio = channel_features.get('view_sub_ratio', 0)
            
            comparison['channel_context'] = {
                'channel_name': channel_name,
                'subscriber_count': int(subs) if subs else 0,
                'avg_views': int(avg_views) if avg_views else 0,
                'median_views': int(median_views) if median_views else 0,
                'view_sub_ratio': float(round(view_sub_ratio, 2)),  # Key metric!
                'view_sub_label': self._get_view_sub_label(view_sub_ratio),
                'hit_rate': float(round(hit_rate * 100, 1)),  # As percentage
                'hit_rate_label': self._get_hit_rate_label(hit_rate),
                'momentum': float(round(momentum * 100, 1)),  # As percentage
                'momentum_label': self._get_momentum_label(momentum),
            }
            
            # How this video compares to channel's average
            if avg_views > 0:
                expected_views = avg_views * (score / 50)  # Score 50 = average
                comparison['expected_performance'] = {
                    'expected_views': int(expected_views),
                    'vs_channel_avg': f"{(score / 50 - 1) * 100:+.0f}%" if score != 50 else "Average",
                    'expected_tier': 'above' if score > 55 else 'average' if score > 45 else 'below',
                }
        
        return comparison
    
    def _get_hit_rate_label(self, hit_rate: float) -> str:
        """Get human-readable label for hit rate."""
        if hit_rate >= 0.35:
            return "Exceptional - Consistently makes hits"
        elif hit_rate >= 0.25:
            return "Strong - Above average hit maker"
        elif hit_rate >= 0.15:
            return "Average - Normal performance"
        elif hit_rate >= 0.08:
            return "Below Average - Struggling to hit"
        else:
            return "Low - Rarely breaks out"
    
    def _get_momentum_label(self, momentum: float) -> str:
        """Get human-readable label for momentum."""
        if momentum >= 0.20:
            return "🔥 Hot - Recent videos outperforming"
        elif momentum >= 0.05:
            return "📈 Growing - Positive trend"
        elif momentum >= -0.05:
            return "➡️ Stable - Consistent performance"
        elif momentum >= -0.20:
            return "📉 Declining - Recent dip"
        else:
            return "⚠️ Cold - Significant drop"
    
    def _get_view_sub_label(self, ratio: float) -> str:
        """Get human-readable label for view/subscriber ratio."""
        if ratio >= 5.0:
            return "🚀 Viral reach - Far exceeding subscriber base"
        elif ratio >= 2.0:
            return "🔥 Excellent reach - Strong viral potential"
        elif ratio >= 1.0:
            return "✅ Strong reach - Matching subscriber count"
        elif ratio >= 0.5:
            return "📊 Good reach - Engaging half your subs"
        elif ratio >= 0.2:
            return "➡️ Average reach - Typical for most channels"
        elif ratio > 0:
            return "📉 Low reach - Most subs not watching"
        else:
            return "Unknown"
    
    def _get_channel_name(self, channel_id: str, channel_features: Optional[Dict] = None) -> str:
        """Get channel name from features, database, or API."""
        # First check cached features
        if channel_features and channel_features.get('channel_name'):
            return channel_features['channel_name']
        
        try:
            from src.database.connection import get_session
            from src.database.models import Channel
            
            with get_session() as session:
                channel = session.query(Channel).filter_by(channel_id=channel_id).first()
                if channel:
                    return channel.channel_name
        except Exception as e:
            logger.debug("analyze.channel_name_lookup_failed", channel_id=channel_id, error=str(e))
        
        return "Unknown Channel"


# Singleton instance
_analyzer = None


def get_analyzer() -> VideoAnalyzer:
    """Get or create the video analyzer singleton."""
    global _analyzer
    if _analyzer is None:
        _analyzer = VideoAnalyzer()
    return _analyzer


def analyze_video(url: str, channel_id: Optional[str] = None) -> AnalysisResult:
    """
    Convenience function to analyze a video.
    
    Args:
        url: YouTube video URL
        channel_id: Optional channel ID for context
        
    Returns:
        AnalysisResult
    """
    analyzer = get_analyzer()
    return analyzer.analyze(url, channel_id)

