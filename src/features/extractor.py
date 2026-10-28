"""Main feature extraction orchestrator."""
from dataclasses import dataclass
from typing import Optional, List
import structlog

from sqlalchemy.orm import Session

from src.database.models import Video, VideoFeatures, Channel
from src.features.title_analyzer import TitleAnalyzer
from src.features.thumbnail_analyzer import ThumbnailAnalyzer
from src.features.metadata_analyzer import MetadataAnalyzer

logger = structlog.get_logger()


@dataclass
class ExtractionResult:
    """Result of feature extraction."""
    video_id: str
    title_extracted: bool
    thumbnail_extracted: bool
    metadata_extracted: bool
    error: Optional[str] = None


class FeatureExtractor:
    """
    Orchestrates feature extraction for videos.
    
    Week 3-4: Benchmark Feature Extraction
    - Extracts title, thumbnail, and metadata features
    - Saves to VideoFeatures table
    """
    
    def __init__(
        self,
        session: Session,
        enable_face_detection: bool = False,
        enable_emotion_detection: bool = False,
        enable_thumbnail_download: bool = True,
    ):
        """
        Initialize extractor.
        
        Args:
            session: SQLAlchemy session
            enable_face_detection: Use OpenCV for face detection
            enable_emotion_detection: Use DeepFace for emotion detection
            enable_thumbnail_download: Download and analyze thumbnails
        """
        self.session = session
        self.enable_thumbnail_download = enable_thumbnail_download
        
        self.title_analyzer = TitleAnalyzer()
        self.thumbnail_analyzer = ThumbnailAnalyzer(
            enable_face_detection=enable_face_detection,
            enable_emotion_detection=enable_emotion_detection,
        )
        self.metadata_analyzer = MetadataAnalyzer()
        
        # Cache for channel categories
        self._channel_categories: dict = {}
    
    def extract_for_video(self, video: Video) -> ExtractionResult:
        """
        Extract all features for a single video.
        
        Args:
            video: Video model instance
            
        Returns:
            ExtractionResult with status
        """
        result = ExtractionResult(
            video_id=video.video_id,
            title_extracted=False,
            thumbnail_extracted=False,
            metadata_extracted=False,
        )
        
        try:
            # Check if features already exist
            existing = self.session.query(VideoFeatures).filter(
                VideoFeatures.video_id == video.video_id
            ).first()
            
            if existing:
                # Update existing record
                features = existing
            else:
                # Create new record
                features = VideoFeatures(video_id=video.video_id)
                self.session.add(features)
            
            # Extract title features
            try:
                title_features = self.title_analyzer.analyze(video.title)
                features.title_char_length = title_features.char_length
                features.title_word_count = title_features.word_count
                features.title_has_number = title_features.has_number
                features.title_number_position = title_features.number_position
                features.title_has_question = title_features.has_question
                features.title_has_exclamation = title_features.has_exclamation
                features.title_has_brackets = title_features.has_brackets
                features.title_caps_ratio = title_features.caps_ratio
                features.title_hook_type = title_features.hook_type
                features.title_emotional_score = title_features.emotional_score
                features.title_sentiment = title_features.sentiment
                features.title_trending_score = title_features.trending_score
                features.title_specificity_score = title_features.specificity_score
                features.title_processed = True
                result.title_extracted = True
            except Exception as e:
                logger.error("title_extraction_error", video_id=video.video_id, error=str(e))
            
            # Extract thumbnail features
            if self.enable_thumbnail_download and video.thumbnail_url:
                try:
                    thumb_features = self.thumbnail_analyzer.analyze_from_url_sync(
                        video.thumbnail_url
                    )
                    if thumb_features:
                        features.face_count = thumb_features.face_count
                        features.face_area_ratio = thumb_features.face_area_ratio
                        features.has_face = thumb_features.has_face
                        features.face_emotion_primary = thumb_features.face_emotion_primary
                        features.face_emotion_intensity = thumb_features.face_emotion_intensity
                        features.has_text = thumb_features.has_text
                        features.text_area_ratio = thumb_features.text_area_ratio
                        features.dominant_color_1 = thumb_features.dominant_color_1
                        features.dominant_color_2 = thumb_features.dominant_color_2
                        features.dominant_color_3 = thumb_features.dominant_color_3
                        features.brightness = thumb_features.brightness
                        features.saturation = thumb_features.saturation
                        features.contrast = thumb_features.contrast
                        features.visual_complexity = thumb_features.visual_complexity
                        features.edge_density = thumb_features.edge_density
                        features.composition_score = thumb_features.composition_score
                        features.thumbnail_processed = True
                        result.thumbnail_extracted = True
                except Exception as e:
                    logger.debug("thumbnail_extraction_error", video_id=video.video_id, error=str(e))
            
            # Extract metadata features
            try:
                category = self._get_channel_category(video.channel_id)
                meta_features = self.metadata_analyzer.analyze(
                    duration_seconds=video.duration_seconds,
                    published_at=video.published_at,
                    tags=video.tags,
                    category=category,
                )
                features.duration_seconds = meta_features.duration_seconds
                features.duration_category_ratio = meta_features.duration_category_ratio
                features.posting_day_of_week = meta_features.posting_day_of_week
                features.posting_hour = meta_features.posting_hour
                features.tags_count = meta_features.tags_count
                result.metadata_extracted = True
            except Exception as e:
                logger.error("metadata_extraction_error", video_id=video.video_id, error=str(e))
            
            # Mark video as processed
            video.features_extracted = True
            self.session.commit()
            
        except Exception as e:
            result.error = str(e)
            logger.error("extraction_error", video_id=video.video_id, error=str(e))
            self.session.rollback()
        
        return result
    
    def extract_batch(
        self,
        max_videos: Optional[int] = None,
        skip_thumbnails: bool = False,
    ) -> List[ExtractionResult]:
        """
        Extract features for multiple videos.
        
        Args:
            max_videos: Maximum videos to process
            skip_thumbnails: Skip thumbnail download (faster)
            
        Returns:
            List of ExtractionResult
        """
        # Temporarily disable thumbnails if requested
        original_thumbnail_setting = self.enable_thumbnail_download
        if skip_thumbnails:
            self.enable_thumbnail_download = False
        
        # Get videos that need processing
        query = self.session.query(Video).filter(
            Video.features_extracted == False
        )
        
        if max_videos:
            query = query.limit(max_videos)
        
        videos = query.all()
        
        logger.info("starting_feature_extraction", videos=len(videos))
        
        results = []
        for i, video in enumerate(videos):
            result = self.extract_for_video(video)
            results.append(result)
            
            # Log progress every 100 videos
            if (i + 1) % 100 == 0:
                success = sum(1 for r in results if r.title_extracted)
                logger.info(
                    "extraction_progress",
                    processed=i + 1,
                    total=len(videos),
                    success_rate=f"{success / (i + 1) * 100:.1f}%"
                )
        
        # Restore thumbnail setting
        self.enable_thumbnail_download = original_thumbnail_setting
        
        # Summary
        title_count = sum(1 for r in results if r.title_extracted)
        thumb_count = sum(1 for r in results if r.thumbnail_extracted)
        meta_count = sum(1 for r in results if r.metadata_extracted)
        
        logger.info(
            "feature_extraction_complete",
            total=len(results),
            titles=title_count,
            thumbnails=thumb_count,
            metadata=meta_count,
        )
        
        return results
    
    def _get_channel_category(self, channel_id: str) -> str:
        """Get category for a channel (cached)."""
        if channel_id not in self._channel_categories:
            channel = self.session.query(Channel).filter(
                Channel.channel_id == channel_id
            ).first()
            
            if channel:
                self._channel_categories[channel_id] = channel.primary_category
            else:
                self._channel_categories[channel_id] = "other"
        
        return self._channel_categories[channel_id]
    
    def get_extraction_stats(self) -> dict:
        """Get current extraction statistics."""
        from sqlalchemy import func
        
        total_videos = self.session.query(func.count(Video.id)).scalar()
        extracted_videos = self.session.query(func.count(Video.id)).filter(
            Video.features_extracted == True
        ).scalar()
        
        total_features = self.session.query(func.count(VideoFeatures.id)).scalar()
        title_processed = self.session.query(func.count(VideoFeatures.id)).filter(
            VideoFeatures.title_processed == True
        ).scalar()
        thumb_processed = self.session.query(func.count(VideoFeatures.id)).filter(
            VideoFeatures.thumbnail_processed == True
        ).scalar()
        
        return {
            "total_videos": total_videos,
            "extracted_videos": extracted_videos,
            "pending_videos": total_videos - extracted_videos,
            "progress_pct": round((extracted_videos / total_videos * 100), 1) if total_videos else 0,
            "features_records": total_features,
            "titles_processed": title_processed,
            "thumbnails_processed": thumb_processed,
        }

