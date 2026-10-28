"""
Niche Clustering - Groups channels into micro-niches.

Uses:
- YouTube category as primary grouping
- Channel tags and keywords  
- Title patterns from videos
- TF-IDF + K-Means clustering
"""
import re
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.metrics import silhouette_score
from sqlalchemy import func
from sqlalchemy.orm import Session
import structlog

from src.database.models import Channel, Video, Niche

logger = structlog.get_logger()

# Progress callback type: (stage: str, current: int, total: int, message: str)
ProgressCallback = Callable[[str, int, int, str], None]


@dataclass
class NicheInfo:
    """Information about a detected niche."""
    niche_id: int
    category: str
    name: str
    keywords: List[str]
    channel_count: int
    avg_subscribers: float
    description: str


class NicheClusterer:
    """
    Clusters channels into micro-niches within each category.
    
    Target: 200-500 micro-niches with 10-50 channels each.
    """
    
    # Target clusters per category (will be adjusted based on channel count)
    MIN_CHANNELS_PER_NICHE = 5
    MAX_CHANNELS_PER_NICHE = 100
    TARGET_NICHES_TOTAL = 300  # Aim for ~300 niches
    
    def __init__(self, session: Session):
        """Initialize clusterer."""
        self.session = session
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            stop_words='english',
            ngram_range=(1, 2),  # Unigrams and bigrams
            min_df=2,  # Must appear in at least 2 documents
            max_df=0.8,  # Ignore terms in >80% of documents
        )
    
    def _get_channel_text(self, channel_id: str) -> str:
        """
        Get combined text representation for a channel.
        
        Combines:
        - Channel description
        - Video titles
        - Video tags (if available)
        """
        # Get channel
        channel = self.session.query(Channel).filter(
            Channel.channel_id == channel_id
        ).first()
        
        if not channel:
            return ""
        
        texts = []
        
        # Add channel description
        if channel.description:
            texts.append(channel.description)
        
        # Add video titles
        videos = self.session.query(Video.title, Video.tags).filter(
            Video.channel_id == channel_id
        ).limit(30).all()
        
        for title, tags in videos:
            if title:
                # Clean title
                clean_title = re.sub(r'[^\w\s]', ' ', title.lower())
                texts.append(clean_title)
            if tags:
                texts.append(tags)
        
        return " ".join(texts)
    
    def _extract_keywords(self, texts: List[str], tfidf_matrix, feature_names: List[str], top_n: int = 10) -> List[str]:
        """Extract top keywords from a cluster based on TF-IDF scores."""
        if len(texts) == 0:
            return []
        
        # Average TF-IDF scores across all documents in cluster
        avg_tfidf = np.asarray(tfidf_matrix.mean(axis=0)).flatten()
        
        # Get top indices
        top_indices = avg_tfidf.argsort()[-top_n:][::-1]
        
        return [feature_names[i] for i in top_indices if avg_tfidf[i] > 0]
    
    def _generate_niche_name(self, category: str, keywords: List[str]) -> str:
        """Generate a descriptive name for a niche."""
        if not keywords:
            return f"{category} - General"
        
        # Use top 2-3 keywords
        key_terms = keywords[:3]
        return f"{category} - {' / '.join(key_terms).title()}"
    
    def cluster_category(
        self,
        category: str,
        n_clusters: Optional[int] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> List[NicheInfo]:
        """
        Cluster channels within a single category.
        
        Args:
            category: YouTube category to cluster
            n_clusters: Number of clusters (auto-determined if None)
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of NicheInfo for each detected niche
        """
        # Get channels in this category
        channels = self.session.query(Channel).filter(
            Channel.primary_category == category,
            Channel.is_active == True
        ).all()
        
        if len(channels) < self.MIN_CHANNELS_PER_NICHE:
            logger.info(f"Not enough channels in {category}", count=len(channels))
            return []
        
        channel_ids = [c.channel_id for c in channels]
        
        # Build text corpus
        logger.info(f"Building text corpus for {category}", channels=len(channels))
        texts = []
        valid_channels = []
        
        for idx, channel in enumerate(channels):
            if progress_callback and idx % 50 == 0:
                progress_callback(
                    "channels", 
                    idx, 
                    len(channels), 
                    f"Building corpus for {category}"
                )
            text = self._get_channel_text(channel.channel_id)
            if text.strip():
                texts.append(text)
                valid_channels.append(channel)
        
        if len(texts) < self.MIN_CHANNELS_PER_NICHE:
            logger.info(f"Not enough text data for {category}")
            return []
        
        # TF-IDF vectorization
        try:
            tfidf_matrix = self.vectorizer.fit_transform(texts)
        except ValueError as e:
            logger.warning(f"TF-IDF failed for {category}: {e}")
            return []
        
        feature_names = self.vectorizer.get_feature_names_out()
        
        # Determine number of clusters
        if n_clusters is None:
            # Aim for 10-50 channels per cluster
            n_clusters = max(2, min(
                len(texts) // 15,  # ~15 channels per niche
                50  # Max 50 niches per category
            ))
        
        n_clusters = min(n_clusters, len(texts) - 1)
        
        logger.info(f"Clustering {category}", n_clusters=n_clusters, documents=len(texts))
        
        # K-Means clustering
        if len(texts) > 1000:
            kmeans = MiniBatchKMeans(n_clusters=n_clusters, random_state=42, n_init=3)
        else:
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        
        labels = kmeans.fit_predict(tfidf_matrix)
        
        # Calculate silhouette score if we have enough samples
        if len(set(labels)) > 1 and len(texts) > n_clusters:
            try:
                score = silhouette_score(tfidf_matrix, labels, sample_size=min(1000, len(texts)))
                logger.info(f"Silhouette score for {category}: {score:.3f}")
            except:
                pass
        
        # Build niche info for each cluster
        niches = []
        
        for cluster_id in range(n_clusters):
            cluster_mask = labels == cluster_id
            cluster_channels = [c for c, m in zip(valid_channels, cluster_mask) if m]
            
            if len(cluster_channels) < self.MIN_CHANNELS_PER_NICHE:
                continue
            
            # Get cluster TF-IDF matrix
            cluster_tfidf = tfidf_matrix[cluster_mask]
            
            # Extract keywords
            keywords = self._extract_keywords(
                [texts[i] for i, m in enumerate(cluster_mask) if m],
                cluster_tfidf,
                feature_names
            )
            
            # Generate name
            name = self._generate_niche_name(category, keywords)
            
            # Calculate stats - convert numpy to native Python types
            avg_subs = float(np.mean([c.subscriber_count or 0 for c in cluster_channels]))
            
            niche_info = NicheInfo(
                niche_id=0,  # Will be assigned after saving
                category=category,
                name=name,
                keywords=keywords,
                channel_count=len(cluster_channels),
                avg_subscribers=avg_subs,
                description=f"Cluster of {len(cluster_channels)} channels focused on: {', '.join(keywords[:5])}"
            )
            
            niches.append((niche_info, cluster_channels))
        
        return niches
    
    def cluster_all_categories(
        self,
        progress_callback: Optional[ProgressCallback] = None
    ) -> Dict[str, List[NicheInfo]]:
        """
        Cluster all categories and save niches to database.
        
        Args:
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dict mapping category to list of NicheInfo
        """
        # Get all categories with channels
        categories = self.session.query(
            Channel.primary_category,
            func.count(Channel.id)
        ).filter(
            Channel.is_active == True
        ).group_by(
            Channel.primary_category
        ).all()
        
        # Filter valid categories
        valid_categories = [
            (cat, count) for cat, count in categories 
            if cat and count >= self.MIN_CHANNELS_PER_NICHE
        ]
        
        all_niches = {}
        total_niches = 0
        
        for idx, (category, count) in enumerate(valid_categories):
            if progress_callback:
                progress_callback(
                    "categories", 
                    idx, 
                    len(valid_categories), 
                    f"Clustering {category} ({count} channels)"
                )
            
            logger.info(f"Clustering category: {category}", channels=count)
            
            niches_with_channels = self.cluster_category(category, progress_callback=progress_callback)
            
            if niches_with_channels:
                # Save niches to database
                saved_niches = []
                
                for niche_info, channels in niches_with_channels:
                    # Create niche record
                    niche = Niche(
                        name=niche_info.name,
                        category=niche_info.category,
                        keywords=",".join(niche_info.keywords),
                        channel_count=niche_info.channel_count,
                        avg_subscribers=niche_info.avg_subscribers,
                        description=niche_info.description,
                    )
                    self.session.add(niche)
                    self.session.flush()  # Get the ID
                    
                    # Update channels with niche assignment
                    for channel in channels:
                        channel.niche_id = niche.id
                    
                    niche_info.niche_id = niche.id
                    saved_niches.append(niche_info)
                    total_niches += 1
                
                self.session.commit()
                all_niches[category] = saved_niches
                
                logger.info(f"Created {len(saved_niches)} niches for {category}")
        
        if progress_callback:
            progress_callback("categories", len(valid_categories), len(valid_categories), "Complete!")
        
        logger.info(f"Total niches created: {total_niches}")
        return all_niches
    
    def get_niche_summary(self) -> List[Dict]:
        """Get summary of all niches."""
        niches = self.session.query(Niche).order_by(
            Niche.category, Niche.channel_count.desc()
        ).all()
        
        return [
            {
                "id": n.id,
                "name": n.name,
                "category": n.category,
                "channels": n.channel_count,
                "avg_subs": n.avg_subscribers,
                "keywords": n.keywords.split(",")[:5] if n.keywords else [],
            }
            for n in niches
        ]

