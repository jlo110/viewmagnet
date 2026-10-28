"""Thin async Redis wrapper with a graceful in-memory fallback.

When ``REDIS_URL`` is set the real ``redis.asyncio`` client is used; otherwise
an in-process dict is used so unit tests and ``DEV_MODE`` runs work without a
running Redis.

Use ``cache_get_json`` / ``cache_set_json`` for OAuth state, analyze cache,
LLM budget counters, etc.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

import structlog

from src.config import get_settings

logger = structlog.get_logger(__name__)


class _MemoryRedis:
    """In-process fallback used when ``REDIS_URL`` is not configured.

    Implements just the subset of the Redis API the app uses (``get``, ``set``,
    ``setex``, ``delete``, ``incr``, ``expire``). Not thread-safe across
    processes -- intended for tests and single-worker dev runs only.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[bytes, Optional[float]]] = {}
        self._lock = asyncio.Lock()

    def _expired(self, key: str) -> bool:
        item = self._store.get(key)
        if item is None:
            return True
        _, expires_at = item
        if expires_at is not None and time.time() > expires_at:
            del self._store[key]
            return True
        return False

    async def get(self, key: str) -> Optional[bytes]:
        async with self._lock:
            if self._expired(key):
                return None
            return self._store[key][0]

    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        async with self._lock:
            data = value.encode() if isinstance(value, str) else bytes(value)
            expires_at = time.time() + ex if ex else None
            self._store[key] = (data, expires_at)

    async def setex(self, key: str, ex: int, value: Any) -> None:
        await self.set(key, value, ex=ex)

    async def delete(self, *keys: str) -> int:
        async with self._lock:
            removed = 0
            for key in keys:
                if key in self._store:
                    del self._store[key]
                    removed += 1
            return removed

    async def incr(self, key: str) -> int:
        async with self._lock:
            current = 0
            if not self._expired(key):
                try:
                    current = int(self._store[key][0])
                except (ValueError, KeyError):
                    current = 0
            current += 1
            self._store[key] = (str(current).encode(), self._store.get(key, (None, None))[1])
            return current

    async def incrbyfloat(self, key: str, amount: float) -> float:
        async with self._lock:
            current = 0.0
            if not self._expired(key):
                try:
                    current = float(self._store[key][0])
                except (ValueError, KeyError):
                    current = 0.0
            current += amount
            self._store[key] = (str(current).encode(), self._store.get(key, (None, None))[1])
            return current

    async def expire(self, key: str, seconds: int) -> bool:
        async with self._lock:
            if key not in self._store or self._expired(key):
                return False
            data, _ = self._store[key]
            self._store[key] = (data, time.time() + seconds)
            return True

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._store.clear()


_using_memory = False
# redis.asyncio clients are bound to the event loop that created them — awaiting
# their futures from a different loop raises "got Future attached to a different
# loop". We get multiple loops in practice (FastAPI startup loop vs per-request
# loops under uvicorn --reload, threads spawned by ML model code, etc.), so we
# keep one client per loop instead of a single module-level singleton.
_clients_by_loop: "dict[int, Any]" = {}
_loop_agnostic_client: Optional[Any] = None  # for the in-memory fallback


def _make_client() -> Any:
    """Create a fresh Redis (or in-memory) client based on settings."""
    global _using_memory
    settings = get_settings()
    if settings.redis_url:
        try:
            import redis.asyncio as redis_asyncio
            client = redis_asyncio.from_url(settings.redis_url, decode_responses=False)
            logger.info("redis.connected", url=settings.redis_url.split("@")[-1])
            return client
        except ImportError:
            logger.warning("redis.import_failed", message="redis package not installed, using in-memory fallback")
            _using_memory = True
            return _MemoryRedis()
    logger.info("redis.using_memory_fallback")
    _using_memory = True
    return _MemoryRedis()


def get_redis() -> Any:
    """Return a Redis client bound to the current event loop (or in-memory fallback)."""
    global _loop_agnostic_client

    # In-memory fallback uses asyncio.Lock() which IS loop-bound, but we keep a
    # single instance per process for state continuity. Locks recreate as needed.
    if _loop_agnostic_client is not None and _using_memory:
        return _loop_agnostic_client

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (e.g. sync startup code) — create and cache loop-less.
        if _loop_agnostic_client is None:
            _loop_agnostic_client = _make_client()
        return _loop_agnostic_client

    client = _clients_by_loop.get(id(loop))
    if client is not None:
        return client

    client = _make_client()
    if _using_memory:
        _loop_agnostic_client = client
        return client
    _clients_by_loop[id(loop)] = client
    return client


def is_memory_backend() -> bool:
    """True when the in-process fallback is in use."""
    return _using_memory or (not _clients_by_loop and _loop_agnostic_client is None)


async def cache_get(key: str) -> Optional[str]:
    """Get a string value by key, or ``None`` if missing/expired."""
    client = get_redis()
    try:
        value = await client.get(key)
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else value
    except Exception as e:
        logger.error("cache.get_failed", key=key, error=str(e))
        return None


async def cache_set(key: str, value: str, ttl_seconds: Optional[int] = None) -> None:
    """Set a string value with optional TTL."""
    client = get_redis()
    try:
        if ttl_seconds:
            await client.setex(key, ttl_seconds, value)
        else:
            await client.set(key, value)
    except Exception as e:
        logger.error("cache.set_failed", key=key, error=str(e))


async def cache_delete(*keys: str) -> int:
    """Delete one or more keys; returns number actually removed."""
    if not keys:
        return 0
    client = get_redis()
    try:
        return await client.delete(*keys)
    except Exception as e:
        logger.error("cache.delete_failed", keys=keys, error=str(e))
        return 0


async def cache_get_json(key: str) -> Optional[Any]:
    """JSON-decode a cached value, or ``None`` if missing."""
    raw = await cache_get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("cache.json_decode_failed", key=key)
        return None


async def cache_set_json(key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    """JSON-encode and store a value."""
    try:
        await cache_set(key, json.dumps(value, default=str), ttl_seconds=ttl_seconds)
    except (TypeError, ValueError) as e:
        logger.error("cache.json_encode_failed", key=key, error=str(e))


async def ping() -> bool:
    """Health check."""
    client = get_redis()
    try:
        return bool(await client.ping())
    except Exception:
        return False
