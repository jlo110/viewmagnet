"""YouTube API client with quota management and rate limiting."""
import re
import time
from datetime import datetime
from typing import Any, Optional, List
from dataclasses import dataclass

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog

from src.youtube.quota import QuotaManager, QUOTA_COSTS

logger = structlog.get_logger()


def parse_duration(duration_str: str) -> int:
    """
    Parse ISO 8601 duration string to seconds.
    
    Examples:
        PT1H30M45S -> 5445
        PT10M -> 600
        PT30S -> 30
    """
    if not duration_str:
        return 0
    
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return 0
    
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    
    return hours * 3600 + minutes * 60 + seconds


@dataclass
class ChannelInfo:
    """Parsed channel information from YouTube API."""
    channel_id: str
    channel_name: str
    custom_url: Optional[str]
    description: Optional[str]
    subscriber_count: int
    total_views: int
    video_count: int
    country: Optional[str]
    created_at: Optional[datetime]
    thumbnail_url: Optional[str]
    uploads_playlist_id: Optional[str]
    default_language: Optional[str] = None


@dataclass
class VideoInfo:
    """Parsed video information from YouTube API."""
    video_id: str
    channel_id: str
    title: str
    description: Optional[str]
    thumbnail_url: Optional[str]
    tags: list[str]
    duration_seconds: int
    published_at: datetime
    youtube_category_id: Optional[str]
    view_count: int
    like_count: int
    comment_count: int
    # Phase 8.5 capture-now fields — present in the same `snippet` part we
    # already request, so they're free. Defaults keep older callers working.
    live_broadcast_content: Optional[str] = None  # "live" | "upcoming" | "none"
    default_audio_language: Optional[str] = None


