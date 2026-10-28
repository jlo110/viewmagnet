"""
Tests for dashboard endpoints.
"""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock


class TestDashboardEndpoints:
    """Test dashboard endpoints."""
    
    def test_get_dashboard_stats_no_analyses(self, client, test_user, auth_headers):
        """Test dashboard stats for user with no analyses."""
        response = client.get(
            "/dashboard/stats",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["avg_prediction_score"] == 0
        assert data["videos_analyzed"] == 0
        # Remaining = plan limit - used; free plan = 5/month
        from src.config import PLAN_LIMITS
        free_limit = PLAN_LIMITS["free"]["analyses_per_month"]
        assert data["analyses_remaining"] == free_limit
        assert data["above_baseline_pct"] == 0
        assert data["recent_analyses"] == []
        assert data["performance_trend"] == []
    
    def test_get_dashboard_stats_with_analyses(self, client, test_user, auth_headers, db_session):
        """Test dashboard stats for user with analyses."""
        from src.database.models import UserVideoAnalysis
        
        # Create some test analyses
        analyses = [
            UserVideoAnalysis(
                user_id=test_user["id"],
                video_id=f"video_{i}",
                video_url=f"https://youtube.com/watch?v=video_{i}",
                title=f"Test Video {i}",
                prediction_score=60 + i * 5,
                prediction_tier="high" if i > 2 else "medium",
                analyzed_at=datetime.utcnow(),
            )
            for i in range(5)
        ]
        for analysis in analyses:
            db_session.add(analysis)
        db_session.commit()
        
        response = client.get(
            "/dashboard/stats",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["videos_analyzed"] == 5
        # Remaining reflects actual plan limit, not a hardcoded 500
        from src.config import PLAN_LIMITS
        free_limit = PLAN_LIMITS["free"]["analyses_per_month"]
        assert data["analyses_remaining"] == max(0, free_limit - data["analyses_used"])
        assert data["avg_prediction_score"] > 0
        assert len(data["recent_analyses"]) <= 5
    
    def test_get_analysis_history(self, client, test_user, auth_headers, db_session):
        """Test getting user's analysis history."""
        from src.database.models import UserVideoAnalysis
        
        # Create test analyses
        for i in range(3):
            analysis = UserVideoAnalysis(
                user_id=test_user["id"],
                video_id=f"history_video_{i}",
                video_url=f"https://youtube.com/watch?v=history_video_{i}",
                title=f"History Video {i}",
                prediction_score=70.0,
                prediction_tier="high",
                analyzed_at=datetime.utcnow(),
            )
            db_session.add(analysis)
        db_session.commit()
        
        response = client.get(
            "/analyses/history",
            params={"limit": 10},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "analyses" in data
        assert len(data["analyses"]) == 3
        assert data["total"] == 3
    
    def test_get_analysis_by_video_id(self, client, test_user, auth_headers, db_session):
        """Test getting a specific analysis by video ID."""
        from src.database.models import UserVideoAnalysis
        
        analysis = UserVideoAnalysis(
            user_id=test_user["id"],
            video_id="specific_video_id",
            video_url="https://youtube.com/watch?v=specific_video_id",
            title="Specific Video",
            prediction_score=85.0,
            prediction_tier="high",
            title_score=80.0,
            thumbnail_score=90.0,
            analyzed_at=datetime.utcnow(),
        )
        db_session.add(analysis)
        db_session.commit()
        
        response = client.get(
            "/analyses/specific_video_id",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["video_id"] == "specific_video_id"
        assert data["title"] == "Specific Video"
        assert data["prediction_score"] == 85.0
    
    def test_get_analysis_not_found(self, client, test_user, auth_headers):
        """Test getting a non-existent analysis."""
        response = client.get(
            "/analyses/nonexistent_video",
            headers=auth_headers,
        )
        assert response.status_code == 404
    
    def test_dashboard_stats_unauthenticated(self, client):
        """Test dashboard stats without authentication."""
        response = client.get("/dashboard/stats")
        assert response.status_code == 401
