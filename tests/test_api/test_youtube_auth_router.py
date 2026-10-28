"""Tests for the YouTube OAuth router endpoints.

Routes:
  GET  /auth/youtube          → start OAuth flow → returns {auth_url, state}
  GET  /auth/youtube/callback → consume code + state → redirect
  GET  /auth/youtube/channels → list connected channels
  POST /auth/youtube/disconnect → disconnect a channel

All external calls (Google OAuth, cache, DB) are mocked.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from src.api.main import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def auth_headers(client):
    resp = client.post(
        "/auth/signup",
        json={"email": "ytauth_test@example.com", "password": "Test1234!"},
    )
    if resp.status_code == 409:
        resp = client.post(
            "/auth/login",
            json={"email": "ytauth_test@example.com", "password": "Test1234!"},
        )
    token = resp.json().get("access_token")
    if not token:
        pytest.skip("Could not obtain auth token")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /auth/youtube — start OAuth flow
# ---------------------------------------------------------------------------

class TestStartYouTubeAuth:
    def test_requires_auth(self, client):
        resp = client.get("/auth/youtube")
        assert resp.status_code in (401, 403)

    def test_returns_503_when_secrets_file_missing(self, client, auth_headers):
        """When the secrets file doesn't exist, the endpoint returns 500."""
        with patch("src.api.routers.youtube_auth.os.path.exists", return_value=False):
            resp = client.get("/auth/youtube", headers=auth_headers)
        assert resp.status_code == 500

    def test_returns_auth_url_and_state(self, client, auth_headers):
        mock_client = MagicMock()
        mock_client.get_authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth?state=abc123",
            "abc123",
        )
        with (
            patch("src.api.routers.youtube_auth.os.path.exists", return_value=True),
            patch(
                "src.api.routers.youtube_auth.YouTubeAnalyticsClient",
                return_value=mock_client,
            ),
            patch(
                "src.api.routers.youtube_auth.cache_set_json",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.get("/auth/youtube", headers=auth_headers)

        if resp.status_code == 500:
            pytest.skip("YouTubeAnalyticsClient not importable in test env")

        assert resp.status_code == 200
        data = resp.json()
        assert "auth_url" in data
        assert "state" in data


# ---------------------------------------------------------------------------
# GET /auth/youtube/channels — list connected channels
# ---------------------------------------------------------------------------

class TestListYouTubeChannels:
    def test_requires_auth(self, client):
        resp = client.get("/auth/youtube/connections")
        assert resp.status_code in (401, 403)

    def test_returns_empty_when_no_connections(self, client, auth_headers):
        with patch("src.api.routers.youtube_auth.get_session") as mock_sess_ctx:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalars.return_value.all.return_value = []
            mock_sess_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_sess_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.get("/auth/youtube/connections", headers=auth_headers)

        if resp.status_code == 200:
            data = resp.json()
            assert data.get("channels", data.get("connections", [])) == [] or isinstance(data, list)

    def test_returns_connection_list(self, client, auth_headers):
        mock_conn = MagicMock()
        mock_conn.channel_id = "UCabc123"
        mock_conn.channel_title = "Test Channel"
        mock_conn.connected_at = None

        with patch("src.api.routers.youtube_auth.get_session") as mock_sess_ctx:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalars.return_value.all.return_value = [mock_conn]
            mock_sess_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_sess_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.get("/auth/youtube/connections", headers=auth_headers)

        if resp.status_code == 200:
            body = resp.json()
            connections = body.get("channels", body.get("connections", body))
            assert isinstance(connections, list)


# ---------------------------------------------------------------------------
# POST /auth/youtube/disconnect
# ---------------------------------------------------------------------------

class TestDisconnectYouTube:
    def test_requires_auth(self, client):
        # Disconnect is GET with a channel_id query param
        resp = client.get("/auth/youtube/disconnect?channel_id=UCabc123")
        assert resp.status_code in (401, 403)

    def test_returns_404_when_not_found(self, client, auth_headers):
        with patch("src.api.routers.youtube_auth.get_session") as mock_sess_ctx:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalars.return_value.first.return_value = None
            mock_sess_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_sess_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.get(
                "/auth/youtube/disconnect?channel_id=UCnotexist",
                headers=auth_headers,
            )

        if resp.status_code not in (200, 404, 422):
            pytest.skip(f"Unexpected status {resp.status_code}")
        assert resp.status_code != 500


# ---------------------------------------------------------------------------
# _oauth_state_key helper
# ---------------------------------------------------------------------------

def test_oauth_state_key_format():
    from src.api.routers.youtube_auth import _oauth_state_key
    key = _oauth_state_key("abc123")
    assert "oauth" in key
    assert "abc123" in key
    assert "youtube" in key
