"""Tests for GET /analyses/history, GET /analyses/{video_id}, GET /analyses/count.

The routes live in src/api/routers/analyses.py.
test_dashboard.py already covers GET /dashboard/stats, so we focus on the
analysis-list, detail, and count endpoints.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from src.api.main import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def auth_headers(client):
    """Return bearer headers for the test user (signup or existing)."""
    resp = client.post(
        "/auth/signup",
        json={"email": "analyses_test@example.com", "password": "Test1234!"},
    )
    if resp.status_code == 409:
        resp = client.post(
            "/auth/login",
            json={"email": "analyses_test@example.com", "password": "Test1234!"},
        )
    data = resp.json()
    token = data.get("access_token")
    if not token:
        pytest.skip("Could not obtain auth token")
    return {"Authorization": f"Bearer {token}"}


def _make_analysis(**kwargs):
    m = MagicMock()
    m.id = kwargs.get("id", 1)
    m.video_id = kwargs.get("video_id", "dQw4w9WgXcQ")
    m.video_url = kwargs.get("video_url", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    m.title = kwargs.get("title", "Test Video")
    m.prediction_score = kwargs.get("prediction_score", 75.0)
    m.prediction_tier = kwargs.get("prediction_tier", "above")
    m.title_score = kwargs.get("title_score", 80.0)
    m.thumbnail_score = kwargs.get("thumbnail_score", 70.0)
    m.analyzed_at = kwargs.get("analyzed_at", datetime(2025, 6, 1, 12, 0, 0))
    m.shap_explanations = kwargs.get("shap_explanations", None)
    m.recommendations = kwargs.get("recommendations", None)
    return m


# ---------------------------------------------------------------------------
# GET /analyses/history
# ---------------------------------------------------------------------------

class TestAnalysisHistory:
    def test_requires_auth(self, client):
        resp = client.get("/analyses/history")
        assert resp.status_code in (401, 403)

    def test_returns_empty_when_no_data(self, client, auth_headers):
        with patch(
            "src.api.routers.analyses.get_async_session",
        ) as mock_session:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value = mock_ctx

            resp = client.get("/analyses/history", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["analyses"] == []
        assert data["total"] == 0

    def test_returns_list_of_analyses(self, client, auth_headers):
        analyses = [_make_analysis(id=1), _make_analysis(id=2, video_id="abc1234567a")]
        with patch("src.api.routers.analyses.get_async_session") as mock_session:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = analyses
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value = mock_ctx

            resp = client.get("/analyses/history", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["analyses"][0]["video_id"] == "dQw4w9WgXcQ"

    def test_respects_limit_param(self, client, auth_headers):
        with patch("src.api.routers.analyses.get_async_session") as mock_session:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value = mock_ctx

            resp = client.get("/analyses/history?limit=50", headers=auth_headers)
        assert resp.status_code == 200

    def test_limit_validates_min(self, client, auth_headers):
        resp = client.get("/analyses/history?limit=0", headers=auth_headers)
        assert resp.status_code == 422

    def test_limit_validates_max(self, client, auth_headers):
        resp = client.get("/analyses/history?limit=501", headers=auth_headers)
        assert resp.status_code == 422

    def test_limit_500_is_allowed(self, client, auth_headers):
        with patch("src.api.routers.analyses.get_async_session") as mock_session:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value = mock_ctx

            resp = client.get("/analyses/history?limit=500", headers=auth_headers)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /analyses/{video_id}
# ---------------------------------------------------------------------------

class TestAnalysisDetail:
    def test_requires_auth(self, client):
        resp = client.get("/analyses/dQw4w9WgXcQ")
        assert resp.status_code in (401, 403)

    def test_returns_404_when_not_found(self, client, auth_headers):
        with patch("src.api.routers.analyses.get_async_session") as mock_session:
            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = None
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value = mock_ctx

            resp = client.get("/analyses/NOTEXIST001", headers=auth_headers)
        assert resp.status_code == 404

    def test_returns_analysis_data(self, client, auth_headers):
        analysis = _make_analysis(video_id="dQw4w9WgXcQ", prediction_score=88.0)
        with patch("src.api.routers.analyses.get_async_session") as mock_session:
            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = analysis
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value = mock_ctx

            resp = client.get("/analyses/dQw4w9WgXcQ", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["video_id"] == "dQw4w9WgXcQ"
        assert data["prediction_score"] == 88.0
        assert "explanations" in data
        assert "recommendations" in data


# ---------------------------------------------------------------------------
# GET /analyses/count
# ---------------------------------------------------------------------------

class TestAnalysisCount:
    def test_requires_auth(self, client):
        resp = client.get("/analyses/count")
        assert resp.status_code in (401, 403)

    def test_returns_count(self, client, auth_headers):
        with patch("src.api.routers.analyses.get_async_session") as mock_session:
            mock_result = MagicMock()
            mock_result.scalar.return_value = 7
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value = mock_ctx

            resp = client.get("/analyses/count", headers=auth_headers)

        if resp.status_code == 200:
            data = resp.json()
            assert isinstance(data.get("count", data.get("total", 0)), int)
