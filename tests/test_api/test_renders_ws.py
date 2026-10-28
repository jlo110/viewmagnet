"""Render-progress WebSocket: auth + per-user connection cap (Phase 4.4).

Builds a minimal app with just the WS router so we exercise the endpoint's
security properties without the full app/middleware. Redis + auth are mocked.
"""
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import src.api.routers.renders_ws as ws_mod


def _client():
    app = FastAPI()
    app.include_router(ws_mod.router)
    return TestClient(app)


def _fake_pubsub():
    ps = MagicMock()
    ps.get_message.return_value = None  # no events; loop just polls
    return ps


@pytest.fixture(autouse=True)
def _reset_counter():
    ws_mod._active_connections.clear()
    yield
    ws_mod._active_connections.clear()


def test_unauthenticated_closes_4401():
    client = _client()
    with patch.object(ws_mod, "get_current_user_ws", new=AsyncMock(return_value=None)):
        with pytest.raises(WebSocketDisconnect) as ei:
            with client.websocket_connect("/ws/renders?token=bad") as w:
                w.receive_text()
    assert ei.value.code == ws_mod._CLOSE_UNAUTHORIZED  # 4401


def test_valid_token_connects():
    client = _client()
    user = SimpleNamespace(id=7)
    with patch.object(ws_mod, "get_current_user_ws", new=AsyncMock(return_value=user)), \
         patch.object(ws_mod, "redis_is_available", return_value=True), \
         patch.object(ws_mod, "subscribe_to_user", return_value=_fake_pubsub()):
        with client.websocket_connect("/ws/renders?token=ok"):
            # Accepted → counter incremented for this user.
            assert ws_mod._active_connections.get(7) == 1


def test_connection_cap_rejects_excess_with_4429():
    client = _client()
    user = SimpleNamespace(id=42)
    with patch.object(ws_mod, "get_current_user_ws", new=AsyncMock(return_value=user)), \
         patch.object(ws_mod, "redis_is_available", return_value=True), \
         patch.object(ws_mod, "subscribe_to_user", side_effect=lambda _uid: _fake_pubsub()):
        with ExitStack() as stack:
            for _ in range(ws_mod._MAX_CONNECTIONS_PER_USER):
                stack.enter_context(client.websocket_connect("/ws/renders?token=ok"))
            assert ws_mod._active_connections[42] == ws_mod._MAX_CONNECTIONS_PER_USER
            # One past the cap must be rejected (accept → close 4429).
            with pytest.raises(WebSocketDisconnect) as ei:
                with client.websocket_connect("/ws/renders?token=ok") as w6:
                    w6.receive_text()
            assert ei.value.code == ws_mod._CLOSE_TOO_MANY  # 4429
