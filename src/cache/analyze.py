"""Synchronous LRU + Redis cache for expensive analyze inputs.

Used to avoid recomputing thumbnail features and title embeddings on repeat
``POST /analyze`` calls (very common when users re-analyze before publishing).

Both helpers fall back to an in-process LRU when Redis is unavailable.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sync_redis_get(key: str) -> Optional[str]:
    """Best-effort sync Redis read (uses the asyncio client behind a thread loop)."""
    try:
        import asyncio
        from src.cache.redis import cache_get
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return None  # Avoid blocking the running loop -- skip cache.
        except RuntimeError:
            pass
        return asyncio.run(cache_get(key))
    except Exception as e:
        logger.debug("cache.sync_get_failed", key=key, error=str(e))
        return None


def _sync_redis_set(key: str, value: str, ttl_seconds: int) -> None:
    try:
        import asyncio
        from src.cache.redis import cache_set
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return
        except RuntimeError:
            pass
        asyncio.run(cache_set(key, value, ttl_seconds=ttl_seconds))
    except Exception as e:
        logger.debug("cache.sync_set_failed", key=key, error=str(e))


# In-process fallback caches (small, bounded).
@lru_cache(maxsize=512)
def _local_thumb_cache(key: str) -> Optional[str]:  # pragma: no cover - placeholder
    return None


_thumb_inproc: dict[str, str] = {}
_title_inproc: dict[str, str] = {}


def get_thumbnail_features_cached(thumbnail_url: str) -> Optional[dict]:
    """Return cached thumbnail features for the given URL, or ``None``."""
    if not thumbnail_url:
        return None
    key = f"thumb:features:{_sha256(thumbnail_url)}"
    raw = _sync_redis_get(key) or _thumb_inproc.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_thumbnail_features_cached(thumbnail_url: str, features: dict, ttl_seconds: int = 86400) -> None:
    if not thumbnail_url:
        return
    key = f"thumb:features:{_sha256(thumbnail_url)}"
    payload = json.dumps(features, default=float)
    _thumb_inproc[key] = payload
    if len(_thumb_inproc) > 512:
        # Drop the oldest half (rough LRU).
        for k in list(_thumb_inproc.keys())[:256]:
            del _thumb_inproc[k]
    _sync_redis_set(key, payload, ttl_seconds)


def get_title_embedding_cached(title: str) -> Optional[list[float]]:
    if not title:
        return None
    key = f"title:emb:{_sha256(title)}"
    raw = _sync_redis_get(key) or _title_inproc.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_title_embedding_cached(title: str, embedding: list[float], ttl_seconds: int = 604800) -> None:
    if not title:
        return
    key = f"title:emb:{_sha256(title)}"
    payload = json.dumps([float(x) for x in embedding])
    _title_inproc[key] = payload
    if len(_title_inproc) > 512:
        for k in list(_title_inproc.keys())[:256]:
            del _title_inproc[k]
    _sync_redis_set(key, payload, ttl_seconds)


# Packaging-rubric cache (the pre-launch coaching score is an LLM call; titles
# repeat constantly as users re-analyze, so cache by sha256(title)).
_rubric_inproc: dict[str, str] = {}


def get_packaging_rubric_cached(title: str) -> Optional[dict]:
    if not title:
        return None
    key = f"rubric:title:{_sha256(title)}"
    raw = _sync_redis_get(key) or _rubric_inproc.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_packaging_rubric_cached(title: str, result: dict, ttl_seconds: int = 604800) -> None:
    if not title or not result:
        return
    key = f"rubric:title:{_sha256(title)}"
    try:
        payload = json.dumps(result)
    except (TypeError, ValueError):
        return
    _rubric_inproc[key] = payload
    if len(_rubric_inproc) > 512:
        for k in list(_rubric_inproc.keys())[:256]:
            del _rubric_inproc[k]
    _sync_redis_set(key, payload, ttl_seconds)
