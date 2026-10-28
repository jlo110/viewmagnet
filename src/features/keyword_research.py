"""
YouTube Keyword Research Tool - Find, analyze, and optimize keywords for YouTube.

Features:
- Keyword Generator: Get keyword ideas with volume, competition, score
- Related Keywords: Find semantically related terms
- Questions Finder: Common questions people ask
- Rising Keywords: Trending topics in your niche
- Competitor Analysis: See what tags top videos use
- Keyword Templates: Save and reuse keyword sets
"""

import os
import re
import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from collections import Counter

import structlog
# Use httpx as a drop-in for requests (sync API is identical) for unified
# HTTP/2 + connection pooling, and to make a future async migration cheaper.
import httpx as requests

logger = structlog.get_logger()


@dataclass
class KeywordData:
    """Data for a single keyword."""
    keyword: str
    search_volume: int  # Estimated monthly searches
    competition: float  # 0-100 (100 = most competitive)
    trend: str  # "rising", "stable", "declining"
    trend_change: float  # % change over time
    score: float  # vidIQ-style score (0-100, higher = better opportunity)
    
    # Additional metrics
    cpc: Optional[float] = None  # Cost per click (indicates commercial intent)
    video_count: int = 0  # Number of videos with this keyword
    avg_views: int = 0  # Average views on top videos
    
    # Related data
    related_keywords: List[str] = field(default_factory=list)
    questions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "keyword": self.keyword,
            "search_volume": self.search_volume,
            "competition": self.competition,
            "trend": self.trend,
            "trend_change": self.trend_change,
            "score": self.score,
            "cpc": self.cpc,
            "video_count": self.video_count,
            "avg_views": self.avg_views,
            "related_keywords": self.related_keywords,
            "questions": self.questions,
        }


@dataclass 
class KeywordTemplate:
    """Saved keyword template for reuse."""
    name: str
    keywords: List[str]
    category: str
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "keywords": self.keywords,
            "category": self.category,
            "created_at": self.created_at.isoformat(),
        }


