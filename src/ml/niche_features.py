"""
Niche-Relative Features

Calculates how a video's features compare to top performers in its niche.
These relative features are more predictive than raw features alone.
"""
import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass
from sqlalchemy.orm import Session
import structlog

from src.database.models import Video, VideoFeatures, Channel, Niche

logger = structlog.get_logger()


@dataclass
class NicheTopPerformers:
    """Aggregated features from top performers in a niche."""
    niche_id: int
    niche_name: str
    sample_count: int
    
    # Face features
    face_rate: float  # % of thumbnails with faces
    avg_face_count: float
    avg_face_area: float
    
    # Text features
    text_rate: float  # % with text
    avg_text_words: float
    avg_text_area: float
    
    # Visual features
    avg_brightness: float
    avg_saturation: float
    avg_contrast: float
    avg_edge_density: float
    avg_composition: float
    
    # Title features
    avg_title_length: float
    avg_title_words: float
    number_rate: float
    question_rate: float


@dataclass
class NicheRelativeFeatures:
    """How a video compares to its niche top performers."""
    # Face comparison (-1 to 1, 0 = same as niche)
    face_vs_niche: float  # Has face when niche usually doesn't = positive
    face_count_vs_niche: float
    face_area_vs_niche: float
    
    # Text comparison
    text_vs_niche: float
    text_words_vs_niche: float
    
    # Visual comparison
    brightness_vs_niche: float
    saturation_vs_niche: float
    contrast_vs_niche: float
    edge_vs_niche: float
    composition_vs_niche: float
    
    # Title comparison
    title_length_vs_niche: float
    title_words_vs_niche: float
    
    # Similarity score to niche top performers (0-1)
    similarity_to_top: float


