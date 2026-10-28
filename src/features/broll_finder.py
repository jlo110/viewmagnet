"""
B-Roll Finder for ViewMagnet.

Finds relevant stock footage from Pexels and Pixabay based on script content.
"""
import os
import re
import httpx
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from urllib.parse import urlencode

import structlog

logger = structlog.get_logger()


@dataclass
class StockClip:
    """Represents a stock media item (video, image, or animated GIF).

    The shape stays uniform across media types so the frontend can render
    every result with the same card and the same "add to timeline" flow.
    For images, ``duration`` is 0 (the renderer treats them as a 4s still);
    for GIFs, ``download_url`` is always an MP4 URL (Tenor / Giphy both
    expose one) so the timeline never has to deal with .gif natively.
    """
    id: str
    source: str  # "pexels" or "pixabay" or "tenor" or "giphy"
    title: str
    description: str
    duration: int  # seconds; 0 for static images
    width: int
    height: int
    preview_url: str
    download_url: str
    thumbnail_url: str
    user: str
    user_url: str
    tags: List[str] = field(default_factory=list)
    quality: str = "hd"  # sd, hd, 4k
    # ``video`` (mp4), ``image`` (jpg/png), or ``gif`` (mp4 of a gif loop).
    media_type: str = "video"


@dataclass
class BRollSuggestion:
    """A B-roll suggestion for a script section."""
    section_name: str
    section_text: str
    keywords: List[str]
    clips: List[StockClip]
    timestamp: Optional[str] = None


