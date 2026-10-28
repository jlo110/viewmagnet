"""
Similar Video Finder

Finds successful videos similar to the user's title/topic.
Uses sentence embeddings for semantic similarity.
"""

import numpy as np
from dataclasses import dataclass
from typing import List
from sqlalchemy import and_, desc
from sentence_transformers import SentenceTransformer
from src.database.models import Video, VideoFeatures, Channel
from src.database.connection import get_session
import logging

logger = logging.getLogger(__name__)

EMBEDDER_NAME = "all-MiniLM-L6-v2"


@dataclass
class SimilarVideo:
    """A similar successful video."""
    video_id: str
    title: str
    view_count: int
    channel_name: str
    performance_ratio: float  # views / channel avg
    has_face: bool
    has_text: bool
    title_length: int
    similarity_score: float


class SimilarVideoFinder:
    """Finds similar successful videos using semantic search."""
    
    def __init__(self):
        self.embedder = None
        self.video_cache = {}  # category -> list of (embedding, video_data)
        self._loaded_categories = set()
    
    def _ensure_embedder(self):
        if self.embedder is None:
            logger.info(f"Loading embedder: {EMBEDDER_NAME}")
            self.embedder = SentenceTransformer(EMBEDDER_NAME)
    
    def _load_category_videos(self, category: str, min_performance: float = 1.5):
        """Load successful videos from a category into cache."""
        if category in self._loaded_categories:
            return
        
        logger.info(f"Loading successful videos for category: {category}")
        
        with get_session() as session:
            # Get high-performing videos in this category
            results = session.query(
                Video.video_id,
                Video.title,
                Video.view_count,
                Channel.channel_name,
                Channel.avg_views_per_video,
                VideoFeatures.has_face,
                VideoFeatures.has_text,
                VideoFeatures.title_char_length,
            ).join(
                VideoFeatures, Video.video_id == VideoFeatures.video_id
            ).join(
                Channel, Video.channel_id == Channel.channel_id
            ).filter(and_(
                Channel.primary_category == category,
                Video.view_count >= 10000,  # Minimum views
                Channel.avg_views_per_video > 0,
                Video.title.isnot(None)
            )).order_by(
                desc(Video.view_count / Channel.avg_views_per_video)
            ).limit(500).all()  # Top 500 performers
        
        if not results:
            self._loaded_categories.add(category)
            self.video_cache[category] = []
            return
        
        # Generate embeddings for all titles
        self._ensure_embedder()
        titles = [r.title for r in results]
        embeddings = self.embedder.encode(titles, show_progress_bar=False)
        
        # Store in cache
        video_data = []
        for i, r in enumerate(results):
            perf_ratio = r.view_count / r.avg_views_per_video if r.avg_views_per_video > 0 else 1
            if perf_ratio >= min_performance:  # Only keep high performers
                video_data.append({
                    'embedding': embeddings[i],
                    'video_id': r.video_id,
                    'title': r.title,
                    'view_count': r.view_count,
                    'channel_name': r.channel_name,
                    'performance_ratio': perf_ratio,
                    'has_face': r.has_face,
                    'has_text': r.has_text,
                    'title_length': r.title_char_length or len(r.title),
                })
        
        self.video_cache[category] = video_data
        self._loaded_categories.add(category)
        logger.info(f"Cached {len(video_data)} successful videos for {category}")
    
    def find_similar(self, title: str, category: str, top_k: int = 5) -> List[SimilarVideo]:
        """
        Find similar successful videos.
        
        Args:
            title: User's video title
            category: User's channel category
            top_k: Number of similar videos to return
        
        Returns:
            List of similar successful videos
        """
        self._ensure_embedder()
        self._load_category_videos(category)
        
        if category not in self.video_cache or not self.video_cache[category]:
            # Try to find from any category
            return self._find_similar_global(title, top_k)
        
        # Embed the user's title
        user_embedding = self.embedder.encode([title])[0]
        
        # Calculate similarities
        similarities = []
        for video_data in self.video_cache[category]:
            sim = np.dot(user_embedding, video_data['embedding']) / (
                np.linalg.norm(user_embedding) * np.linalg.norm(video_data['embedding'])
            )
            similarities.append((sim, video_data))
        
        # Sort by similarity
        similarities.sort(key=lambda x: x[0], reverse=True)
        
        # Return top K
        results = []
        for sim, data in similarities[:top_k]:
            results.append(SimilarVideo(
                video_id=data['video_id'],
                title=data['title'],
                view_count=data['view_count'],
                channel_name=data['channel_name'],
                performance_ratio=data['performance_ratio'],
                has_face=data['has_face'],
                has_text=data['has_text'],
                title_length=data['title_length'],
                similarity_score=sim,
            ))
        
        return results
    
    def _find_similar_global(self, title: str, top_k: int = 5) -> List[SimilarVideo]:
        """Find similar videos across all categories."""
        logger.info("Finding similar videos globally (no category cache)")
        
        with get_session() as session:
            # Get top performing videos globally
            results = session.query(
                Video.video_id,
                Video.title,
                Video.view_count,
                Channel.channel_name,
                Channel.avg_views_per_video,
                VideoFeatures.has_face,
                VideoFeatures.has_text,
                VideoFeatures.title_char_length,
            ).join(
                VideoFeatures, Video.video_id == VideoFeatures.video_id
            ).join(
                Channel, Video.channel_id == Channel.channel_id
            ).filter(and_(
                Video.view_count >= 100000,
                Channel.avg_views_per_video > 0,
                Video.title.isnot(None)
            )).order_by(
                desc(Video.view_count)
            ).limit(200).all()
        
        if not results:
            return []
        
        # Embed all titles
        self._ensure_embedder()
        titles = [r.title for r in results]
        embeddings = self.embedder.encode(titles, show_progress_bar=False)
        user_embedding = self.embedder.encode([title])[0]
        
        # Calculate similarities
        similarities = []
        for i, r in enumerate(results):
            sim = np.dot(user_embedding, embeddings[i]) / (
                np.linalg.norm(user_embedding) * np.linalg.norm(embeddings[i])
            )
            perf_ratio = r.view_count / r.avg_views_per_video if r.avg_views_per_video > 0 else 1
            similarities.append((sim, r, perf_ratio))
        
        # Sort by similarity
        similarities.sort(key=lambda x: x[0], reverse=True)
        
        # Return top K
        results = []
        for sim, r, perf_ratio in similarities[:top_k]:
            results.append(SimilarVideo(
                video_id=r.video_id,
                title=r.title,
                view_count=r.view_count,
                channel_name=r.channel_name,
                performance_ratio=perf_ratio,
                has_face=r.has_face,
                has_text=r.has_text,
                title_length=r.title_char_length or len(r.title),
                similarity_score=sim,
            ))
        
        return results


# Singleton instance
_similar_finder = None

def get_similar_finder() -> SimilarVideoFinder:
    global _similar_finder
    if _similar_finder is None:
        _similar_finder = SimilarVideoFinder()
    return _similar_finder