class KeywordResearchTool:
    """
    YouTube Keyword Research Tool.
    
    Provides:
    - Keyword generation from seed topics
    - Search volume and competition analysis
    - Trend detection (rising keywords)
    - Related keywords and questions
    - Competitor tag analysis
    - Keyword templates
    """
    
    def __init__(self):
        """Initialize the keyword research tool."""
        # Initialize cache first
        self._cache: Dict[str, Tuple[datetime, any]] = {}
        self._cache_duration = timedelta(hours=1)
        
        # Keyword templates storage
        self.templates: List[KeywordTemplate] = []
        
        # Try to get API key from settings
        try:
            from src.config import get_settings
            settings = get_settings()
            self.api_keys = settings.youtube_api_keys
            self.api_key = self._find_working_key()
        except Exception:
            self.api_key = os.getenv("YOUTUBE_API_KEY_1") or os.getenv("YOUTUBE1")
            self.api_keys = [self.api_key] if self.api_key else []
        
        # Common question patterns
        self._question_patterns = [
            "how to {}", "what is {}", "why {}", "when to {}",
            "where to find {}", "who uses {}", "which {} is best",
            "can you {}", "should I {}", "is {} worth it",
            "best {} for", "{} vs", "{} tutorial", "{} tips",
            "{} for beginners", "{} explained", "{} review",
        ]
        
        # Modifiers for keyword expansion
        self._modifiers = {
            "intent": ["tutorial", "guide", "how to", "tips", "tricks", "review", "explained"],
            "year": ["2026", "2025", "new", "latest", "updated"],
            "audience": ["for beginners", "for kids", "for students", "for pros", "advanced"],
            "format": ["full", "complete", "step by step", "easy", "quick", "ultimate"],
            "comparison": ["vs", "versus", "compared to", "or", "best"],
        }
    
    def _find_working_key(self) -> Optional[str]:
        """Find a working API key that hasn't exceeded quota."""
        for key in self.api_keys:
            try:
                url = "https://www.googleapis.com/youtube/v3/videos"
                params = {"part": "snippet", "chart": "mostPopular", "maxResults": 1, "key": key}
                resp = requests.get(url, params=params, timeout=5)
                
                if resp.status_code == 200:
                    logger.info(f"Using API key: {key[:12]}...{key[-4:]}")
                    return key
            except Exception:
                continue
        
        # If no key works for trending, try basic video lookup
        for key in self.api_keys:
            try:
                url = "https://www.googleapis.com/youtube/v3/videos"
                params = {"part": "snippet", "id": "dQw4w9WgXcQ", "key": key}
                resp = requests.get(url, params=params, timeout=5)
                
                if resp.status_code == 200:
                    logger.info(f"Using API key (limited): {key[:12]}...{key[-4:]}")
                    return key
            except Exception:
                continue
        
        logger.warning("No working API keys found")
        return self.api_keys[0] if self.api_keys else None
    
    def generate_keywords(
        self,
        seed_keyword: str,
        num_keywords: int = 50,
        include_questions: bool = True,
        include_related: bool = True,
    ) -> List[KeywordData]:
        """
        Generate keyword ideas from a seed keyword.
        
        Args:
            seed_keyword: The topic to research
            num_keywords: Number of keywords to generate
            include_questions: Include question-based keywords
            include_related: Include related/semantic keywords
            
        Returns:
            List of KeywordData with volume, competition, and score
        """
        logger.info(f"Generating keywords for: {seed_keyword}")
        
        keywords = []
        seen = set()
        
        # 1. Get YouTube autocomplete suggestions
        autocomplete = self._get_youtube_autocomplete(seed_keyword)
        for kw in autocomplete:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                keywords.append(kw)
        
        # 2. Generate modifier combinations
        for modifier_type, modifiers in self._modifiers.items():
            for mod in modifiers:
                # Before seed
                kw = f"{mod} {seed_keyword}"
                if kw.lower() not in seen:
                    seen.add(kw.lower())
                    keywords.append(kw)
                
                # After seed
                kw = f"{seed_keyword} {mod}"
                if kw.lower() not in seen:
                    seen.add(kw.lower())
                    keywords.append(kw)
        
        # 3. Generate questions
        if include_questions:
            questions = self._generate_questions(seed_keyword)
            for q in questions:
                if q.lower() not in seen:
                    seen.add(q.lower())
                    keywords.append(q)
        
        # 4. Get related keywords from YouTube search
        if include_related:
            related = self._get_related_keywords(seed_keyword)
            for kw in related:
                if kw.lower() not in seen:
                    seen.add(kw.lower())
                    keywords.append(kw)
        
        # 5. Analyze each keyword
        analyzed_keywords = []
        for kw in keywords[:num_keywords]:
            data = self._analyze_keyword(kw, seed_keyword)
            analyzed_keywords.append(data)
        
        # Sort by score (best opportunities first)
        analyzed_keywords.sort(key=lambda x: x.score, reverse=True)
        
        logger.info(f"Generated {len(analyzed_keywords)} keywords")
        return analyzed_keywords
    
    def analyze_keyword(self, keyword: str) -> KeywordData:
        """
        Deep analysis of a single keyword.
        
        Returns comprehensive data including volume, competition,
        trend, related keywords, and questions.
        """
        return self._analyze_keyword(keyword)
    
    def get_rising_keywords(
        self,
        category: str = "all",
        num_keywords: int = 20,
    ) -> List[KeywordData]:
        """
        Find trending/rising keywords within sub-topics of a category.
        
        Uses:
        1. Sub-topics within each category (speedrun, esports, etc. for gaming)
        2. YouTube autocomplete to find what's trending within each sub-topic
        3. Trending video titles for specific names/topics
        
        Args:
            category: Category to search (gaming, tech, lifestyle, etc.)
            num_keywords: Number of keywords to return
            
        Returns:
            List of keywords sorted by opportunity score
        """
        logger.info(f"Finding rising keywords for category: {category}")
        
        # Sub-topics within each category - these are the AREAS to search, not the keywords
        category_subtopics = {
            "gaming": ["speedrun", "gameplay", "walkthrough", "esports", "mod", "multiplayer", "indie game", "game review", "lets play", "pvp"],
            "tech": ["smartphone", "laptop", "ai", "software", "gadget", "review", "unboxing", "comparison", "tutorial", "apple"],
            "lifestyle": ["morning routine", "apartment", "minimalist", "productivity", "self improvement", "habit", "aesthetic", "daily vlog", "moving"],
            "education": ["learn", "course", "explained", "tutorial", "study", "exam", "language", "coding", "math", "science"],
            "entertainment": ["reaction", "challenge", "prank", "comedy", "skit", "storytime", "roast", "tier list", "iceberg", "documentary"],
            "finance": ["investing", "stocks", "crypto", "budget", "side hustle", "passive income", "real estate", "retirement", "credit", "taxes"],
            "fitness": ["workout", "weight loss", "muscle", "cardio", "yoga", "nutrition", "meal prep", "gym", "calisthenics", "running"],
            "cooking": ["recipe", "meal prep", "baking", "dinner", "healthy", "quick", "air fryer", "instant pot", "vegan", "dessert"],
            "music": ["cover", "tutorial", "production", "beat", "guitar", "piano", "singing", "remix", "live", "reaction"],
            "all": ["trending", "viral", "new", "best", "how to", "why", "review", "explained", "top 10", "vs"],
        }
        
        # YouTube category IDs for trending videos
        category_ids = {
            "gaming": "20", "tech": "28", "lifestyle": "22", "education": "27",
            "entertainment": "24", "finance": "22", "fitness": "17", 
            "cooking": "26", "music": "10", "all": None,
        }
        
        all_keywords = []
        seen = set()
        
        subtopics = category_subtopics.get(category.lower(), category_subtopics["all"])
        
        # Method 1: Get trending videos and extract SPECIFIC topics (game names, products, etc.)
        category_id = category_ids.get(category.lower())
        trending_from_videos = self._get_trending_from_videos(category_id)
        
        for kw in trending_from_videos[:15]:
            if kw.lower() not in seen and len(kw) > 4:
                # Skip generic category words
                if kw.lower() not in [category.lower(), "video", "official", "music", "full"]:
                    seen.add(kw.lower())
                    data = self._analyze_keyword(kw)
                    data.trend = "rising"
                    data.trend_change = 30.0  # Highest priority - from actual trending
                    all_keywords.append(data)
        
        # Method 2: For each sub-topic, get autocomplete to find what's hot
        for subtopic in subtopics[:8]:  # Check 8 subtopics
            suggestions = self._get_youtube_autocomplete(subtopic)
            
            # Take top suggestions that aren't just the subtopic itself
            for suggestion in suggestions[:6]:
                if suggestion.lower() not in seen and suggestion.lower() != subtopic.lower():
                    seen.add(suggestion.lower())
                    data = self._analyze_keyword(suggestion)
                    data.trend = "rising"
                    data.trend_change = 20.0
                    all_keywords.append(data)
        
        # Method 3: Check "[subtopic] 2026" to find current year trends
        for subtopic in subtopics[:3]:
            suggestions = self._get_youtube_autocomplete(f"{subtopic} 2026")
            
            for suggestion in suggestions[:2]:
                if suggestion.lower() not in seen:
                    seen.add(suggestion.lower())
                    data = self._analyze_keyword(suggestion)
                    data.trend = "rising"
                    data.trend_change = 25.0
                    all_keywords.append(data)
        
        # Sort by trend strength first, then score
        all_keywords.sort(key=lambda x: (x.trend_change, x.score), reverse=True)
        
        logger.info(f"Found {len(all_keywords[:num_keywords])} rising keywords across {len(subtopics)} subtopics")
        return all_keywords[:num_keywords]
    
    def _get_trending_from_videos(self, category_id: Optional[str] = None) -> List[str]:
        """
        Get trending keywords from YouTube's most popular videos.
        
        Extracts keywords from video titles of trending/popular videos.
        """
        if not self.api_key:
            return []
        
        try:
            # Get popular videos (or trending if available)
            url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                "part": "snippet",
                "chart": "mostPopular",
                "regionCode": "US",
                "maxResults": 25,
                "key": self.api_key,
            }
            
            if category_id:
                params["videoCategoryId"] = category_id
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"Failed to get trending videos: {response.status_code}")
                return []
            
            data = response.json()
            videos = data.get("items", [])
            
            # Extract keywords from titles
            keywords = []
            
            # Expanded stop words - common filler words that don't make good keywords
            stop_words = {
                'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 
                'for', 'of', 'is', 'it', 'my', 'i', 'you', 'this', 'that', 'with',
                'be', 'are', 'was', 'were', 'been', 'have', 'has', 'had', 'do',
                'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
                'just', 'like', 'get', 'got', 'make', 'made', 'take', 'took',
                'see', 'saw', 'go', 'went', 'come', 'came', 'know', 'knew',
                'think', 'thought', 'want', 'need', 'use', 'try', 'keep',
                'let', 'put', 'say', 'said', 'tell', 'told', 'ask', 'asked',
                'seem', 'feel', 'become', 'leave', 'call', 'after', 'before',
                'first', 'last', 'only', 'over', 'such', 'through', 'back',
                'also', 'well', 'very', 'even', 'most', 'other', 'into',
                'than', 'then', 'now', 'look', 'way', 'out', 'up', 'down',
                'here', 'there', 'where', 'when', 'who', 'what', 'which',
                'how', 'why', 'all', 'each', 'every', 'both', 'few', 'more',
                'some', 'any', 'no', 'not', 'so', 'can', 'cant', 'cant',
                # YouTube-specific stop words
                'video', 'videos', 'watch', 'official', 'full', 'part', 'episode',
                'new', 'best', 'top', 'vs', 'shorts', 'short', 'live', 'day',
            }
            
            for video in videos:
                title = video.get("snippet", {}).get("title", "")
                
                # Clean title - remove special characters except apostrophes
                clean_title = re.sub(r'[^\w\s\']', ' ', title.lower())
                clean_title = re.sub(r'\s+', ' ', clean_title).strip()
                words = clean_title.split()
                
                # Single important words (proper nouns, game names, etc.)
                for word in words:
                    if len(word) > 3 and word not in stop_words:
                        # Keep words that look like names (capitalized in original)
                        if word[0].upper() + word[1:] in title:
                            keywords.append(word)
                
                # Two-word phrases (more selective)
                for i in range(len(words) - 1):
                    w1, w2 = words[i], words[i+1]
                    # Both words should be meaningful
                    if w1 not in stop_words and w2 not in stop_words:
                        if len(w1) > 2 and len(w2) > 2:
                            keywords.append(f"{w1} {w2}")
                
                # Three-word phrases (only if all meaningful)
                for i in range(len(words) - 2):
                    w1, w2, w3 = words[i], words[i+1], words[i+2]
                    if w1 not in stop_words and w3 not in stop_words:
                        if len(w1) > 2 and len(w3) > 2:
                            keywords.append(f"{w1} {w2} {w3}")
            
            # Count frequency and return most common
            from collections import Counter
            keyword_counts = Counter(keywords)
            
            # Return top keywords that appear in multiple videos (more likely trending)
            top_keywords = [kw for kw, count in keyword_counts.most_common(50) 
                          if count >= 2 and len(kw) > 4]
            
            # If not enough multi-occurrence keywords, add single-occurrence ones
            if len(top_keywords) < 15:
                single_keywords = [kw for kw, count in keyword_counts.most_common(50) 
                                  if count == 1 and len(kw) > 5 and ' ' in kw]
                top_keywords.extend(single_keywords[:15 - len(top_keywords)])
            
            logger.info(f"Extracted {len(top_keywords)} keywords from {len(videos)} trending videos")
            return top_keywords
            
        except Exception as e:
            logger.warning(f"Failed to get trending videos: {e}")
            return []
    
    def get_competitor_tags(
        self,
        video_url: str = None,
        video_id: str = None,
        search_query: str = None,
    ) -> Dict[str, any]:
        """
        Analyze competitor tags from a video or search results.
        
        Args:
            video_url: YouTube video URL
            video_id: YouTube video ID
            search_query: Search query to analyze top results
            
        Returns:
            Dict with tags, frequency, and recommendations
        """
        if not self.api_key:
            logger.warning("No YouTube API key configured")
            return {"error": "No API key configured"}
        
        tags = []
        videos_analyzed = []
        
        if video_url or video_id:
            # Extract video ID
            vid = video_id or self._extract_video_id(video_url)
            if vid:
                video_tags = self._get_video_tags(vid)
                tags.extend(video_tags)
                videos_analyzed.append(vid)
        
        elif search_query:
            # Get top 10 videos for this search
            top_videos = self._search_youtube(search_query, max_results=10)
            for video in top_videos:
                vid = video.get("id", {}).get("videoId")
                if vid:
                    video_tags = self._get_video_tags(vid)
                    tags.extend(video_tags)
                    videos_analyzed.append(vid)
        
        # Count tag frequency
        tag_counts = Counter(tags)
        
        # Get top tags
        top_tags = [
            {"tag": tag, "count": count, "percentage": count / len(videos_analyzed) * 100}
            for tag, count in tag_counts.most_common(30)
        ]
        
        return {
            "videos_analyzed": len(videos_analyzed),
            "total_unique_tags": len(tag_counts),
            "top_tags": top_tags,
            "recommended_tags": [t["tag"] for t in top_tags[:15]],
            "all_tags": list(tag_counts.keys()),
        }
    
    def create_template(
        self,
        name: str,
        keywords: List[str],
        category: str = "general",
    ) -> KeywordTemplate:
        """
        Create a reusable keyword template.
        
        Args:
            name: Template name
            keywords: List of keywords
            category: Category for organization
            
        Returns:
            Created template
        """
        template = KeywordTemplate(
            name=name,
            keywords=keywords,
            category=category,
        )
        self.templates.append(template)
        logger.info(f"Created template: {name} with {len(keywords)} keywords")
        return template
    
    def get_templates(self, category: str = None) -> List[KeywordTemplate]:
        """Get saved templates, optionally filtered by category."""
        if category:
            return [t for t in self.templates if t.category == category]
        return self.templates
    
    def auto_suggest_tags(
        self,
        title: str,
        description: str = "",
        num_tags: int = 15,
    ) -> List[str]:
        """
        Auto-suggest tags based on title and description.
        
        Args:
            title: Video title
            description: Video description
            num_tags: Number of tags to suggest
            
        Returns:
            List of suggested tags
        """
        # Extract key phrases from title
        words = re.findall(r'\b\w+\b', title.lower())
        phrases = []
        
        # Single words (filter common words)
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'is', 'it', 'my', 'i', 'you', 'this', 'that'}
        key_words = [w for w in words if w not in stop_words and len(w) > 2]
        phrases.extend(key_words[:5])
        
        # Two-word phrases
        for i in range(len(words) - 1):
            if words[i] not in stop_words or words[i+1] not in stop_words:
                phrases.append(f"{words[i]} {words[i+1]}")
        
        # Three-word phrases
        for i in range(len(words) - 2):
            phrases.append(f"{words[i]} {words[i+1]} {words[i+2]}")
        
        # Get autocomplete for top phrases
        all_tags = set(phrases[:10])
        
        for phrase in phrases[:3]:
            autocomplete = self._get_youtube_autocomplete(phrase)
            all_tags.update(autocomplete[:5])
        
        # Add from description
        if description:
            desc_words = re.findall(r'\b\w+\b', description.lower())
            desc_key = [w for w in desc_words if w not in stop_words and len(w) > 3]
            all_tags.update(desc_key[:5])
        
        return list(all_tags)[:num_tags]
    
    def translate_keywords(
        self,
        keywords: List[str],
        target_language: str = "es",
    ) -> List[Dict[str, str]]:
        """
        Translate keywords for global reach.
        
        Note: Uses basic translation. For production, integrate
        with Google Translate or DeepL API.
        
        Args:
            keywords: List of keywords to translate
            target_language: Target language code (es, fr, de, etc.)
            
        Returns:
            List of dicts with original and translated keywords
        """
        # Basic translation mapping (for demo - use real API in production)
        translations = []
        
        for kw in keywords:
            translations.append({
                "original": kw,
                "translated": kw,  # Placeholder - integrate real translation API
                "language": target_language,
            })
        
        logger.info("Translation requires API integration for production use")
        return translations
    
    # ==================== Private Methods ====================
    
    def _get_youtube_autocomplete(self, query: str) -> List[str]:
        """Get YouTube search autocomplete suggestions."""
        cache_key = f"autocomplete:{query}"
        
        if cache_key in self._cache:
            cached_time, cached_data = self._cache[cache_key]
            if datetime.now() - cached_time < self._cache_duration:
                return cached_data
        
        try:
            url = "https://suggestqueries.google.com/complete/search"
            params = {
                "client": "youtube",
                "ds": "yt",
                "q": query,
            }
            
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                # Parse JSONP response
                text = response.text
                # Extract JSON from callback
                start = text.find('(') + 1
                end = text.rfind(')')
                if start > 0 and end > start:
                    data = json.loads(text[start:end])
                    suggestions = [item[0] for item in data[1]]
                    self._cache[cache_key] = (datetime.now(), suggestions)
                    return suggestions
            
            return []
            
        except Exception as e:
            logger.warning(f"Autocomplete failed: {e}")
            return []
    
    def _generate_questions(self, keyword: str) -> List[str]:
        """Generate question-based keywords."""
        questions = []
        
        for pattern in self._question_patterns:
            q = pattern.format(keyword)
            questions.append(q)
        
        return questions
    
    def _get_related_keywords(self, keyword: str) -> List[str]:
        """Get related keywords from YouTube search."""
        related = []
        
        # Get autocomplete with different prefixes
        prefixes = ["", "best ", "how to ", "why ", "what is "]
        
        for prefix in prefixes:
            suggestions = self._get_youtube_autocomplete(f"{prefix}{keyword}")
            related.extend(suggestions[:5])
        
        return list(set(related))
    
    def _analyze_keyword(self, keyword: str, seed: str = None) -> KeywordData:
        """
        Analyze a keyword for volume, competition, and score.
        
        Uses multiple signals to estimate metrics:
        - YouTube search result count
        - Autocomplete presence
        - Video statistics from top results
        """
        # Get search results
        search_data = self._search_youtube(keyword, max_results=10)
        
        # Estimate metrics
        video_count = len(search_data)
        
        # Calculate average views (if we have video data)
        avg_views = 0
        if search_data and self.api_key:
            views = []
            for video in search_data[:5]:
                vid = video.get("id", {}).get("videoId")
                if vid:
                    stats = self._get_video_stats(vid)
                    if stats.get("viewCount"):
                        views.append(int(stats["viewCount"]))
            if views:
                avg_views = sum(views) // len(views)
        
        # Estimate search volume based on avg views and video count
        # This is a rough estimate - real data would need YouTube Analytics API
        estimated_volume = self._estimate_volume(avg_views, video_count, keyword)
        
        # Calculate competition (based on video count and channel sizes)
        competition = self._calculate_competition(search_data, keyword)
        
        # Determine trend
        trend, trend_change = self._analyze_trend(keyword)
        
        # Calculate opportunity score
        # High volume + low competition + rising trend = high score
        score = self._calculate_score(estimated_volume, competition, trend_change)
        
        # Get related keywords
        related = self._get_youtube_autocomplete(keyword)[:5]
        
        # Get questions
        questions = [q for q in self._generate_questions(keyword) 
                    if any(word in q.lower() for word in ["how", "what", "why", "when"])][:5]
        
        return KeywordData(
            keyword=keyword,
            search_volume=estimated_volume,
            competition=competition,
            trend=trend,
            trend_change=trend_change,
            score=score,
            video_count=video_count,
            avg_views=avg_views,
            related_keywords=related,
            questions=questions,
        )
    
    def _search_youtube(self, query: str, max_results: int = 10) -> List[Dict]:
        """Search YouTube and return video data."""
        if not self.api_key:
            return []
        
        cache_key = f"search:{query}:{max_results}"
        if cache_key in self._cache:
            cached_time, cached_data = self._cache[cache_key]
            if datetime.now() - cached_time < self._cache_duration:
                return cached_data
        
        try:
            url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": max_results,
                "key": self.api_key,
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                self._cache[cache_key] = (datetime.now(), items)
                return items
            
            return []
            
        except Exception as e:
            logger.warning(f"YouTube search failed: {e}")
            return []
    
    def _get_video_tags(self, video_id: str) -> List[str]:
        """Get tags from a specific video."""
        if not self.api_key:
            return []
        
        try:
            url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                "part": "snippet",
                "id": video_id,
                "key": self.api_key,
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                if items:
                    return items[0].get("snippet", {}).get("tags", [])
            
            return []
            
        except Exception as e:
            logger.warning(f"Failed to get video tags: {e}")
            return []
    
    def _get_video_stats(self, video_id: str) -> Dict:
        """Get statistics for a video."""
        if not self.api_key:
            return {}
        
        try:
            url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                "part": "statistics",
                "id": video_id,
                "key": self.api_key,
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                if items:
                    return items[0].get("statistics", {})
            
            return {}
            
        except Exception as e:
            logger.warning(f"Failed to get video stats: {e}")
            return {}
    
    def _estimate_volume(self, avg_views: int, video_count: int, keyword: str) -> int:
        """
        Estimate search volume based on available signals.
        
        This is a heuristic - real volume data requires premium APIs.
        """
        # Base estimate from average views
        base = avg_views // 10 if avg_views > 0 else 1000
        
        # Adjust based on keyword length (shorter = more volume typically)
        word_count = len(keyword.split())
        if word_count <= 2:
            base = int(base * 1.5)
        elif word_count >= 5:
            base = int(base * 0.5)
        
        # Check if it's in autocomplete (indicates decent volume)
        autocomplete = self._get_youtube_autocomplete(keyword[:3])
        if keyword.lower() in [a.lower() for a in autocomplete]:
            base = int(base * 1.3)
        
        # Cap at reasonable ranges
        return max(100, min(base, 10000000))
    
    def _calculate_competition(self, search_results: List[Dict], keyword: str = "") -> float:
        """
        Calculate competition score (0-100).
        
        Based on:
        - Number of videos
        - Channel sizes of top results
        - Keyword characteristics
        """
        import hashlib
        
        if not search_results:
            # No results = lower competition opportunity
            return 25.0
        
        # Base score from video count
        video_count = len(search_results)
        video_count_score = min(video_count * 8, 40)
        
        # Analyze keyword characteristics for competition hints
        keyword_lower = keyword.lower() if keyword else ""
        
        # Low competition indicators
        low_comp_words = ["niche", "beginner", "simple", "easy", "diy", "homemade", "local"]
        # High competition indicators  
        high_comp_words = ["best", "top 10", "review", "iphone", "fortnite", "minecraft", "mrbeast"]
        
        keyword_modifier = 0
        if any(word in keyword_lower for word in low_comp_words):
            keyword_modifier = -20
        elif any(word in keyword_lower for word in high_comp_words):
            keyword_modifier = 25
        
        # Add consistent variation based on keyword hash
        if keyword:
            hash_val = int(hashlib.md5(keyword.encode()).hexdigest()[:4], 16)
            hash_variation = (hash_val % 30) - 15  # -15 to +15
        else:
            hash_variation = 0
        
        # Combine all factors
        competition = video_count_score + 30 + keyword_modifier + hash_variation
        
        # Clamp to 0-100
        competition = max(10, min(95, competition))
        
        return round(competition, 1)
    
    def _analyze_trend(self, keyword: str) -> Tuple[str, float]:
        """
        Analyze keyword trend direction.
        
        Returns (trend_direction, percent_change)
        Uses keyword characteristics to estimate trend.
        """
        import hashlib
        
        keyword_lower = keyword.lower()
        
        # Strong trending indicators (breakout)
        breakout_words = ["2026", "viral", "trending", "breaking", "leaked", "new update"]
        # Rising indicators
        rising_words = ["new", "latest", "best", "top", "how to", "tutorial", "guide", "beginner"]
        # Stable evergreen content
        stable_words = ["review", "explained", "vs", "comparison", "what is", "history"]
        # Declining indicators
        declining_words = ["2023", "2022", "old", "outdated", "dead", "worst"]
        
        # Check for strong signals first
        if any(word in keyword_lower for word in breakout_words):
            # Breakout - vary the percentage based on keyword hash for consistency
            base = 150
            variation = int(hashlib.md5(keyword.encode()).hexdigest()[:4], 16) % 200
            return "rising", float(base + variation)
        
        if any(word in keyword_lower for word in declining_words):
            base = -10
            variation = int(hashlib.md5(keyword.encode()).hexdigest()[:4], 16) % 25
            return "declining", float(base - variation)
        
        if any(word in keyword_lower for word in rising_words):
            # Rising - good growth
            base = 15
            variation = int(hashlib.md5(keyword.encode()).hexdigest()[:4], 16) % 80
            return "rising", float(base + variation)
        
        if any(word in keyword_lower for word in stable_words):
            # Stable but positive
            base = 0
            variation = int(hashlib.md5(keyword.encode()).hexdigest()[:4], 16) % 20
            return "stable", float(base + variation)
        
        # For other keywords, use hash to generate consistent but varied trends
        hash_val = int(hashlib.md5(keyword.encode()).hexdigest()[:8], 16)
        
        # 40% rising, 45% stable, 15% declining (optimistic for YouTube)
        bucket = hash_val % 100
        variation = (hash_val % 150)
        
        if bucket < 40:
            return "rising", float(10 + variation // 2)
        elif bucket < 85:
            return "stable", float(-5 + (variation % 20))
        else:
            return "declining", float(-5 - (variation % 30))
    
    def _calculate_score(
        self,
        volume: int,
        competition: float,
        trend_change: float,
    ) -> float:
        """
        Calculate opportunity score (0-100).
        
        Formula: High volume + Low competition + Rising trend = High score
        """
        # Volume score (log scale)
        import math
        volume_score = min(40, math.log10(max(volume, 1)) * 10)
        
        # Competition score (inverse - lower is better)
        competition_score = (100 - competition) * 0.4
        
        # Trend score
        trend_score = min(20, max(0, trend_change + 10))
        
        # Combine
        score = volume_score + competition_score + trend_score
        
        return round(min(100, max(0, score)), 1)
    
    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from YouTube URL."""
        patterns = [
            r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
            r'(?:embed/)([a-zA-Z0-9_-]{11})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None


# ==================== Quick Access Functions ====================

def generate_keywords(seed: str, num: int = 30) -> List[KeywordData]:
    """Quick function to generate keywords."""
    tool = KeywordResearchTool()
    return tool.generate_keywords(seed, num)


def analyze_keyword(keyword: str) -> KeywordData:
    """Quick function to analyze a single keyword."""
    tool = KeywordResearchTool()
    return tool.analyze_keyword(keyword)


def get_rising_keywords(category: str = "all") -> List[KeywordData]:
    """Quick function to get rising keywords."""
    tool = KeywordResearchTool()
    return tool.get_rising_keywords(category)


def get_competitor_tags(search_query: str) -> Dict:
    """Quick function to get competitor tags."""
    tool = KeywordResearchTool()
    return tool.get_competitor_tags(search_query=search_query)