class PexelsClient:
    """Client for Pexels API."""
    
    BASE_URL = "https://api.pexels.com"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("PEXELS_API_KEY")
        if not self.api_key:
            logger.warning("Pexels API key not configured")
        
        self.client = httpx.Client(
            base_url=self.BASE_URL,
            headers={"Authorization": self.api_key or ""},
            timeout=30.0,
        )
    
    def search_videos(
        self,
        query: str,
        per_page: int = 10,
        page: int = 1,
        orientation: Optional[str] = None,  # landscape, portrait, square
        size: Optional[str] = None,  # large, medium, small
    ) -> List[StockClip]:
        """
        Search for videos on Pexels.
        
        Args:
            query: Search query.
            per_page: Results per page (max 80).
            page: Page number.
            orientation: Video orientation filter.
            size: Video size filter.
        
        Returns:
            List of StockClip objects.
        """
        if not self.api_key:
            return []
        
        params = {
            "query": query,
            "per_page": min(per_page, 80),
            "page": page,
        }
        if orientation:
            params["orientation"] = orientation
        if size:
            params["size"] = size
        
        try:
            response = self.client.get(f"/videos/search?{urlencode(params)}")
            response.raise_for_status()
            data = response.json()
            
            clips = []
            for video in data.get("videos", []):
                # Get the best quality file
                video_files = video.get("video_files", [])
                best_file = self._get_best_quality(video_files)
                
                if not best_file:
                    continue
                
                clips.append(StockClip(
                    id=str(video["id"]),
                    source="pexels",
                    title=video.get("url", "").split("/")[-1].replace("-", " ").title(),
                    description="",
                    duration=video.get("duration", 0),
                    width=best_file.get("width", 0),
                    height=best_file.get("height", 0),
                    preview_url=video.get("video_pictures", [{}])[0].get("picture", ""),
                    download_url=best_file.get("link", ""),
                    thumbnail_url=video.get("image", ""),
                    user=video.get("user", {}).get("name", "Unknown"),
                    user_url=video.get("user", {}).get("url", ""),
                    quality=best_file.get("quality", "hd"),
                ))
            
            return clips
        except Exception as e:
            logger.error(f"Pexels search failed: {e}")
            return []
    
    def _get_best_quality(self, video_files: List[Dict]) -> Optional[Dict]:
        """Get the best quality video file that's reasonable for B-roll."""
        # Prefer HD quality, avoid 4K for file size
        quality_order = ["hd", "sd", "uhd"]
        
        sorted_files = sorted(
            video_files,
            key=lambda f: (
                quality_order.index(f.get("quality", "sd")) if f.get("quality") in quality_order else 99,
                -f.get("width", 0),
            )
        )
        
        return sorted_files[0] if sorted_files else None
    
    def search_images(
        self,
        query: str,
        per_page: int = 12,
        page: int = 1,
        orientation: Optional[str] = None,
    ) -> List[StockClip]:
        """Search Pexels' photo library and return ``StockClip``s with
        ``media_type='image'``.

        Pexels' image endpoint is ``/v1/search`` (vs ``/videos/search`` for
        clips). The ``src`` block has multiple sizes — we pick ``large``
        for the timeline render and ``small`` for the panel thumbnail."""
        if not self.api_key:
            return []

        params: Dict[str, Any] = {
            "query": query,
            "per_page": min(per_page, 80),
            "page": page,
        }
        if orientation:
            params["orientation"] = orientation
        try:
            response = self.client.get(f"/v1/search?{urlencode(params)}")
            response.raise_for_status()
            data = response.json()

            clips: List[StockClip] = []
            for photo in data.get("photos", []):
                src = photo.get("src", {}) or {}
                full = src.get("large") or src.get("original") or src.get("medium")
                thumb = src.get("small") or src.get("tiny") or full
                if not full:
                    continue
                clips.append(StockClip(
                    id=str(photo.get("id")),
                    source="pexels",
                    title=(photo.get("alt") or "Pexels photo").strip()[:80],
                    description=photo.get("alt", ""),
                    duration=0,
                    width=photo.get("width", 0),
                    height=photo.get("height", 0),
                    preview_url=thumb or "",
                    download_url=full,
                    thumbnail_url=thumb or "",
                    user=(photo.get("photographer") or "Unknown"),
                    user_url=photo.get("photographer_url", ""),
                    quality="hd",
                    media_type="image",
                ))
            return clips
        except Exception as e:
            logger.error(f"Pexels image search failed: {e}")
            return []

    def get_popular_videos(self, per_page: int = 10) -> List[StockClip]:
        """Get popular/curated videos."""
        if not self.api_key:
            return []
        
        try:
            response = self.client.get(f"/videos/popular?per_page={per_page}")
            response.raise_for_status()
            data = response.json()
            
            clips = []
            for video in data.get("videos", []):
                video_files = video.get("video_files", [])
                best_file = self._get_best_quality(video_files)
                
                if not best_file:
                    continue
                
                clips.append(StockClip(
                    id=str(video["id"]),
                    source="pexels",
                    title=video.get("url", "").split("/")[-1].replace("-", " ").title(),
                    description="",
                    duration=video.get("duration", 0),
                    width=best_file.get("width", 0),
                    height=best_file.get("height", 0),
                    preview_url=video.get("video_pictures", [{}])[0].get("picture", ""),
                    download_url=best_file.get("link", ""),
                    thumbnail_url=video.get("image", ""),
                    user=video.get("user", {}).get("name", "Unknown"),
                    user_url=video.get("user", {}).get("url", ""),
                    quality=best_file.get("quality", "hd"),
                ))
            
            return clips
        except Exception as e:
            logger.error(f"Failed to get popular videos: {e}")
            return []


