"""WebSocket endpoint for live render-progress events (Week 8).

Browsers open ``ws(s)://…/ws/renders?token=<jwt>``; the endpoint
authenticates the token, subscribes to that user's Redis pub/sub
channel, and forwards every event as a JSON text frame until the
client disconnects.

Design choices:

* **Auth via query string** — WebSocket handshakes can't carry
  ``Authorization`` headers, so we accept the same JWT access token
  the rest of the API uses via ``?token=…`` and validate it with
  :func:`get_current_user_ws`.
* **Per-connection pubsub** — every connected tab gets its own
  ``PubSub`` so a slow consumer can't head-of-line block other tabs.
  Connection pooling on the Redis side handles the underlying
  socket reuse.
* **Fail-closed handshake when Redis is unavailable** — the
  endpoint closes with a known code (4408) so the frontend can
  fall back to polling immediately instead of hanging. The
  progress writer is fail-open in the same scenario, so the DB
  is still the source of truth in both directions.
* **No raw event mutation** — events are forwarded verbatim. If
  the publisher schema changes, every consumer benefits.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.auth.dependencies import get_current_user_ws
from src.queue.progress import is_available as redis_is_available
from src.queue.progress import subscribe_to_user

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["renders-ws"])

# Close codes (per RFC 6455 + custom 4xxx app-specific codes).
_CLOSE_UNAUTHORIZED = 4401
_CLOSE_NO_REALTIME = 4408  # Redis unavailable; client should poll instead.
_CLOSE_TOO_MANY = 4429     # Per-user connection cap hit (DoS guard).
_CLOSE_SERVER_ERROR = 4500

# Per-user concurrent-connection cap. Each connection holds a Redis pubsub + a
# polling loop, so unbounded connections per token are a resource-exhaustion
# surface. Counter is per-process (one scheduler/api worker); good enough as a
# guard since a single abusive token is the threat model.
_MAX_CONNECTIONS_PER_USER = 5
_active_connections: dict[int, int] = {}


@router.websocket("/ws/renders")
async def renders_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
) -> None:
    """Stream render-progress events to the authenticated user.

    Auth: pass the same JWT used for HTTP endpoints via ``?token=``.
    Unauthenticated handshakes close with 4401.

    Event shape (forwarded verbatim from
    :func:`src.queue.progress.publish_progress`)::

        {
            "kind": "session" | "project",
            "render_id": int,
            "status": "queued" | "rendering" | "done" | "failed" | "idle",
            "percent": int | null,
            "message": str | null,
            "download_url": str | null,
            "error": str | null
        }
    """
    user = await get_current_user_ws(token)
    if user is None:
        await websocket.close(code=_CLOSE_UNAUTHORIZED)
        return

    if not redis_is_available():
        # Accept first so the close frame has a real WS context;
        # closing pre-accept yields a plain HTTP 403 which most
        # browser WebSocket clients surface as an opaque error.
        await websocket.accept()
        await websocket.close(code=_CLOSE_NO_REALTIME)
        logger.info(
            "renders_ws.no_realtime",
            user_id=user.id,
            reason="redis_unavailable",
        )
        return

    # Connection cap (DoS guard) — reject before subscribing so a rejected
    # connection never allocates a pubsub.
    if _active_connections.get(user.id, 0) >= _MAX_CONNECTIONS_PER_USER:
        await websocket.accept()
        await websocket.close(code=_CLOSE_TOO_MANY)
        logger.warning("renders_ws.too_many", user_id=user.id,
                       cap=_MAX_CONNECTIONS_PER_USER)
        return

    pubsub = subscribe_to_user(user.id)
    if pubsub is None:
        await websocket.accept()
        await websocket.close(code=_CLOSE_SERVER_ERROR)
        return

    _active_connections[user.id] = _active_connections.get(user.id, 0) + 1
    await websocket.accept()
    logger.info("renders_ws.connected", user_id=user.id,
                active=_active_connections[user.id])

    # The pubsub iteration is blocking (it's redis-py, not aioredis),
    # so we poll in a tight asyncio.to_thread loop with a short
    # timeout — yields the event loop frequently so we can also
    # service the client's disconnect / heartbeat without spawning
    # a separate thread per connection.
    try:
        while True:
            # `get_message` with a small timeout returns None when
            # no event arrived; that's fine, we loop and check
            # whether the client is still connected.
            msg = await asyncio.to_thread(
                pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0
            )
            if msg is not None:
                # Forward the raw JSON. The publisher already
                # serialized with separators=(',', ':') for compact
                # payloads.
                data = msg.get("data")
                if isinstance(data, (bytes, bytearray)):
                    payload = data.decode("utf-8", errors="replace")
                else:
                    payload = str(data)
                try:
                    await websocket.send_text(payload)
                except WebSocketDisconnect:
                    break
            # Detect a client-initiated close even when no events
            # are flowing. ``client_state`` flips to ``DISCONNECTED``
            # without raising; we have to poll it here.
            from starlette.websockets import WebSocketState

            if websocket.client_state != WebSocketState.CONNECTED:
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "renders_ws.unhandled",
            user_id=user.id,
            error=str(exc),
        )
    finally:
        try:
            pubsub.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            from starlette.websockets import WebSocketState

            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception:  # noqa: BLE001
            pass
        # Release the connection slot.
        remaining = _active_connections.get(user.id, 1) - 1
        if remaining > 0:
            _active_connections[user.id] = remaining
        else:
            _active_connections.pop(user.id, None)
        logger.info("renders_ws.disconnected", user_id=user.id)