class YouTubeClient:
    """
    YouTube API client with quota management and retry logic.
    
    Features:
    - Automatic API key rotation when quota exhausted
    - Exponential backoff on transient errors
    - Structured logging
    - Rate limiting to avoid hitting rate limits
    """
    
    # Minimum delay between API calls (seconds)
    MIN_REQUEST_DELAY = 0.1
    
    def __init__(self, quota_manager: Optional[QuotaManager] = None):
        """
        Initialize YouTube client.
        
        Args:
            quota_manager: QuotaManager instance. Creates new one if None.
        """
        self.quota_manager = quota_manager or QuotaManager()
        self._youtube = None
        self._last_request_time = 0.0
        self._build_client()
    
    def _build_client(self) -> None:
        """Build the YouTube API client with current key."""
        api_key = self.quota_manager.get_current_key()
        self._youtube = build("youtube", "v3", developerKey=api_key)
        logger.debug("youtube_client_built")
    
    def _ensure_rate_limit(self) -> None:
        """Ensure minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_DELAY:
            time.sleep(self.MIN_REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()
    
    def _rotate_key_if_needed(self, required_units: int) -> bool:
        """
        Check if we need to rotate API key.
        
        Returns:
            True if a key is available, False if all exhausted
        """
        key = self.quota_manager.get_key_with_quota(required_units)
        if key is None:
            return False
        
        if key != self.quota_manager.get_current_key():
            self._build_client()
        return True
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(HttpError),
    )
    def search_channels(
        self,
        query: str,
        max_results: int = 50,
        page_token: Optional[str] = None,
        region_code: str = "US",
        relevance_language: str = "en",
    ) -> dict[str, Any]:
        """
        Search for YouTube channels.
        
        Args:
            query: Search query string
            max_results: Maximum results per page (max 50)
            page_token: Token for pagination
            region_code: Region to search in
            relevance_language: Language preference
            
        Returns:
            API response with channel search results
        """
        operation = "search.list"
        cost = QUOTA_COSTS[operation]
        
        if not self._rotate_key_if_needed(cost):
            raise Exception("All API keys exhausted")
        
        self._ensure_rate_limit()
        
        try:
            request = self._youtube.search().list(
                q=query,
                type="channel",
                part="snippet",
                maxResults=min(max_results, 50),
                pageToken=page_token,
                regionCode=region_code,
                relevanceLanguage=relevance_language,
            )
            response = request.execute()
            
            self.quota_manager.record_usage(operation)
            
            logger.info(
                "channel_search_completed",
                query=query,
                results=len(response.get("items", [])),
                has_next_page=bool(response.get("nextPageToken"))
            )
            
            return response
            
        except HttpError as e:
            self._handle_http_error(e)
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(HttpError),
    )
    def get_channel_details(self, channel_ids: list[str]) -> list[ChannelInfo]:
        """
        Get detailed information for channels.
        
        Args:
            channel_ids: List of channel IDs (max 50)
            
        Returns:
            List of ChannelInfo objects
        """
        if not channel_ids:
            return []
        
        operation = "channels.list"
        cost = QUOTA_COSTS[operation]
        
        if not self._rotate_key_if_needed(cost):
            raise Exception("All API keys exhausted")
        
        self._ensure_rate_limit()
        
        # Batch into groups of 50
        channel_ids = channel_ids[:50]
        
        try:
            request = self._youtube.channels().list(
                id=",".join(channel_ids),
                part="snippet,statistics,contentDetails,brandingSettings",
            )
            response = request.execute()
            
            self.quota_manager.record_usage(operation)
            
            channels = []
            for item in response.get("items", []):
                channels.append(self._parse_channel(item))
            
            logger.info(
                "channel_details_fetched",
                requested=len(channel_ids),
                returned=len(channels)
            )
            
            return channels
            
        except HttpError as e:
            self._handle_http_error(e)
            raise
    
    def _parse_channel(self, item: dict) -> ChannelInfo:
        """Parse a channel item from the API response."""
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})
        
        # Parse creation date
        created_at = None
        if snippet.get("publishedAt"):
            try:
                created_at = datetime.fromisoformat(
                    snippet["publishedAt"].replace("Z", "+00:00")
                )
            except ValueError:
                pass
        
        # Handle hidden subscriber count
        subscriber_count = 0
        if not statistics.get("hiddenSubscriberCount", False):
            subscriber_count = int(statistics.get("subscriberCount", 0))
        
        # Get language - check multiple sources
        default_language = (
            snippet.get("defaultLanguage") or 
            item.get("brandingSettings", {}).get("channel", {}).get("defaultLanguage")
        )
        
        return ChannelInfo(
            channel_id=item["id"],
            channel_name=snippet.get("title", ""),
            custom_url=snippet.get("customUrl"),
            description=snippet.get("description"),
            subscriber_count=subscriber_count,
            total_views=int(statistics.get("viewCount", 0)),
            video_count=int(statistics.get("videoCount", 0)),
            country=snippet.get("country"),
            created_at=created_at,
            thumbnail_url=snippet.get("thumbnails", {}).get("high", {}).get("url"),
            uploads_playlist_id=content_details.get("relatedPlaylists", {}).get("uploads"),
            default_language=default_language,
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(HttpError),
    )
    def get_channel_videos(
        self,
        uploads_playlist_id: str,
        max_results: int = 30,
        page_token: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Get videos from a channel's uploads playlist.
        
        Args:
            uploads_playlist_id: The channel's uploads playlist ID
            max_results: Maximum videos to return
            page_token: Token for pagination
            
        Returns:
            API response with playlist items
        """
        operation = "playlistItems.list"
        cost = QUOTA_COSTS[operation]
        
        if not self._rotate_key_if_needed(cost):
            raise Exception("All API keys exhausted")
        
        self._ensure_rate_limit()
        
        try:
            request = self._youtube.playlistItems().list(
                playlistId=uploads_playlist_id,
                part="snippet,contentDetails",
                maxResults=min(max_results, 50),
                pageToken=page_token,
            )
            response = request.execute()
            
            self.quota_manager.record_usage(operation)
            
            return response
            
        except HttpError as e:
            self._handle_http_error(e)
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(HttpError),
    )
    def get_most_popular(
        self,
        region_code: str = "US",
        video_category_id: Optional[str] = None,
        max_results: int = 50,
    ) -> List[VideoInfo]:
        """Fetch the mostPopular chart for a region (optionally per category).

        1 quota unit — the cheapest niche-stratified discovery source on the
        API (plan 8.11 tracked-set expansion). Some region×category combos
        return 404; callers should treat per-combo failures as skippable.
        """
        operation = "videos.list"
        cost = QUOTA_COSTS[operation]
        if not self._rotate_key_if_needed(cost):
            raise Exception("All API keys exhausted")
        self._ensure_rate_limit()

        params = {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": region_code,
            "maxResults": min(max_results, 50),
        }
        if video_category_id:
            params["videoCategoryId"] = video_category_id
        try:
            response = self._youtube.videos().list(**params).execute()
            self.quota_manager.record_usage(operation)
            return [self._parse_video(item) for item in response.get("items", [])]
        except HttpError as e:
            self._handle_http_error(e)
            raise

    def get_video_details(self, video_ids: List[str]) -> List[VideoInfo]:
        """
        Get detailed information for videos.
        
        Args:
            video_ids: List of video IDs (max 50)
            
        Returns:
            List of VideoInfo objects
        """
        if not video_ids:
            return []
        
        operation = "videos.list"
        cost = QUOTA_COSTS[operation]
        
        if not self._rotate_key_if_needed(cost):
            raise Exception("All API keys exhausted")
        
        self._ensure_rate_limit()
        
        # Batch into groups of 50
        video_ids = video_ids[:50]
        
        try:
            request = self._youtube.videos().list(
                id=",".join(video_ids),
                part="snippet,statistics,contentDetails",
            )
            response = request.execute()
            
            self.quota_manager.record_usage(operation)
            
            videos = []
            for item in response.get("items", []):
                videos.append(self._parse_video(item))
            
            logger.debug(
                "video_details_fetched",
                requested=len(video_ids),
                returned=len(videos)
            )
            
            return videos
            
        except HttpError as e:
            self._handle_http_error(e)
            raise
    
    def _parse_video(self, item: dict) -> VideoInfo:
        """Parse a video item from the API response."""
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})
        
        # Parse publish date
        published_at = datetime.utcnow()
        if snippet.get("publishedAt"):
            try:
                published_at = datetime.fromisoformat(
                    snippet["publishedAt"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except ValueError:
                pass
        
        # Parse duration
        duration = parse_duration(content_details.get("duration", ""))
        
        # Get thumbnail (prefer maxres, fall back to high, then default)
        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = (
            thumbnails.get("maxres", {}).get("url") or
            thumbnails.get("high", {}).get("url") or
            thumbnails.get("default", {}).get("url")
        )
        
        return VideoInfo(
            video_id=item["id"],
            channel_id=snippet.get("channelId", ""),
            title=snippet.get("title", ""),
            description=(snippet.get("description") or "")[:1000],  # First 1000 chars
            thumbnail_url=thumbnail_url,
            tags=snippet.get("tags", []),
            duration_seconds=duration,
            published_at=published_at,
            youtube_category_id=snippet.get("categoryId"),
            view_count=int(statistics.get("viewCount", 0)),
            like_count=int(statistics.get("likeCount", 0)),
            comment_count=int(statistics.get("commentCount", 0)),
            live_broadcast_content=snippet.get("liveBroadcastContent"),
            default_audio_language=snippet.get("defaultAudioLanguage"),
        )
    
    def _handle_http_error(self, e: HttpError) -> None:
        """Handle HTTP errors from YouTube API."""
        if e.resp.status == 403 and "quotaExceeded" in str(e):
            logger.warning("quota_exceeded_marking_dead")
            self.quota_manager.mark_key_dead(reason="quota_exceeded")
            self._build_client()  # Rebuild with new key
        elif e.resp.status == 401:
            logger.warning("auth_error_marking_dead", status=401)
            self.quota_manager.mark_key_dead(reason="unauthorized_401")
            self._build_client()
        elif e.resp.status == 403:
            logger.warning("forbidden_error_marking_dead", status=403)
            self.quota_manager.mark_key_dead(reason="forbidden_403")
            self._build_client()
    
    def get_quota_status(self) -> dict:
        """Get current quota status."""
        return self.quota_manager.get_status()