class PixabayClient:
    """Client for Pixabay API."""
    
    BASE_URL = "https://pixabay.com/api"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("PIXABAY_API_KEY")
        if not self.api_key:
            logger.warning("Pixabay API key not configured")
        
        self.client = httpx.Client(timeout=30.0)
    
    def search_videos(
        self,
        query: str,
        per_page: int = 10,
        page: int = 1,
        video_type: str = "all",  # all, film, animation
        category: Optional[str] = None,
    ) -> List[StockClip]:
        """
        Search for videos on Pixabay.
        
        Args:
            query: Search query.
            per_page: Results per page (max 200).
            page: Page number.
            video_type: Type of video.
            category: Category filter.
        
        Returns:
            List of StockClip objects.
        """
        if not self.api_key:
            return []
        
        params = {
            "key": self.api_key,
            "q": query,
            "per_page": min(per_page, 200),
            "page": page,
            "video_type": video_type,
        }
        if category:
            params["category"] = category
        
        try:
            response = self.client.get(f"{self.BASE_URL}/videos/?{urlencode(params)}")
            response.raise_for_status()
            data = response.json()
            
            clips = []
            for hit in data.get("hits", []):
                videos = hit.get("videos", {})
                # Prefer medium quality
                video_data = videos.get("medium", videos.get("small", videos.get("large", {})))
                
                if not video_data:
                    continue
                
                clips.append(StockClip(
                    id=str(hit["id"]),
                    source="pixabay",
                    title=hit.get("tags", "").split(",")[0].strip().title(),
                    description=hit.get("tags", ""),
                    duration=hit.get("duration", 0),
                    width=video_data.get("width", 0),
                    height=video_data.get("height", 0),
                    preview_url=videos.get("tiny", {}).get("url", ""),
                    download_url=video_data.get("url", ""),
                    thumbnail_url=hit.get("picture_id", ""),
                    user=hit.get("user", "Unknown"),
                    user_url=f"https://pixabay.com/users/{hit.get('user', '')}/",
                    tags=hit.get("tags", "").split(", "),
                    quality="hd" if video_data.get("height", 0) >= 720 else "sd",
                ))
            
            return clips
        except Exception as e:
            logger.error(f"Pixabay search failed: {e}")
            return []


