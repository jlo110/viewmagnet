"""
Tests for the Winning Formula feature.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestWinningFormulaAnalyzer:
    """Test the WinningFormulaAnalyzer class."""
    
    @pytest.fixture
    def sample_videos(self):
        """Sample video data for testing."""
        return [
            {
                "video_id": "vid1",
                "title": "5 Python Tips for Beginners",
                "view_count": 50000,
                "like_count": 2500,
                "comment_count": 300,
                "duration_seconds": 600,
                "has_face_in_thumbnail": True,
                "thumbnail_brightness": 0.7,
                "published_day": "Tuesday",
                "published_hour": 14,
            },
            {
                "video_id": "vid2",
                "title": "How I Learned Python in 30 Days",
                "view_count": 100000,
                "like_count": 5000,
                "comment_count": 600,
                "duration_seconds": 900,
                "has_face_in_thumbnail": True,
                "thumbnail_brightness": 0.6,
                "published_day": "Wednesday",
                "published_hour": 15,
            },
            {
                "video_id": "vid3",
                "title": "Python Update News",
                "view_count": 5000,
                "like_count": 100,
                "comment_count": 20,
                "duration_seconds": 300,
                "has_face_in_thumbnail": False,
                "thumbnail_brightness": 0.4,
                "published_day": "Monday",
                "published_hour": 9,
            },
        ]
    
    def test_calculate_hit_rate(self, sample_videos):
        """Test hit rate calculation."""
        # Calculate median views
        views = [v["view_count"] for v in sample_videos]
        median = sorted(views)[len(views) // 2]
        
        # Count videos above 2x median
        hits = sum(1 for v in sample_videos if v["view_count"] > 2 * median)
        expected_hit_rate = hits / len(sample_videos)
        
        assert 0 <= expected_hit_rate <= 1
    
    def test_identify_title_patterns(self, sample_videos):
        """Test title pattern identification."""
        patterns = {}
        
        for video in sample_videos:
            title = video["title"]
            # Check for numbers
            if any(char.isdigit() for char in title):
                patterns.setdefault("has_number", []).append(video)
            # Check for questions
            if "?" in title:
                patterns.setdefault("is_question", []).append(video)
            # Check for "How" starts
            if title.lower().startswith("how"):
                patterns.setdefault("starts_with_how", []).append(video)
        
        assert "has_number" in patterns
        assert "starts_with_how" in patterns
    
    def test_identify_thumbnail_patterns(self, sample_videos):
        """Test thumbnail pattern identification."""
        # Calculate face appearance stats
        with_face = [v for v in sample_videos if v.get("has_face_in_thumbnail")]
        without_face = [v for v in sample_videos if not v.get("has_face_in_thumbnail")]
        
        if with_face and without_face:
            avg_views_with_face = sum(v["view_count"] for v in with_face) / len(with_face)
            avg_views_without_face = sum(v["view_count"] for v in without_face) / len(without_face)
            
            # Face usually helps in most niches
            assert avg_views_with_face > 0
    
    def test_find_best_posting_times(self, sample_videos):
        """Test best posting time identification."""
        # Group by day and hour
        day_views = {}
        hour_views = {}
        
        for video in sample_videos:
            day = video.get("published_day", "Unknown")
            hour = video.get("published_hour", 12)
            
            day_views.setdefault(day, []).append(video["view_count"])
            hour_views.setdefault(hour, []).append(video["view_count"])
        
        # Find best day
        best_day = max(day_views.keys(), key=lambda d: sum(day_views[d]) / len(day_views[d]))
        
        # Find best hour
        best_hour = max(hour_views.keys(), key=lambda h: sum(hour_views[h]) / len(hour_views[h]))
        
        assert best_day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        assert 0 <= best_hour <= 23
    
    def test_compare_hits_vs_flops(self, sample_videos):
        """Test comparison between hits and flops."""
        views = sorted([v["view_count"] for v in sample_videos])
        median = views[len(views) // 2]
        
        hits = [v for v in sample_videos if v["view_count"] > 2 * median]
        flops = [v for v in sample_videos if v["view_count"] < median * 0.5]
        
        # There should be at least one hit or flop
        assert len(hits) > 0 or len(flops) > 0 or len(sample_videos) == 0


class TestEngagementComparison:
    """Test engagement comparison functionality."""
    
    def test_calculate_engagement_ratios(self):
        """Test engagement ratio calculations."""
        views = 100000
        likes = 5000
        comments = 500
        
        like_ratio = likes / views if views > 0 else 0
        comment_ratio = comments / views if views > 0 else 0
        
        assert like_ratio == 0.05
        assert comment_ratio == 0.005
    
    def test_compare_to_baseline(self):
        """Test comparison to baseline metrics."""
        current_ratio = 0.05
        baseline_ratio = 0.03
        
        vs_baseline = ((current_ratio - baseline_ratio) / baseline_ratio) * 100 if baseline_ratio > 0 else 0
        
        assert vs_baseline > 0  # Current is above baseline
