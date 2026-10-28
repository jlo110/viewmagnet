"""
Tests for health check endpoints.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestHealthEndpoints:
    """Test health check endpoints."""
    
    def test_root_endpoint(self, client):
        """Test root endpoint returns healthy status."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ViewMagnet API"
        assert "version" in data
    
    def test_health_endpoint_healthy(self, client):
        """Test health endpoint when everything is working."""
        with patch("src.api.main.get_session") as mock_session:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session.return_value = mock_ctx
            
            # Health resolves model presence via the model registry; patch it
            # like the degraded test does (os.path.exists only covers the
            # registry-unavailable fallback — relying on it made this test
            # depend on local artifacts existing, which fails on CI where
            # models/ and data/models/ are absent).
            with patch("os.path.exists", return_value=True), \
                 patch("src.ml.registry.artifact_exists", return_value=True):
                response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert data["model_loaded"] is True
    
    def test_health_endpoint_degraded_no_model(self, client):
        """Test health endpoint when model is missing."""
        with patch("src.api.main.get_session") as mock_session:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session.return_value = mock_ctx
            
            # Health resolves model presence via the model registry now.
            with patch("os.path.exists", return_value=False), \
                 patch("src.ml.registry.artifact_exists", return_value=False):
                response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["model_loaded"] is False