class GiphyClient:
    """Client for the Giphy GIF search API.

    Free developer tier: 100 RPH, ~100k RPM. Required env: ``GIPHY_API_KEY``.
    Optional: ``GIPHY_ENDPOINT`` (defaults to the public ``api.giphy.com``).

    Why this matters for B-roll: each search result exposes an MP4 URL
    under ``images.original.mp4`` so we can drop a Giphy GIF onto the
    timeline as a normal video clip — no .gif decoder, no ffmpeg
    image-to-video promote step. (Giphy stores every public GIF as both
    a .gif and a transparent .mp4; we always grab the MP4.)

    Lives alongside ``TenorClient`` — ``BRollFinder`` picks whichever
    provider has a configured API key, preferring Giphy when both are
    set because the user already had a Giphy key in their .env.
    """

    DEFAULT_ENDPOINT = "https://api.giphy.com"

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("GIPHY_API_KEY")
        self.endpoint = (
            endpoint
            or os.getenv("GIPHY_ENDPOINT")
            or self.DEFAULT_ENDPOINT
        ).rstrip("/")
        if not self.api_key:
            logger.warning("Giphy API key not configured")
        self.client = httpx.Client(timeout=15.0)

    @staticmethod
    def _pick_mp4(images: Dict[str, Any]) -> tuple[str, int, int, float]:
        """Choose the best MP4 variant from a Giphy ``images`` block.

        Order of preference:
          1. ``original.mp4`` — full quality, native dimensions.
          2. ``looping.mp4`` — same loop but optimized for autoplay.
          3. ``downsized_medium.mp4`` — fallback when ``original`` is huge.
          4. ``preview.mp4`` — tiny, very last resort.

        Returns ``(url, width, height, duration_seconds)``. Dimensions
        come back as strings from Giphy ("480") so we coerce to int.
        Duration is the GIF playback length; Giphy doesn't always set
        ``mp4_size`` reliably, so we estimate from ``frames * 0.04``
        (25fps) when available, else 0 (renderer treats 0 as "play
        full length", which is fine).
        """
        candidates = (
            "original",
            "looping",
            "downsized_medium",
            "downsized",
            "preview",
        )
        for key in candidates:
            block = images.get(key) or {}
            url = block.get("mp4") or ""
            if url:
                width = int(block.get("width") or 0) if str(block.get("width") or "").isdigit() else 0
                height = int(block.get("height") or 0) if str(block.get("height") or "").isdigit() else 0
                # Estimate duration from frame count when present;
                # otherwise leave as 0 and let the timeline default to
                # the 4s B-roll standard.
                frames = images.get("original", {}).get("frames")
                duration = 0.0
                if frames and str(frames).isdigit():
                    duration = round(int(frames) * 0.04, 2)
                return url, width, height, duration
        return "", 0, 0, 0.0

    def search_gifs(self, query: str, limit: int = 12) -> List[StockClip]:
        """Search Giphy and return GIFs as ``StockClip``s with the MP4
        loop URL as ``download_url``.

        Endpoint: ``GET /v1/gifs/search?api_key=...&q=...&limit=...``
        Per Giphy docs the ``rating`` param defaults to ``g`` if omitted,
        but we set it explicitly to ``pg-13`` so creators can still grab
        reaction clips while we keep the bar reasonable for a creator
        tool aimed at YouTube.
        """
        if not self.api_key:
            return []
        params = {
            "api_key": self.api_key,
            "q": query,
            "limit": min(limit, 50),
            "rating": "pg-13",
            # ``bundle=messaging_non_clips`` trims the response by ~40%
            # by dropping sticker/clip variants we don't render.
            "bundle": "messaging_non_clips",
        }
        try:
            r = self.client.get(
                f"{self.endpoint}/v1/gifs/search?{urlencode(params)}"
            )
            r.raise_for_status()
            data = r.json()
            clips: List[StockClip] = []
            for item in data.get("data", []) or []:
                images = item.get("images", {}) or {}
                mp4_url, width, height, duration = self._pick_mp4(images)
                if not mp4_url:
                    continue
                # Thumbnail: prefer the small still preview so the panel
                # grid renders fast; fall back to the original GIF.
                preview_gif = (images.get("preview_gif") or {}).get("url", "")
                fixed_gif = (images.get("fixed_height_small") or {}).get("url", "")
                still = (images.get("original_still") or {}).get("url", "")
                thumb = still or preview_gif or fixed_gif
                clips.append(StockClip(
                    id=str(item.get("id")),
                    source="giphy",
                    title=(item.get("title") or query)[:80].strip(),
                    description=item.get("title", ""),
                    duration=int(duration),
                    width=width,
                    height=height,
                    preview_url=thumb,
                    download_url=mp4_url,
                    thumbnail_url=thumb,
                    user=(item.get("user") or {}).get("display_name") or item.get("username", "") or "Giphy",
                    user_url=(item.get("user") or {}).get("profile_url") or item.get("url", ""),
                    quality="hd" if width >= 480 else "sd",
                    media_type="gif",
                ))
            return clips
        except Exception as e:
            logger.error(f"Giphy search failed: {e}")
            return []


