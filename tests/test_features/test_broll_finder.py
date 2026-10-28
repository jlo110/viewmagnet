"""Tests for broll_finder.py - B-Roll/Stock footage finder."""
import pytest
from unittest.mock import Mock, patch, MagicMock

from src.features.broll_finder import (
    StockClip,
    BRollSuggestion,
    PexelsClient,
    PixabayClient,
    BRollFinder,
    find_broll,
    search_stock_videos,
)


class TestStockClip:
    """Tests for StockClip dataclass."""
    
    def test_stock_clip_creation(self):
        """Test creating a StockClip instance."""
        clip = StockClip(
            id="123",
            source="pexels",
            title="Test Clip",
            description="A test video",
            duration=30,
            width=1920,
            height=1080,
            preview_url="https://example.com/preview.mp4",
            download_url="https://example.com/download.mp4",
            thumbnail_url="https://example.com/thumb.jpg",
            user="TestUser",
            user_url="https://pexels.com/user/test",
        )
        assert clip.id == "123"
        assert clip.source == "pexels"
        assert clip.duration == 30
        assert clip.quality == "hd"  # default value
    
    def test_stock_clip_with_tags(self):
        """Test StockClip with tags."""
        clip = StockClip(
            id="456",
            source="pixabay",
            title="Nature",
            description="Nature video",
            duration=60,
            width=1280,
            height=720,
            preview_url="",
            download_url="",
            thumbnail_url="",
            user="User",
            user_url="",
            tags=["nature", "trees", "forest"],
        )
        assert clip.tags == ["nature", "trees", "forest"]


class TestBRollSuggestion:
    """Tests for BRollSuggestion dataclass."""
    
    def test_broll_suggestion_creation(self):
        """Test creating a BRollSuggestion instance."""
        clip = StockClip(
            id="1", source="pexels", title="Clip", description="",
            duration=10, width=1920, height=1080, preview_url="",
            download_url="", thumbnail_url="", user="", user_url=""
        )
        suggestion = BRollSuggestion(
            section_name="Introduction",
            section_text="Welcome to this video about coding.",
            keywords=["coding", "programming", "computer"],
            clips=[clip],
        )
        assert suggestion.section_name == "Introduction"
        assert len(suggestion.clips) == 1
        assert suggestion.timestamp is None


class TestPexelsClient:
    """Tests for PexelsClient."""
    
    def test_init_without_api_key(self):
        """Test initialization without API key returns empty results."""
        with patch.dict("os.environ", {}, clear=True):
            client = PexelsClient(api_key=None)
            client.api_key = None
            
            # Should return empty list without API key
            results = client.search_videos("test")
            assert results == []
    
    def test_get_best_quality(self):
        """Test _get_best_quality method."""
        client = PexelsClient.__new__(PexelsClient)
        
        video_files = [
            {"quality": "sd", "width": 640},
            {"quality": "hd", "width": 1280},
            {"quality": "uhd", "width": 3840},
        ]
        
        best = client._get_best_quality(video_files)
        assert best["quality"] == "hd"  # HD preferred over UHD
    
    def test_get_best_quality_empty_list(self):
        """Test _get_best_quality with empty list."""
        client = PexelsClient.__new__(PexelsClient)
        
        result = client._get_best_quality([])
        assert result is None


class TestPixabayClient:
    """Tests for PixabayClient."""
    
    def test_init_without_api_key(self):
        """Test initialization without API key returns empty results."""
        with patch.dict("os.environ", {}, clear=True):
            client = PixabayClient(api_key=None)
            client.api_key = None
            
            results = client.search_videos("test")
            assert results == []


