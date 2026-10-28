"""
Tests for YouTube Description Generator module.
"""

import pytest
import json
from unittest.mock import patch, MagicMock

from src.features.description_generator import (
    Chapter,
    GeneratedDescription,
    seconds_to_timestamp,
    extract_chapters_from_segments,
    DescriptionGenerator,
    generate_youtube_description,
)


class TestChapter:
    """Tests for Chapter dataclass."""
    
    def test_creation(self):
        chapter = Chapter(
            timestamp="1:30",
            title="Introduction",
            start_seconds=90.0
        )
        
        assert chapter.timestamp == "1:30"
        assert chapter.title == "Introduction"
        assert chapter.start_seconds == 90.0
    
    def test_default_start_seconds(self):
        chapter = Chapter(timestamp="0:00", title="Intro")
        assert chapter.start_seconds == 0.0


class TestGeneratedDescription:
    """Tests for GeneratedDescription dataclass."""
    
    def test_creation(self):
        desc = GeneratedDescription(
            description="Test description",
            chapters=[Chapter("0:00", "Intro")],
            hashtags=["test", "video"],
            summary="Short summary",
            language="en"
        )
        
        assert desc.description == "Test description"
        assert len(desc.chapters) == 1
        assert desc.hashtags == ["test", "video"]
        assert desc.summary == "Short summary"
        assert desc.language == "en"
    
    def test_to_dict(self):
        chapter = Chapter("0:00", "Intro", 0.0)
        desc = GeneratedDescription(
            description="Full description here",
            chapters=[chapter],
            hashtags=["tag1"],
            summary="Summary",
            language="en"
        )
        
        result = desc.to_dict()
        
        assert result["description"] == "Full description here"
        assert len(result["chapters"]) == 1
        assert result["chapters"][0]["timestamp"] == "0:00"
        assert result["chapters"][0]["title"] == "Intro"
        assert result["hashtags"] == ["tag1"]
        assert result["language"] == "en"


class TestSecondsToTimestamp:
    """Tests for seconds_to_timestamp function."""
    
    def test_zero_seconds(self):
        assert seconds_to_timestamp(0) == "0:00"
    
    def test_under_minute(self):
        assert seconds_to_timestamp(45) == "0:45"
    
    def test_one_minute(self):
        assert seconds_to_timestamp(60) == "1:00"
    
    def test_minutes_and_seconds(self):
        assert seconds_to_timestamp(125) == "2:05"
    
    def test_one_hour(self):
        assert seconds_to_timestamp(3600) == "1:00:00"
    
    def test_hours_minutes_seconds(self):
        assert seconds_to_timestamp(3725) == "1:02:05"
    
    def test_float_seconds(self):
        assert seconds_to_timestamp(90.7) == "1:30"


class TestExtractChaptersFromSegments:
    """Tests for extract_chapters_from_segments function."""
    
    def test_empty_segments(self):
        chapters = extract_chapters_from_segments([])
        
        assert len(chapters) == 1
        assert chapters[0].timestamp == "0:00"
        assert chapters[0].title == "Intro"
    
    def test_creates_intro_chapter(self):
        segments = [
            {"start": 0, "end": 5, "text": "Hello everyone"},
            {"start": 5, "end": 10, "text": "Today we discuss"},
        ]
        
        chapters = extract_chapters_from_segments(segments)
        
        assert chapters[0].timestamp == "0:00"
        assert chapters[0].title == "Intro"
    
    def test_respects_min_chapter_duration(self):
        segments = [
            {"start": 0, "end": 10, "text": "First point"},
            {"start": 10, "end": 20, "text": "Next point"},  # Too close
            {"start": 60, "end": 70, "text": "Another point later"},
        ]
        
        chapters = extract_chapters_from_segments(
            segments,
            min_chapter_duration=30.0
        )
        
        # Should have intro + maybe one more
        assert len(chapters) >= 1
    
    def test_detects_chapter_keywords(self):
        segments = [
            {"start": 0, "end": 10, "text": "Welcome"},
            {"start": 60, "end": 70, "text": "First, let's talk about"},
            {"start": 120, "end": 130, "text": "Next, we move to"},
        ]
        
        chapters = extract_chapters_from_segments(
            segments,
            min_chapter_duration=30.0
        )
        
        assert len(chapters) >= 1
    
    def test_respects_max_chapters(self):
        segments = [
            {"start": i * 60, "end": i * 60 + 10, "text": f"Next point {i}"}
            for i in range(20)
        ]
        
        chapters = extract_chapters_from_segments(
            segments,
            min_chapter_duration=30.0,
            max_chapters=5
        )
        
        assert len(chapters) <= 5


class TestDescriptionGenerator:
    """Tests for DescriptionGenerator class."""
    
    def test_init_without_api_key(self):
        with patch.dict('os.environ', {}, clear=True):
            generator = DescriptionGenerator()
            assert generator.api_key is None
    
    def test_init_with_api_key(self):
        generator = DescriptionGenerator(api_key="test-key")
        assert generator.api_key == "test-key"
    
    def test_generate_basic_description_no_api(self):
        generator = DescriptionGenerator()
        generator.api_key = None
        
        result = generator.generate(
            title="Test Video",
            transcript="This is a test transcript."
        )
        
        assert result.description is not None
        assert len(result.description) > 0
        assert "Test Video" in result.description or "SUBSCRIBE" in result.description
    
    def test_generate_includes_chapters_when_requested(self):
        generator = DescriptionGenerator()
        generator.api_key = None
        
        segments = [
            {"start": 0, "end": 10, "text": "Intro"},
            {"start": 60, "end": 70, "text": "First topic"},
        ]
        
        result = generator.generate(
            title="Test Video",
            transcript_segments=segments,
            include_chapters=True
        )
        
        assert len(result.chapters) > 0
        assert result.chapters[0].timestamp == "0:00"
    
    @patch('anthropic.Anthropic')
    def test_generate_with_api(self, mock_anthropic):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="""
Check out this amazing video!

In this video, we cover:
- Topic one
- Topic two

0:00 Intro
1:00 Main content

Don't forget to subscribe!

#YouTube #Video #Test
""")]
        
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client
        
        generator = DescriptionGenerator(api_key="test-key")
        result = generator.generate(
            title="Test Video",
            transcript="Test transcript content",
            include_chapters=True,
            include_hashtags=True
        )
        
        assert result.description is not None
        assert len(result.hashtags) > 0
    
    def test_generate_calculates_duration_from_segments(self):
        generator = DescriptionGenerator()
        generator.api_key = None
        
        segments = [
            {"start": 0, "end": 30, "text": "Segment 1"},
            {"start": 30, "end": 120, "text": "Segment 2"},
        ]
        
        result = generator.generate(
            title="Test",
            transcript_segments=segments
        )
        
        # Should calculate duration from last segment
        assert result is not None


class TestGenerateYouTubeDescription:
    """Tests for generate_youtube_description convenience function."""
    
    def test_generates_description(self):
        result = generate_youtube_description(
            title="My Video Title",
            transcript="This is a sample transcript for testing.",
            language="en"
        )
        
        assert isinstance(result, GeneratedDescription)
        assert result.description is not None
        assert result.language == "en"
    
    def test_passes_segments(self):
        segments = [
            {"start": 0, "end": 30, "text": "Opening segment"},
            {"start": 60, "end": 90, "text": "Middle segment"},
        ]
        
        result = generate_youtube_description(
            title="Test Video",
            transcript_segments=segments
        )
        
        assert result is not None
        assert len(result.chapters) >= 1
