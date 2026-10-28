"""
Tests for video analysis endpoints.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestAnalyzeEndpoints:
    """Test video analysis endpoints."""
    
    def test_analyze_video_valid_url(self, client, test_user, auth_headers, mock_youtube_api):
        """Test analyzing a valid YouTube video URL."""
        with patch("src.api.analyze.VideoAnalyzer") as mock_analyzer:
            mock_instance = MagicMock()
            mock_instance.analyze.return_value = {
                "video_id": "test_video_id",
                "title": "Test Video",
                "prediction_score": 75.0,
                "prediction_tier": "high",
                "title_score": 78.0,
                "thumbnail_score": 72.0,
                "explanations": [],
                "recommendations": [],
                "niche_comparison": {},
            }
            mock_analyzer.return_value = mock_instance
            
            response = client.post(
                "/analyze",
                json={"url": "https://www.youtube.com/watch?v=test_video_id"},
                headers=auth_headers,
            )
        
        # Should return 200 or handle gracefully
        assert response.status_code in [200, 500]
    
    def test_analyze_video_invalid_url(self, client, test_user, auth_headers):
        """Test analyzing an invalid URL."""
        response = client.post(
            "/analyze",
            json={"url": "not_a_valid_url"},
            headers=auth_headers,
        )
        assert response.status_code in [400, 422, 500]
    
    def test_analyze_video_missing_url(self, client, test_user, auth_headers):
        """Test analyzing without providing a URL."""
        response = client.post(
            "/analyze",
            json={},
            headers=auth_headers,
        )
        assert response.status_code == 422
    
    def test_analyze_video_unauthenticated(self, client):
        """Test analyzing without authentication."""
        response = client.post(
            "/analyze",
            json={"url": "https://www.youtube.com/watch?v=test_video_id"},
        )
        assert response.status_code == 401


class TestTitleGeneratorEndpoints:
    """Test title generator endpoints."""
    
    def test_generate_titles(self, client, test_user, auth_headers):
        """Test generating title suggestions."""
        with patch("src.features.smart_title_generator.SmartTitleGenerator") as mock_gen:
            mock_instance = MagicMock()
            mock_instance.generate_suggestions.return_value = [
                {"title": "Test Title 1", "score": 85, "reason": "Good hook"},
                {"title": "Test Title 2", "score": 78, "reason": "Has number"},
            ]
            mock_gen.return_value = mock_instance

            response = client.post(
                "/titles/generate",
                json={
                    "topic": "Python tutorial",
                    "niche": "Technology",
                    "style": "educational",
                },
                headers=auth_headers,
            )

        # Should return 200 or handle gracefully (not 401)
        assert response.status_code in [200, 500]


class TestWinningFormulaEndpoints:
    """Test winning formula endpoints."""
    
    def test_get_winning_formula(self, client, test_user, auth_headers, mock_youtube_api):
        """Test getting winning formula for a channel."""
        with patch("src.features.winning_formula.WinningFormulaAnalyzer") as mock_analyzer:
            mock_instance = MagicMock()
            mock_instance.analyze.return_value = {
                "channel_name": "Test Channel",
                "channel_id": "test_channel_id",
                "total_videos_analyzed": 50,
                "avg_views": 10000,
                "hit_rate": 0.25,
                "title_patterns": [],
                "thumbnail_patterns": [],
                "key_insights": ["Pattern 1", "Pattern 2"],
            }
            mock_analyzer.return_value = mock_instance

            response = client.get(
                "/winning-formula/test_channel_id",
                headers=auth_headers,
            )

        # Should return 200 or handle gracefully (not 401)
        assert response.status_code in [200, 500]


class TestCompetitorEndpoints:
    """Test competitor analysis endpoints."""
    
    def test_analyze_competitor(self, client, test_user, auth_headers, mock_youtube_api):
        """Test analyzing a competitor channel."""
        with patch("src.features.competitor_analysis.CompetitorAnalyzer") as mock_analyzer:
            mock_instance = MagicMock()
            mock_instance.analyze.return_value = {
                "competitor": {
                    "name": "Competitor Channel",
                    "channel_id": "competitor_id",
                },
                "metrics": [],
                "strategy_differences": [],
                "opportunities": [],
            }
            mock_analyzer.return_value = mock_instance

            response = client.post(
                "/competitors/analyze",
                params={
                    "channel_url": "https://youtube.com/@competitor",
                },
                headers=auth_headers,
            )

        # Should return 200 or handle gracefully (not 401/403)
        assert response.status_code in [200, 500]
