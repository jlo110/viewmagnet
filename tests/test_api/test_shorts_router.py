"""Tests for the /shorts/* API endpoints.

Covers the fixes made to the shorts router:
  - score field must accept 0-100 (was incorrectly capped to 0-1)
  - /shorts/detect-highlights returns clear 400/422 errors, not opaque 500s
  - transcript length guard rejects paste that is too short
  - TranscriptUnavailable maps to 422, not 500
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(db_session):
    """TestClient with auth bypassed via DEV_MODE mock token."""
    import os
    os.environ.setdefault("ENVIRONMENT", "development")
    from src.api.main import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def auth_headers(client):
    """Return Authorization headers for the dev-mode mock user."""
    from src.api.limiter import _settings as ls
    # DEV_MODE exposes a bypass token; fall back to a signup if needed.
    import os
    token = os.environ.get("DEV_MODE_TOKEN")
    if not token:
        resp = client.post(
            "/auth/signup",
            json={"email": "shorts_test@example.com", "password": "Test1234!"},
        )
        data = resp.json()
        token = data.get("access_token") or data.get("detail", "")
        if not token or resp.status_code not in (200, 201, 409):
            pytest.skip("Could not obtain auth token")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Score validation — the field must accept values > 1.0
# ---------------------------------------------------------------------------

class TestShortHighlightScoreRange:
    def test_score_field_accepts_100_scale(self):
        """ShortHighlight.score must accept values in 0-100, not just 0-1."""
        from src.api.routers.shorts import ShortHighlight
        h = ShortHighlight(
            start_time=0.0,
            end_time=30.0,
            duration=30.0,
            text="Buzzer beater to win the championship",
            score=85.0,
            reason="High energy moment",
            hook_type="sports",
            suggested_title="Buzzer Beater Championship",
        )
        assert h.score == 85.0

    def test_score_clamps_to_100_max(self):
        """Scores above 100 are not accepted (Pydantic le=100 constraint)."""
        from src.api.routers.shorts import ShortHighlight
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ShortHighlight(
                start_time=0.0,
                end_time=10.0,
                duration=10.0,
                text="x",
                score=101.0,
                reason="Over cap",
                hook_type=None,
                suggested_title="Title",
            )

    def test_score_does_not_accept_negative(self):
        from src.api.routers.shorts import ShortHighlight
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ShortHighlight(
                start_time=0.0,
                end_time=10.0,
                duration=10.0,
                text="x",
                score=-1.0,
                reason="Negative",
                hook_type=None,
                suggested_title="Title",
            )


# ---------------------------------------------------------------------------
# TranscriptUnavailable → 422 with actionable message
# ---------------------------------------------------------------------------

class TestShortsDetectErrors:
    def _post(self, client, headers, body):
        return client.post("/shorts/detect-highlights", json=body, headers=headers)

    def test_missing_both_fields_returns_400(self, client, auth_headers):
        resp = self._post(client, auth_headers, {"max_highlights": 3})
        assert resp.status_code == 400
        detail = resp.json().get("error", {}).get("message", resp.text)
        assert "url" in detail.lower() or "transcript" in detail.lower()

    def test_short_transcript_returns_400(self, client, auth_headers):
        resp = self._post(client, auth_headers, {"transcript": "too short"})
        assert resp.status_code == 400
        detail = resp.json().get("error", {}).get("message", resp.text)
        assert "30" in detail or "short" in detail.lower()

    def test_invalid_youtube_url_returns_400(self, client, auth_headers):
        resp = self._post(client, auth_headers, {"video_url": "not-a-url"})
        assert resp.status_code == 400
        detail = resp.json().get("error", {}).get("message", resp.text)
        assert "youtube" in detail.lower() or "valid" in detail.lower()

    def test_transcript_unavailable_returns_422(self, client, auth_headers):
        """When YouTube captions can't be fetched, the router must return
        422 (not 500) with a clear paste-the-transcript instruction."""
        from src.features.shorts.models import TranscriptUnavailable

        with patch(
            "src.features.shorts_creator.ShortsCreator.analyze_youtube_video",
            side_effect=TranscriptUnavailable("paste the transcript"),
        ):
            resp = self._post(
                client, auth_headers,
                {"video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
        assert resp.status_code == 422
        detail = resp.json().get("error", {}).get("message", resp.text)
        assert "transcript" in detail.lower()

    def test_good_transcript_returns_200(self, client, auth_headers):
        """A well-formed transcript must reach the scoring pipeline and
        return 200 — regression guard against future import regressions."""
        transcript = (
            "So today we are going to talk about the championship game. "
            "It came down to the final seconds and nobody expected what happened next. "
            "The crowd went absolutely wild when he hit that buzzer beater. "
            "Then things got heated on the sideline after the final whistle."
        )
        mock_analysis = MagicMock()
        mock_analysis.highlights = []
        mock_analysis.video_title = "Test"
        mock_analysis.video_duration = 60.0
        mock_analysis.transcript_full = transcript

        with patch(
            "src.features.shorts_creator.ShortsCreator.analyze_from_text",
            return_value=mock_analysis,
        ):
            resp = self._post(
                client, auth_headers,
                {"transcript": transcript, "max_highlights": 3},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "highlights" in data
        assert isinstance(data["highlights"], list)


# ---------------------------------------------------------------------------
# TranscriptUnavailable exception itself
# ---------------------------------------------------------------------------

class TestTranscriptUnavailable:
    def test_is_exception(self):
        from src.features.shorts.models import TranscriptUnavailable
        exc = TranscriptUnavailable("paste the transcript instead")
        assert isinstance(exc, Exception)
        assert "paste" in str(exc)

    def test_not_caught_by_value_error(self):
        """TranscriptUnavailable must NOT be a ValueError subclass so the
        router's separate except-blocks handle it correctly."""
        from src.features.shorts.models import TranscriptUnavailable
        with pytest.raises(TranscriptUnavailable):
            try:
                raise TranscriptUnavailable("test")
            except ValueError:
                pytest.fail("TranscriptUnavailable was caught as ValueError")