class NicheFeatureCalculator:
    """
    Calculates niche-relative features.
    
    These features answer: "How does this video compare to top performers
    in the same niche?"
    """
    
    def __init__(self, session: Session):
        """Initialize calculator."""
        self.session = session
        self._niche_cache: Dict[int, NicheTopPerformers] = {}
    
    def get_niche_benchmarks(self, niche_id: int, top_percentile: int = 25) -> Optional[NicheTopPerformers]:
        """
        Get aggregated features from top performers in a niche.
        
        Args:
            niche_id: Niche ID
            top_percentile: Top X% of videos to consider (by views)
            
        Returns:
            NicheTopPerformers with aggregated features
        """
        if niche_id in self._niche_cache:
            return self._niche_cache[niche_id]
        
        # Get niche info
        niche = self.session.query(Niche).filter(Niche.id == niche_id).first()
        if not niche:
            return None
        
        # Get channel IDs in this niche
        channel_ids = [
            cid for (cid,) in 
            self.session.query(Channel.channel_id).filter(Channel.niche_id == niche_id).all()
        ]
        
        if not channel_ids:
            return None
        
        # Get videos in this niche with features
        videos_query = self.session.query(
            Video.view_count,
            VideoFeatures.face_count,
            VideoFeatures.face_area_ratio,
            VideoFeatures.has_face,
            VideoFeatures.has_text,
            VideoFeatures.text_word_count,
            VideoFeatures.text_area_ratio,
            VideoFeatures.brightness,
            VideoFeatures.saturation,
            VideoFeatures.contrast,
            VideoFeatures.edge_density,
            VideoFeatures.composition_score,
            VideoFeatures.title_char_length,
            VideoFeatures.title_word_count,
            VideoFeatures.title_has_number,
            VideoFeatures.title_has_question,
        ).join(
            VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).filter(
            Video.channel_id.in_(channel_ids),
            Video.view_count > 0,
        ).all()
        
        if len(videos_query) < 10:
            return None
        
        # Sort by views and take top percentile
        videos_sorted = sorted(videos_query, key=lambda x: x[0], reverse=True)
        top_count = max(10, int(len(videos_sorted) * top_percentile / 100))
        top_videos = videos_sorted[:top_count]
        
        # Calculate averages
        def safe_avg(values):
            valid = [v for v in values if v is not None]
            return np.mean(valid) if valid else 0.0
        
        def safe_rate(values):
            valid = [1 if v else 0 for v in values if v is not None]
            return np.mean(valid) if valid else 0.0
        
        benchmarks = NicheTopPerformers(
            niche_id=niche_id,
            niche_name=niche.name,
            sample_count=len(top_videos),
            face_rate=safe_rate([v[3] for v in top_videos]),
            avg_face_count=safe_avg([v[1] for v in top_videos]),
            avg_face_area=safe_avg([v[2] for v in top_videos]),
            text_rate=safe_rate([v[4] for v in top_videos]),
            avg_text_words=safe_avg([v[5] for v in top_videos]),
            avg_text_area=safe_avg([v[6] for v in top_videos]),
            avg_brightness=safe_avg([v[7] for v in top_videos]),
            avg_saturation=safe_avg([v[8] for v in top_videos]),
            avg_contrast=safe_avg([v[9] for v in top_videos]),
            avg_edge_density=safe_avg([v[10] for v in top_videos]),
            avg_composition=safe_avg([v[11] for v in top_videos]),
            avg_title_length=safe_avg([v[12] for v in top_videos]),
            avg_title_words=safe_avg([v[13] for v in top_videos]),
            number_rate=safe_rate([v[14] for v in top_videos]),
            question_rate=safe_rate([v[15] for v in top_videos]),
        )
        
        self._niche_cache[niche_id] = benchmarks
        return benchmarks
    
    def calculate_relative_features(
        self,
        niche_id: int,
        features: Dict,
    ) -> Optional[NicheRelativeFeatures]:
        """
        Calculate how a video's features compare to niche top performers.
        
        Args:
            niche_id: Niche ID
            features: Video features dict
            
        Returns:
            NicheRelativeFeatures with comparison scores
        """
        benchmarks = self.get_niche_benchmarks(niche_id)
        if not benchmarks:
            return None
        
        def compare(value, benchmark, invert=False):
            """Compare value to benchmark, return -1 to 1 score."""
            if benchmark == 0:
                return 0.0
            diff = (value - benchmark) / benchmark
            diff = max(-1, min(1, diff))  # Clip to -1, 1
            return -diff if invert else diff
        
        # Calculate relative features
        has_face = 1 if features.get('has_face', False) else 0
        face_vs_niche = compare(has_face, benchmarks.face_rate)
        
        face_count = features.get('face_count', 0)
        face_count_vs_niche = compare(face_count, benchmarks.avg_face_count)
        
        face_area = features.get('face_area_ratio', 0)
        face_area_vs_niche = compare(face_area, benchmarks.avg_face_area)
        
        has_text = 1 if features.get('has_text', False) else 0
        text_vs_niche = compare(has_text, benchmarks.text_rate)
        
        text_words = features.get('text_word_count', 0)
        text_words_vs_niche = compare(text_words, benchmarks.avg_text_words)
        
        brightness = features.get('brightness', 0.5)
        brightness_vs_niche = compare(brightness, benchmarks.avg_brightness)
        
        saturation = features.get('saturation', 0.5)
        saturation_vs_niche = compare(saturation, benchmarks.avg_saturation)
        
        contrast = features.get('contrast', 0.5)
        contrast_vs_niche = compare(contrast, benchmarks.avg_contrast)
        
        edge = features.get('edge_density', 0.5)
        edge_vs_niche = compare(edge, benchmarks.avg_edge_density)
        
        composition = features.get('composition_score', 0.5)
        composition_vs_niche = compare(composition, benchmarks.avg_composition)
        
        title_length = features.get('title_char_length', 50)
        title_length_vs_niche = compare(title_length, benchmarks.avg_title_length)
        
        title_words = features.get('title_word_count', 8)
        title_words_vs_niche = compare(title_words, benchmarks.avg_title_words)
        
        # Calculate overall similarity to top performers (0-1)
        # Lower absolute differences = higher similarity
        diffs = [
            abs(face_vs_niche),
            abs(brightness_vs_niche),
            abs(saturation_vs_niche),
            abs(composition_vs_niche),
            abs(title_length_vs_niche),
        ]
        similarity_to_top = 1 - np.mean(diffs)
        
        return NicheRelativeFeatures(
            face_vs_niche=face_vs_niche,
            face_count_vs_niche=face_count_vs_niche,
            face_area_vs_niche=face_area_vs_niche,
            text_vs_niche=text_vs_niche,
            text_words_vs_niche=text_words_vs_niche,
            brightness_vs_niche=brightness_vs_niche,
            saturation_vs_niche=saturation_vs_niche,
            contrast_vs_niche=contrast_vs_niche,
            edge_vs_niche=edge_vs_niche,
            composition_vs_niche=composition_vs_niche,
            title_length_vs_niche=title_length_vs_niche,
            title_words_vs_niche=title_words_vs_niche,
            similarity_to_top=similarity_to_top,
        )
    
    def precompute_all_niches(self) -> int:
        """Precompute benchmarks for all niches."""
        niches = self.session.query(Niche).all()
        computed = 0
        
        for niche in niches:
            benchmarks = self.get_niche_benchmarks(niche.id)
            if benchmarks:
                computed += 1
                logger.debug(f"Computed benchmarks for {niche.name}", sample_count=benchmarks.sample_count)
        
        logger.info(f"Computed benchmarks for {computed} niches")
        return computed