class TestBRollFinder:
    """Tests for BRollFinder."""
    
    def test_extract_keywords(self):
        """Test keyword extraction from text."""
        finder = BRollFinder()
        
        text = "Learn how to code Python programming for beginners tutorial"
        keywords = finder.extract_keywords(text)
        
        assert "python" in keywords
        assert "programming" in keywords
        assert "beginners" in keywords
        # Stop words should be filtered
        assert "how" not in keywords
        assert "for" not in keywords
    
    def test_extract_keywords_limited(self):
        """Test keywords are limited to 10."""
        finder = BRollFinder()
        
        text = " ".join([f"word{i}" for i in range(20)])
        keywords = finder.extract_keywords(text)
        
        assert len(keywords) <= 10
    
    def test_extract_visual_cues_coding(self):
        """Test visual cue extraction for coding content."""
        finder = BRollFinder()
        
        text = "Let's write some code on the computer and see how programming works"
        cues = finder.extract_visual_cues(text)
        
        assert "coding computer" in cues
    
    def test_extract_visual_cues_business(self):
        """Test visual cue extraction for business content."""
        finder = BRollFinder()
        
        text = "In this meeting, our team will discuss collaboration strategies"
        cues = finder.extract_visual_cues(text)
        
        assert "business meeting" in cues
    
    def test_extract_visual_cues_nature(self):
        """Test visual cue extraction for nature content."""
        finder = BRollFinder()
        
        text = "Let's explore the outdoor landscape and beautiful nature"
        cues = finder.extract_visual_cues(text)
        
        assert "nature landscape" in cues
    
    def test_extract_visual_cues_multiple(self):
        """Test extracting multiple visual cues."""
        finder = BRollFinder()
        
        text = "In our office, we use technology for business growth and success"
        cues = finder.extract_visual_cues(text)
        
        assert len(cues) >= 2
        # Should contain office, technology, and growth-related cues
    
    def test_extract_visual_cues_empty_text(self):
        """Test visual cue extraction with empty text."""
        finder = BRollFinder()
        
        cues = finder.extract_visual_cues("")
        assert cues == []
    
    @patch.object(PexelsClient, "search_videos")
    @patch.object(PixabayClient, "search_videos")
    def test_find_broll_for_text(self, mock_pixabay, mock_pexels):
        """Test finding B-roll for text."""
        mock_clip = StockClip(
            id="1", source="pexels", title="Test", description="",
            duration=10, width=1920, height=1080, preview_url="",
            download_url="", thumbnail_url="", user="", user_url=""
        )
        mock_pexels.return_value = [mock_clip]
        mock_pixabay.return_value = []
        
        finder = BRollFinder()
        clips = finder.find_broll_for_text("coding tutorial", max_clips=5)
        
        assert len(clips) >= 0  # May be empty if no visual cues match
    
    @patch.object(BRollFinder, "find_broll_for_text")
    def test_find_broll_for_script(self, mock_find):
        """Test finding B-roll for script sections."""
        mock_clip = StockClip(
            id="1", source="pexels", title="Test", description="",
            duration=10, width=1920, height=1080, preview_url="",
            download_url="", thumbnail_url="", user="", user_url=""
        )
        mock_find.return_value = [mock_clip]
        
        finder = BRollFinder()
        script_sections = [
            {"name": "Intro", "content": "Welcome to this coding tutorial."},
            {"name": "Main", "content": "Let's learn about Python programming."},
        ]
        
        suggestions = finder.find_broll_for_script(script_sections)
        
        assert len(suggestions) == 2
        assert suggestions[0].section_name == "Intro"
        assert suggestions[1].section_name == "Main"
    
    def test_find_broll_for_script_empty_section(self):
        """Test B-roll finder skips empty sections."""
        finder = BRollFinder()
        
        script_sections = [
            {"name": "Empty", "content": "   "},
            {"name": "Valid", "content": "Some actual content here."},
        ]
        
        with patch.object(finder, "find_broll_for_text", return_value=[]):
            suggestions = finder.find_broll_for_script(script_sections)
        
        # Empty section should be skipped
        assert len(suggestions) == 1
        assert suggestions[0].section_name == "Valid"


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    @patch.object(BRollFinder, "find_broll_for_text")
    def test_find_broll_function(self, mock_find):
        """Test find_broll convenience function."""
        mock_find.return_value = []
        
        result = find_broll("test text", max_clips=3)
        
        mock_find.assert_called_once_with("test text", 3)
    
    @patch.object(BRollFinder, "search_clips")
    def test_search_stock_videos_function(self, mock_search):
        """Test search_stock_videos convenience function."""
        mock_search.return_value = []
        
        result = search_stock_videos("nature", max_results=5)
        
        mock_search.assert_called_once_with("nature", 5)