class TenorClient:
    """Client for Tenor (Google) GIF search.

    Free tier: 10 RPS, no monthly cap. Required env: ``TENOR_API_KEY``.
    Optional: ``TENOR_CLIENT_KEY`` (any short string identifying the app —
    Google recommends it for analytics but doesn't enforce uniqueness).

    Why Tenor over Giphy: every Tenor search result exposes an MP4 URL
    under ``media_formats.mp4.url`` so we can drop the result straight
    onto the B-roll timeline as a normal video clip — no .gif decoder
    pipeline needed. Giphy has the same field but their search corpus
    skews more meme-and-reaction; Tenor covers gameplay/satisfying loops
    better, which is what the user is after.
    """

    BASE_URL = "https://tenor.googleapis.com/v2"

    def __init__(self, api_key: Optional[str] = None, client_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("TENOR_API_KEY")
        self.client_key = client_key or os.getenv("TENOR_CLIENT_KEY", "viewmagnet")
        if not self.api_key:
            logger.warning("Tenor API key not configured")
        self.client = httpx.Client(timeout=15.0)

    def search_gifs(self, query: str, limit: int = 12) -> List[StockClip]:
        """Search Tenor and return GIFs as ``StockClip``s with the MP4
        loop URL as ``download_url``.

        Tenor's search endpoint: ``/v2/search?q=...&key=...&client_key=...``
        Returns ``results[]`` with ``media_formats`` per item:
          - ``mp4`` (high-quality looping MP4 — perfect for B-roll)
          - ``tinymp4`` (smaller MP4 for previews)
          - ``gif`` / ``tinygif`` (fallback)
        """
        if not self.api_key:
            return []
        params = {
            "q": query,
            "key": self.api_key,
            "client_key": self.client_key,
            "limit": min(limit, 50),
            # ``contentfilter=medium`` keeps the safe-for-work bar reasonable
            # while still surfacing gameplay / cartoon clips.
            "contentfilter": "medium",
            # ``media_filter`` trims response size by 60%+ — request only
            # the formats we actually consume.
            "media_filter": "mp4,tinymp4,gif,tinygif",
        }
        try:
            r = self.client.get(f"{self.BASE_URL}/search?{urlencode(params)}")
            r.raise_for_status()
            data = r.json()
            clips: List[StockClip] = []
            for item in data.get("results", []) or []:
                fmts = item.get("media_formats", {}) or {}
                mp4 = fmts.get("mp4") or {}
                tinymp4 = fmts.get("tinymp4") or {}
                tinygif = fmts.get("tinygif") or fmts.get("gif") or {}
                mp4_url = mp4.get("url") or tinymp4.get("url")
                if not mp4_url:
                    continue
                # Tenor reports duration in fractional seconds in
                # ``mp4.duration`` (or 0 if not provided). Floor to int
                # for the dataclass; the renderer treats 0 as "play full
                # length" so it's safe.
                duration = int(float(mp4.get("duration") or tinymp4.get("duration") or 0))
                width, height = (mp4.get("dims") or [0, 0])[:2] or [0, 0]
                clips.append(StockClip(
                    id=str(item.get("id")),
                    source="tenor",
                    title=(item.get("title") or item.get("content_description") or query)[:80],
                    description=item.get("content_description", ""),
                    duration=duration,
                    width=width,
                    height=height,
                    preview_url=tinygif.get("url", "") or tinymp4.get("url", ""),
                    download_url=mp4_url,
                    thumbnail_url=tinygif.get("url", "") or tinymp4.get("url", ""),
                    user="Tenor",
                    user_url=item.get("itemurl", ""),
                    quality="hd",
                    media_type="gif",
                ))
            return clips
        except Exception as e:
            logger.error(f"Tenor search failed: {e}")
            return []


class BRollFinder:
    """
    Service to find B-roll footage for video scripts.
    
    Analyzes script content to extract keywords and finds relevant
    stock footage from multiple sources.
    """
    
    def __init__(self):
        self.pexels = PexelsClient()
        self.pixabay = PixabayClient()
        self.giphy = GiphyClient()
        self.tenor = TenorClient()
    
    def extract_keywords(self, text: str) -> List[str]:
        """
        Extract relevant keywords from text for B-roll search.
        
        Args:
            text: Script section text.
        
        Returns:
            List of keywords for searching.
        """
        # Common words to ignore
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
            "be", "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "must", "shall", "can", "need", "dare", "ought",
            "used", "this", "that", "these", "those", "i", "you", "he", "she", "it",
            "we", "they", "what", "which", "who", "whom", "when", "where", "why", "how",
            "all", "each", "every", "both", "few", "more", "most", "other", "some",
            "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too",
            "very", "just", "also", "now", "here", "there", "then", "once", "always",
            "never", "often", "still", "already", "ever", "about", "after", "before",
            "above", "below", "between", "into", "through", "during", "again", "further",
            "your", "our", "their", "my", "his", "her", "its", "let", "me", "us",
            "them", "him", "yourself", "ourselves", "themselves", "going", "get", "got",
            "really", "actually", "basically", "literally", "totally", "absolutely",
            "want", "like", "know", "think", "make", "see", "look", "take", "come",
            "say", "said", "tell", "ask", "use", "find", "give", "first", "new", "way",
        }
        
        # Extract words
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        
        # Filter and deduplicate
        keywords = []
        seen = set()
        for word in words:
            if word not in stop_words and word not in seen:
                seen.add(word)
                keywords.append(word)
        
        return keywords[:10]  # Return top 10 keywords
    
    def extract_visual_cues(self, text: str) -> List[str]:
        """
        Extract visual cues that suggest specific B-roll types.
        
        Args:
            text: Script text.
        
        Returns:
            List of visual cue keywords.
        """
        visual_patterns = {
            r'\b(computer|laptop|coding|programming|developer)\b': "coding computer",
            r'\b(meeting|conference|team|collaboration)\b': "business meeting",
            r'\b(office|workplace|desk)\b': "modern office",
            r'\b(nature|outdoor|outside|landscape)\b': "nature landscape",
            r'\b(city|urban|downtown|skyline)\b': "city skyline",
            r'\b(technology|tech|digital|innovation)\b': "technology innovation",
            r'\b(success|achievement|celebration|win)\b': "success celebration",
            r'\b(money|finance|investment|stock)\b': "finance money",
            r'\b(health|fitness|exercise|workout)\b': "fitness exercise",
            r'\b(food|cooking|kitchen|restaurant)\b': "cooking food",
            r'\b(travel|vacation|journey|adventure)\b': "travel adventure",
            r'\b(education|learning|study|school)\b': "education learning",
            r'\b(communication|social|network|connect)\b': "social connection",
            r'\b(growth|progress|improve|develop)\b': "growth progress",
            r'\b(time|clock|schedule|deadline)\b': "time management",
            r'\b(creative|art|design|imagination)\b': "creative design",
            r'\b(data|analytics|chart|graph)\b': "data analytics",
            r'\b(startup|entrepreneur|business)\b': "startup business",
            r'\b(customer|client|service|support)\b': "customer service",
            r'\b(stress|anxiety|overwhelm|pressure)\b': "stress relief",
        }
        
        cues = []
        text_lower = text.lower()
        
        for pattern, keyword in visual_patterns.items():
            if re.search(pattern, text_lower):
                cues.append(keyword)
        
        return list(set(cues))
    
    def find_broll_for_text(
        self,
        text: str,
        max_clips: int = 5,
        sources: List[str] = None,
    ) -> List[StockClip]:
        """
        Find B-roll clips for a piece of text.
        
        Args:
            text: Text to find B-roll for.
            max_clips: Maximum clips to return.
            sources: Sources to search ("pexels", "pixabay").
        
        Returns:
            List of StockClip objects.
        """
        if sources is None:
            sources = ["pexels", "pixabay"]
        
        # Extract search terms
        visual_cues = self.extract_visual_cues(text)
        keywords = self.extract_keywords(text)
        
        # Build search queries
        search_queries = visual_cues[:3] if visual_cues else keywords[:3]
        
        if not search_queries:
            search_queries = ["background abstract"]
        
        all_clips = []
        
        for query in search_queries:
            clips_per_query = max(1, max_clips // len(search_queries))
            
            if "pexels" in sources:
                clips = self.pexels.search_videos(query, per_page=clips_per_query)
                all_clips.extend(clips)
            
            if "pixabay" in sources:
                clips = self.pixabay.search_videos(query, per_page=clips_per_query)
                all_clips.extend(clips)
        
        # Deduplicate by ID
        seen_ids = set()
        unique_clips = []
        for clip in all_clips:
            clip_key = f"{clip.source}:{clip.id}"
            if clip_key not in seen_ids:
                seen_ids.add(clip_key)
                unique_clips.append(clip)
        
        return unique_clips[:max_clips]
    
    def find_broll_for_script(
        self,
        script_sections: List[Dict[str, str]],
        clips_per_section: int = 3,
    ) -> List[BRollSuggestion]:
        """
        Find B-roll suggestions for each section of a script.
        
        Args:
            script_sections: List of dicts with 'name' and 'content' keys.
            clips_per_section: Number of clips to suggest per section.
        
        Returns:
            List of BRollSuggestion objects.
        """
        suggestions = []
        
        for section in script_sections:
            name = section.get("name", "")
            content = section.get("content", "")
            
            if not content.strip():
                continue
            
            keywords = self.extract_keywords(content)
            visual_cues = self.extract_visual_cues(content)
            all_keywords = visual_cues + [k for k in keywords if k not in visual_cues]
            
            clips = self.find_broll_for_text(
                content,
                max_clips=clips_per_section,
            )
            
            suggestions.append(BRollSuggestion(
                section_name=name,
                section_text=content[:200] + "..." if len(content) > 200 else content,
                keywords=all_keywords[:5],
                clips=clips,
                timestamp=section.get("timestamp"),
            ))
        
        return suggestions
    
    def search_clips(
        self,
        query: str,
        max_results: int = 10,
        source: Optional[str] = None,
    ) -> List[StockClip]:
        """
        Direct search for clips.
        
        Args:
            query: Search query.
            max_results: Maximum results.
            source: Specific source ("pexels" or "pixabay") or None for both.
        
        Returns:
            List of StockClip objects.
        """
        clips = []
        
        if source is None or source == "pexels":
            pexels_clips = self.pexels.search_videos(query, per_page=max_results)
            clips.extend(pexels_clips)
        
        if source is None or source == "pixabay":
            pixabay_clips = self.pixabay.search_videos(query, per_page=max_results)
            clips.extend(pixabay_clips)
        
        return clips[:max_results]

    def search_images(
        self,
        query: str,
        max_results: int = 12,
        source: Optional[str] = None,
    ) -> List[StockClip]:
        """Search stock-photo libraries. Only Pexels is wired today;
        ``source`` is reserved so we can add Pixabay images later without
        breaking the router contract."""
        if source not in (None, "pexels"):
            return []
        return self.pexels.search_images(query, per_page=max_results)

    def search_gifs(
        self,
        query: str,
        max_results: int = 12,
        source: Optional[str] = None,
    ) -> List[StockClip]:
        """Search animated-GIF libraries.

        Both Giphy and Tenor expose MP4 URLs per result so either is a
        drop-in B-roll source. We try them in this order:

          1. If ``source`` pins a specific provider, use only that one.
          2. Otherwise prefer ``giphy`` when its API key is configured
             (Giphy ships the user's existing key; Tenor would require a
             second sign-up). Fall back to ``tenor`` automatically when
             Giphy is unconfigured or returns nothing.

        Results are capped to ``max_results`` after merge so a healthy
        Giphy response doesn't get padded out with Tenor duplicates.
        """
        if source == "giphy":
            return self.giphy.search_gifs(query, limit=max_results)
        if source == "tenor":
            return self.tenor.search_gifs(query, limit=max_results)
        if source is not None:
            return []

        clips: List[StockClip] = []
        if self.giphy.api_key:
            clips = self.giphy.search_gifs(query, limit=max_results)
        if not clips and self.tenor.api_key:
            clips = self.tenor.search_gifs(query, limit=max_results)
        return clips[:max_results]


# Convenience functions
def find_broll(text: str, max_clips: int = 5) -> List[StockClip]:
    """
    Find B-roll clips for text.
    
    Args:
        text: Text to find B-roll for.
        max_clips: Maximum clips to return.
    
    Returns:
        List of StockClip objects.
    """
    finder = BRollFinder()
    return finder.find_broll_for_text(text, max_clips)


def search_stock_videos(query: str, max_results: int = 10) -> List[StockClip]:
    """
    Search for stock videos.
    
    Args:
        query: Search query.
        max_results: Maximum results.
    
    Returns:
        List of StockClip objects.
    """
    finder = BRollFinder()
    return finder.search_clips(query, max_results)
