"""Channel collector - main discovery logic."""
import random
from typing import List, Optional, Set, TYPE_CHECKING
from dataclasses import dataclass
import structlog

from src.config import DISCOVERY_QUERIES, CATEGORY_DISTRIBUTION, SIZE_DISTRIBUTION
from src.youtube.client import YouTubeClient, ChannelInfo
from src.discovery.tracker import DistributionTracker

if TYPE_CHECKING:
    from src.discovery.storage import ChannelStorage

logger = structlog.get_logger()


@dataclass
class CollectionResult:
    """Result of a collection run."""
    channels_found: int
    channels_added: int
    channels_skipped: int
    errors: int


class ChannelCollector:
    """
    Collects YouTube channels according to target distribution.
    
    Discovery strategies:
    1. Search-based: Use category-specific search queries
    2. Related channels: Get channels related to already-collected channels
    3. Trending: Find channels from trending videos in each category
    
    The collector prioritizes filling gaps in the distribution.
    """
    
    def __init__(
        self,
        youtube_client: Optional[YouTubeClient] = None,
        tracker: Optional[DistributionTracker] = None,
        storage: Optional["ChannelStorage"] = None,
    ):
        """
        Initialize the collector.
        
        Args:
            youtube_client: YouTube API client
            tracker: Distribution tracker
            storage: Storage layer for saving channels
        """
        self.client = youtube_client or YouTubeClient()
        self.tracker = tracker or DistributionTracker()
        self.storage = storage
        
        # Track channels we've already seen to avoid duplicates
        self._seen_channel_ids: Set[str] = set()
    
    def collect_by_search(
        self,
        category: str,
        max_channels: int = 100,
        queries: Optional[List[str]] = None,
    ) -> CollectionResult:
        """
        Collect channels for a category using search queries.
        
        Args:
            category: Category to collect for
            max_channels: Maximum channels to collect
            queries: Custom queries (uses defaults if None)
            
        Returns:
            CollectionResult with statistics
        """
        if queries is None:
            queries = DISCOVERY_QUERIES.get(category, [category])
        
        result = CollectionResult(
            channels_found=0,
            channels_added=0,
            channels_skipped=0,
            errors=0
        )
        
        # Shuffle queries to vary collection
        queries = list(queries)
        random.shuffle(queries)
        
        channels_to_add = []
        
        for query in queries:
            if result.channels_added >= max_channels:
                break
            
            try:
                # Search for channels
                search_results = self.client.search_channels(query)
                
                # Extract channel IDs from search
                channel_ids = []
                for item in search_results.get("items", []):
                    channel_id = item.get("snippet", {}).get("channelId")
                    if channel_id and channel_id not in self._seen_channel_ids:
                        channel_ids.append(channel_id)
                        self._seen_channel_ids.add(channel_id)
                
                if not channel_ids:
                    continue
                
                # Get full channel details
                channels = self.client.get_channel_details(channel_ids)
                result.channels_found += len(channels)
                
                for channel in channels:
                    # Check if channel meets minimum requirements
                    if not self._is_valid_channel(channel):
                        result.channels_skipped += 1
                        continue
                    
                    # Check if we need this channel for our distribution
                    if self.tracker.should_collect(category, channel.subscriber_count):
                        # Save to database if storage is configured
                        if self.storage:
                            try:
                                self.storage.save_channel(
                                    channel, 
                                    category,
                                    discovery_source="search",
                                    discovery_query=query
                                )
                            except Exception as e:
                                logger.error("save_channel_error", channel=channel.channel_name, error=str(e))
                                result.errors += 1
                                continue
                        
                        result.channels_added += 1
                        self.tracker.record_channel(category, channel.subscriber_count)
                        
                        if result.channels_added >= max_channels:
                            break
                    else:
                        result.channels_skipped += 1
                        
            except Exception as e:
                logger.error("search_error", query=query, error=str(e))
                result.errors += 1
        
        # Commit any pending saves
        if self.storage:
            try:
                self.storage.commit()
            except Exception as e:
                logger.error("commit_error", error=str(e))
        
        logger.info(
            "search_collection_complete",
            category=category,
            found=result.channels_found,
            added=result.channels_added,
            skipped=result.channels_skipped,
        )
        
        return result
    
    def collect_all_categories(
        self,
        channels_per_category: Optional[int] = None,
        prioritize_gaps: bool = True,
    ) -> dict[str, CollectionResult]:
        """
        Collect channels for all categories.
        
        Args:
            channels_per_category: Max channels per category per run
            prioritize_gaps: If True, focus on categories with biggest gaps
            
        Returns:
            Dict mapping category to CollectionResult
        """
        results = {}
        
        if prioritize_gaps:
            # Order categories by how many channels they still need
            categories = self.tracker.get_priority_categories(top_n=len(CATEGORY_DISTRIBUTION))
        else:
            categories = list(CATEGORY_DISTRIBUTION.keys())
        
        for category in categories:
            progress = self.tracker.get_category_progress(category)
            
            if progress.is_complete:
                logger.info("category_complete", category=category)
                continue
            
            # Calculate how many to collect
            if channels_per_category:
                max_to_collect = min(channels_per_category, progress.remaining)
            else:
                # Proportional to remaining need
                max_to_collect = min(100, progress.remaining)
            
            logger.info(
                "collecting_category",
                category=category,
                current=progress.current,
                target=progress.target,
                collecting=max_to_collect
            )
            
            result = self.collect_by_search(category, max_channels=max_to_collect)
            results[category] = result
            
            # Check quota status
            quota = self.client.get_quota_status()
            if quota["total_remaining"] < 200:
                logger.warning("low_quota_stopping", remaining=quota["total_remaining"])
                break
        
        return results
    
    def collect_targeted(
        self,
        category: str,
        size_tier: str,
        max_channels: int = 50,
    ) -> CollectionResult:
        """
        Collect channels for a specific category and size tier.
        
        Useful for filling specific gaps in the distribution.
        
        Args:
            category: Target category
            size_tier: Target size tier (micro, small, medium, large, top)
            max_channels: Maximum channels to collect
            
        Returns:
            CollectionResult with statistics
        """
        size_range = SIZE_DISTRIBUTION.get(size_tier, {}).get("range", (0, float("inf")))
        min_subs, max_subs = size_range
        
        queries = DISCOVERY_QUERIES.get(category, [category])
        
        result = CollectionResult(
            channels_found=0,
            channels_added=0,
            channels_skipped=0,
            errors=0
        )
        
        # Add size-related terms to queries
        size_hints = {
            "micro": ["small youtuber", "underrated", "hidden gem", "new channel 2024", "first video", "100 subscribers", "starting out"],
            "small": ["growing channel", "upcoming creator", "underrated channel", "50k subscribers", "100k subscribers", "rising creator", "new youtuber 2024"],
            "medium": ["popular", "trending", "blowing up", "500k subscribers"],
            "large": ["top", "best", "famous", "million subscribers"],
            "top": ["biggest", "most popular", "viral", "10 million"],
        }
        
        enhanced_queries = []
        for query in queries:
            enhanced_queries.append(query)
            for hint in size_hints.get(size_tier, []):
                enhanced_queries.append(f"{query} {hint}")
        
        random.shuffle(enhanced_queries)
        
        for query in enhanced_queries:
            if result.channels_added >= max_channels:
                break
            
            try:
                search_results = self.client.search_channels(query)
                
                channel_ids = []
                for item in search_results.get("items", []):
                    channel_id = item.get("snippet", {}).get("channelId")
                    if channel_id and channel_id not in self._seen_channel_ids:
                        channel_ids.append(channel_id)
                        self._seen_channel_ids.add(channel_id)
                
                if not channel_ids:
                    continue
                
                channels = self.client.get_channel_details(channel_ids)
                result.channels_found += len(channels)
                
                for channel in channels:
                    if not self._is_valid_channel(channel):
                        result.channels_skipped += 1
                        continue
                    
                    # Save ALL valid channels (don't waste them!)
                    # Check if we need this channel for ANY slot in this category
                    if self.tracker.should_collect(category, channel.subscriber_count):
                        # Save to database if storage is configured
                        if self.storage:
                            try:
                                self.storage.save_channel(
                                    channel,
                                    category,
                                    discovery_source="targeted_search",
                                    discovery_query=query
                                )
                            except Exception as e:
                                logger.error("save_channel_error", channel=channel.channel_name, error=str(e))
                                result.errors += 1
                                continue
                        
                        self.tracker.record_channel(category, channel.subscriber_count)
                        result.channels_added += 1
                        
                        # Only stop if we've filled the TARGET tier we were looking for
                        actual_tier = self.tracker.get_size_tier(channel.subscriber_count)
                        if actual_tier == size_tier and result.channels_added >= max_channels:
                            break
                    else:
                        result.channels_skipped += 1
                        
            except Exception as e:
                logger.error("targeted_search_error", query=query, error=str(e))
                result.errors += 1
        
        # Commit any pending saves
        if self.storage:
            try:
                self.storage.commit()
            except Exception as e:
                logger.error("commit_error", error=str(e))
        
        return result
    
    def fill_gaps(self, max_total: int = 500) -> dict[str, CollectionResult]:
        """
        Focus collection on the biggest gaps in the distribution.
        
        Args:
            max_total: Maximum total channels to collect
            
        Returns:
            Dict mapping "category/size" to CollectionResult
        """
        gaps = self.tracker.get_gaps()
        results = {}
        total_added = 0
        
        for category, size_tier, needed in gaps:
            if total_added >= max_total:
                break
            
            to_collect = min(needed, max_total - total_added, 50)
            
            logger.info(
                "filling_gap",
                category=category,
                size_tier=size_tier,
                needed=needed,
                collecting=to_collect
            )
            
            result = self.collect_targeted(category, size_tier, max_channels=to_collect)
            results[f"{category}/{size_tier}"] = result
            total_added += result.channels_added
            
            # Check quota
            quota = self.client.get_quota_status()
            if quota["total_remaining"] < 200:
                logger.warning("low_quota_stopping")
                break
        
        return results
    
    
    def _is_valid_channel(self, channel: ChannelInfo) -> bool:
        """
        Check if a channel meets minimum requirements.
        
        Requirements:
        - At least 10K subscribers (minimum for micro tier)
        - At least 10 videos
        - Not a hidden subscriber count
        - English language channel
        """
        if channel.subscriber_count < 10_000:
            return False
        
        if channel.video_count < 10:
            return False
        
        # Subscriber count of 0 usually means hidden
        if channel.subscriber_count == 0:
            return False
        
        # Filter for English channels
        if not self._is_english_channel(channel):
            logger.debug(
                "skipping_non_english",
                channel=channel.channel_name,
                language=channel.default_language,
                country=channel.country
            )
            return False
        
        return True
    
    def _is_english_channel(self, channel: ChannelInfo) -> bool:
        """
        Determine if a channel is likely English-language.
        
        Only reject channels that EXPLICITLY set a non-English language.
        Channels without language data are accepted.
        
        Args:
            channel: Channel info
            
        Returns:
            True if not explicitly non-English
        """
        # Only reject if explicitly set to non-English
        if channel.default_language:
            lang = channel.default_language.lower()
            # Accept English variants: en, en-US, en-GB, etc.
            if lang.startswith("en"):
                return True
            # Reject explicitly non-English languages
            logger.debug(
                "rejecting_explicit_non_english",
                channel=channel.channel_name,
                language=channel.default_language
            )
            return False
        
        # No explicit language set - accept the channel
        # (YouTube search with relevanceLanguage=en biases toward English anyway)
        return True
    
    
    def load_seen_channels(self, session) -> None:
        """
        Load already-collected channel IDs to avoid duplicates.
        
        Args:
            session: SQLAlchemy session
        """
        from src.database.models import Channel
        
        channel_ids = session.query(Channel.channel_id).all()
        self._seen_channel_ids = {cid[0] for cid in channel_ids}
        
        logger.info("loaded_seen_channels", count=len(self._seen_channel_ids))

