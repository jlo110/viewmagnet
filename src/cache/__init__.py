"""Cache backends (Redis with in-memory fallback)."""
from src.cache.redis import (
    get_redis,
    cache_get,
    cache_set,
    cache_delete,
    cache_get_json,
    cache_set_json,
)

__all__ = [
    "get_redis",
    "cache_get",
    "cache_set",
    "cache_delete",
    "cache_get_json",
    "cache_set_json",
]
