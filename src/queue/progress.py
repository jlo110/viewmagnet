"""Redis pub/sub for live render-progress events (Week 8).

Every time a render job updates its progress / status / final URL, it
also publishes a small JSON event on ``renders:user:<user_id>``. The
WebSocket endpoint (``/ws/renders``) subscribes per-user and forwards
events to connected browser tabs so the UI never has to poll.

Three design rules keep this safe:

1. **DB stays the source of truth.** Events are derived from the same
   write that updates ``EditSession`` / ``StudioProject``; a missed
   event never corrupts state, the WebSocket reader can always
   re-fetch the row to reconcile.
2. **Fail-open.** A Redis publish failure logs at warn and returns;
   the render job MUST NOT fail because pub/sub is down. The frontend
   will fall back to polling.
3. **Sync fallback no-ops.** When ``REDIS_URL`` is unset (tests, dev
   without Redis) the publisher silently returns. No tests should
   need to mock Redis to exercise the render path.
"""
from __future__ import annotations

import json
from typing import Literal, Optional

import structlog

from src.config import get_settings

logger = structlog.get_logger(__name__)

# A single Redis connection reused per process. ``None`` until first use;
# resolved lazily so test processes that never publish don't open a
# socket.
_redis_conn = None
_redis_resolved = False


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


def _get_connection():
    """Return the shared Redis connection (or ``None`` when unavailable).

    Resolved exactly once per process. ``None`` is the sentinel that
    means "no Redis configured / install failed" — every public helper
    checks for it and short-circuits to a no-op.
    """
    global _redis_conn, _redis_resolved
    if _redis_resolved:
        return _redis_conn

    _redis_resolved = True
    settings = get_settings()
    if not settings.redis_url:
        return None

    try:
        from redis import Redis

        _redis_conn = Redis.from_url(settings.redis_url)
    except ImportError:
        logger.warning("queue.progress.redis_not_installed")
        _redis_conn = None
    except Exception as exc:  # noqa: BLE001 — Redis can raise many things
        logger.warning("queue.progress.connect_failed", error=str(exc))
        _redis_conn = None
    return _redis_conn


# ---------------------------------------------------------------------------
# Channel naming
# ---------------------------------------------------------------------------


def channel_for_user(user_id: int) -> str:
    """One channel per user — the WebSocket endpoint subscribes
    exactly this name. Keeping it tenant-scoped means a noisy
    user doesn't fan out events to anyone else's connections."""
    return f"renders:user:{user_id}"


# ---------------------------------------------------------------------------
# Event publisher
# ---------------------------------------------------------------------------

RenderKind = Literal["session", "project"]
RenderStatus = Literal["queued", "rendering", "done", "failed", "idle"]


def is_available() -> bool:
    """True iff Redis is reachable and pub/sub is usable.

    Drives the WebSocket endpoint's fallback path — when this
    returns False the endpoint immediately closes the connection
    with a known code so the frontend falls back to polling.
    """
    return _get_connection() is not None


def subscribe_to_user(user_id: int):
    """Open a Redis pub/sub iterator for ``user_id``'s channel.

    Returns a ``redis.client.PubSub`` instance subscribed to the
    user's channel, or ``None`` when Redis is unavailable. Callers
    are responsible for closing the pubsub when done (``pubsub.close()``).

    Used by the WebSocket endpoint. Each connected client gets its
    own pubsub so a slow consumer doesn't block other tabs (this
    is the standard redis-py pattern; the connection pool handles
    socket sharing transparently).
    """
    conn = _get_connection()
    if conn is None:
        return None
    try:
        pubsub = conn.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel_for_user(user_id))
        return pubsub
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "queue.progress.subscribe_failed",
            user_id=user_id,
            error=str(exc),
        )
        return None


def publish_progress(
    *,
    user_id: int,
    kind: RenderKind,
    render_id: int,
    status: RenderStatus,
    percent: Optional[int] = None,
    message: Optional[str] = None,
    download_url: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Publish a progress event to the user's render channel.

    Called RIGHT AFTER the underlying DB write — never as a substitute
    for one. The event shape is intentionally flat (no nesting) so
    the WebSocket handler can stream it straight through without
    deserializing.

    Args:
        user_id: Owner of the render. The publish channel is
            tenant-scoped to this user; never publish another user's
            progress.
        kind: ``"session"`` for single-clip renders, ``"project"`` for
            multi-clip Project renders. Lets the frontend route the
            event to the right card without an extra round trip.
        render_id: Database id of the ``EditSession`` (kind=session)
            or ``StudioProject`` (kind=project). Same id the row's
            ``last_render_*`` columns key off of.
        status: Current render lifecycle state.
        percent: 0-100 if known, else None. Matches the DB column.
        message: Short human-readable status (e.g. "Encoding 42%").
        download_url: Final R2 URL on ``status="done"``.
        error: Truncated error string on ``status="failed"``.
    """
    conn = _get_connection()
    if conn is None:
        return  # Fail-open: no Redis, no live progress; UI polling covers it.

    event = {
        "kind": kind,
        "render_id": render_id,
        "status": status,
        "percent": percent,
        "message": message,
        "download_url": download_url,
        "error": error,
    }
    payload = json.dumps(event, separators=(",", ":"))
    try:
        conn.publish(channel_for_user(user_id), payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "queue.progress.publish_failed",
            user_id=user_id,
            kind=kind,
            render_id=render_id,
            error=str(exc),
        )
