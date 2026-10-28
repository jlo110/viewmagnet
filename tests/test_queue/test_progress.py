"""Tests for :mod:`src.queue.progress`.

The publisher is fail-open by design — render jobs MUST keep working
when Redis is missing or flaky. These tests pin that behavior and
verify the event shape that the WebSocket endpoint will fan out.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.queue import progress


@pytest.fixture(autouse=True)
def _reset_connection_cache():
    """Each test gets a clean cached connection state so we can swap
    in different mocks without bleeding between cases."""
    progress._redis_conn = None
    progress._redis_resolved = False
    yield
    progress._redis_conn = None
    progress._redis_resolved = False


def test_channel_for_user_is_tenant_scoped():
    """Channel name embeds the user id so subscribers can't cross
    tenants by accident."""
    assert progress.channel_for_user(42) == "renders:user:42"
    assert progress.channel_for_user(1) != progress.channel_for_user(2)


def test_publish_progress_no_op_when_no_redis():
    """When ``REDIS_URL`` isn't configured, publish must be a silent
    no-op — never raise, never block."""
    with patch.object(progress, "_get_connection", return_value=None):
        progress.publish_progress(
            user_id=1,
            kind="session",
            render_id=99,
            status="rendering",
            percent=42,
            message="Encoding",
        )
    # Reaches here without raising — that's the test.


def test_publish_progress_publishes_expected_shape():
    """Happy path: when Redis is available the publisher emits a
    flat JSON event on the user's channel with all the fields the
    frontend hook expects to render."""
    mock_conn = MagicMock()
    with patch.object(progress, "_get_connection", return_value=mock_conn):
        progress.publish_progress(
            user_id=7,
            kind="project",
            render_id=123,
            status="rendering",
            percent=55,
            message="Concatenating clips",
        )

    mock_conn.publish.assert_called_once()
    channel, raw_payload = mock_conn.publish.call_args[0]
    assert channel == "renders:user:7"
    payload = json.loads(raw_payload)
    assert payload == {
        "kind": "project",
        "render_id": 123,
        "status": "rendering",
        "percent": 55,
        "message": "Concatenating clips",
        "download_url": None,
        "error": None,
    }


def test_publish_progress_includes_download_url_on_done():
    """``status='done'`` events carry the final URL so the UI can
    update the result card without re-fetching the row."""
    mock_conn = MagicMock()
    with patch.object(progress, "_get_connection", return_value=mock_conn):
        progress.publish_progress(
            user_id=3,
            kind="session",
            render_id=42,
            status="done",
            percent=100,
            message="Done",
            download_url="https://r2.example.com/done.mp4",
        )

    payload = json.loads(mock_conn.publish.call_args[0][1])
    assert payload["status"] == "done"
    assert payload["download_url"] == "https://r2.example.com/done.mp4"


def test_publish_progress_swallows_redis_errors():
    """Redis blip during publish must not bubble to the render job."""
    mock_conn = MagicMock()
    mock_conn.publish.side_effect = ConnectionError("broker gone")
    with patch.object(progress, "_get_connection", return_value=mock_conn):
        # Should NOT raise.
        progress.publish_progress(
            user_id=1,
            kind="session",
            render_id=1,
            status="rendering",
            percent=10,
            message="Working",
        )
