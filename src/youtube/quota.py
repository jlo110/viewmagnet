"""YouTube API quota management with multi-key rotation."""
import threading
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import structlog

from src.config import get_settings

logger = structlog.get_logger()

# YouTube Data API quota resets at MIDNIGHT PACIFIC, not UTC. Accounting by a
# UTC/server-local day makes a key look "fresh" for the ~7-8h between local
# midnight and the real Pacific reset, so we hammer 403s on keys that are still
# exhausted (observed in prod: a key maxed "yesterday" 403s all morning while
# our counter reads 0). Keying every quota read/write by the Pacific day aligns
# our accounting with when YouTube actually resets.
_QUOTA_TZ = ZoneInfo("America/Los_Angeles")


def _quota_day() -> date:
    """Current date in YouTube's quota-reset timezone (US/Pacific)."""
    return datetime.now(_QUOTA_TZ).date()


# ---------------------------------------------------------------------------
# Durable-usage accumulator (observability)
# ---------------------------------------------------------------------------
# Each QuotaManager only counts usage in its own (per-process, per-instance)
# memory, which is wiped on restart and invisible from outside. To make
# "are we running out of quota?" answerable, every ``record_usage`` also feeds
# this process-global buffer; a periodic job drains it into the
# ``youtube_quota_usage`` table (see src.youtube.quota_store). The buffer is
# keyed by ``(usage_date_iso, key_index, operation)`` so a flush can upsert
# exact deltas. A lock keeps it safe across APScheduler's job threads.
_USAGE_LOCK = threading.Lock()
_PENDING_USAGE: Dict[Tuple[str, int, str], int] = defaultdict(int)


def _accumulate_usage(key_index: int, operation: str, cost: int) -> None:
    """Add one operation's cost to the global pending-flush buffer."""
    with _USAGE_LOCK:
        _PENDING_USAGE[(_quota_day().isoformat(), key_index, operation)] += cost


def drain_pending_usage() -> Dict[Tuple[str, int, str], int]:
    """Atomically remove and return the accumulated deltas for flushing.

    Drain semantics: each delta is handed out exactly once. If the caller's
    persist step fails it should call :func:`restore_pending_usage` so the
    counts aren't lost (retried on the next flush).
    """
    with _USAGE_LOCK:
        drained = dict(_PENDING_USAGE)
        _PENDING_USAGE.clear()
    return drained


def restore_pending_usage(deltas: Dict[Tuple[str, int, str], int]) -> None:
    """Re-add drained deltas after a failed flush so they retry next time."""
    if not deltas:
        return
    with _USAGE_LOCK:
        for k, v in deltas.items():
            _PENDING_USAGE[k] += v


# YouTube API quota costs
# https://developers.google.com/youtube/v3/determine_quota_cost
QUOTA_COSTS = {
    "search.list": 100,
    "channels.list": 1,
    "videos.list": 1,
    "playlistItems.list": 1,
    "commentThreads.list": 1,
}

DAILY_QUOTA_LIMIT = 10_000


def _load_persisted_usage(num_keys: int) -> Dict[int, int]:
    """Today's already-spent units per key_index from ``youtube_quota_usage``.

    A ``QuotaManager`` only counts usage in per-process memory, wiped on every
    restart. Without this, a freshly-started process assumes ALL keys are full,
    starts on key 0, and burns a wall of 403s rediscovering which keys are
    already exhausted (observed in prod: only the first ~5 keys ever get used
    while the rest sit idle). Hydrating from the durable table lets a restart
    skip spent keys and rotate straight to a live one.

    Fail-open: returns ``{}`` on any error so a missing table / DB blip never
    breaks the client (worst case = the old restart-forgets behaviour)."""
    try:
        from sqlalchemy import func, select

        from src.database.connection import get_session
        from src.database.models import YouTubeQuotaUsage as Q

        today = _quota_day().isoformat()
        with get_session() as db:
            rows = db.execute(
                select(Q.key_index, func.sum(Q.units))
                .where(Q.usage_date == today)
                .group_by(Q.key_index)
            ).all()
        return {int(k): int(u) for k, u in rows
                if k is not None and 0 <= int(k) < num_keys}
    except Exception as e:  # noqa: BLE001
        logger.warning("quota_hydrate_failed", error=str(e)[:120])
        return {}


class QuotaManager:
    """
    Manages YouTube API quota across multiple API keys.
    
    Features:
    - Rotates between multiple API keys
    - Tracks daily usage per key
    - Prevents quota exhaustion
    - Provides quota-aware key selection
    - Marks dead keys (exhausted or auth errors) to skip them
    """
    
    def __init__(self, api_keys: Optional[List[str]] = None):
        """
        Initialize quota manager.
        
        Args:
            api_keys: List of YouTube API keys. If None, loads from settings.
        """
        if api_keys is None:
            settings = get_settings()
            api_keys = settings.youtube_api_keys
        
        if not api_keys:
            raise ValueError("No YouTube API keys configured")
        
        self.api_keys = api_keys
        self._usage: dict[int, dict[date, int]] = {i: {} for i in range(len(api_keys))}
        self._current_key_index = 0
        self._dead_keys: set[int] = set()  # Keys that are exhausted or have auth errors

        # Hydrate today's usage from the durable table so a restarted process
        # doesn't assume every key is fresh and hammer already-spent keys.
        today = _quota_day()
        persisted = _load_persisted_usage(len(api_keys))
        for i, used in persisted.items():
            self._usage[i][today] = used
        # Start on the key with the MOST remaining quota, so a restart doesn't
        # begin on a spent (or nearly-spent) key and immediately have to rotate.
        best = max(range(len(api_keys)),
                   key=lambda i: self._get_remaining_quota(i, today))
        if self._get_remaining_quota(best, today) > 0:
            self._current_key_index = best

        logger.info(
            "quota_manager_initialized",
            num_keys=len(api_keys),
            hydrated_keys=len(persisted),
            start_key=self._current_key_index,
            total_used_today=sum(persisted.values()),
        )
    
    def get_current_key(self) -> str:
        """Get the current API key."""
        return self.api_keys[self._current_key_index]
    
    def get_key_with_quota(self, required_units: int = 1) -> Optional[str]:
        """
        Get an API key that has enough quota remaining.
        
        Args:
            required_units: Minimum quota units needed

        Returns:
            API key with sufficient quota, or None if all exhausted
        """
        today = _quota_day()
        
        # Try current key first (if not dead)
        if (self._current_key_index not in self._dead_keys and 
            self._get_remaining_quota(self._current_key_index, today) >= required_units):
            return self.api_keys[self._current_key_index]
        
        # Try other keys (skip dead ones)
        for i in range(len(self.api_keys)):
            if i != self._current_key_index and i not in self._dead_keys:
                if self._get_remaining_quota(i, today) >= required_units:
                    self._current_key_index = i
                    logger.info("rotated_api_key", new_key_index=i)
                    return self.api_keys[i]
        
        logger.warning("all_keys_exhausted", dead_keys=len(self._dead_keys), total_keys=len(self.api_keys))
        return None
    
    def mark_key_dead(self, key_index: Optional[int] = None, reason: str = "unknown") -> None:
        """
        Mark a key as dead (exhausted or auth error).
        
        Args:
            key_index: Which key to mark. Defaults to current key.
            reason: Why the key is being marked dead
        """
        if key_index is None:
            key_index = self._current_key_index
        
        self._dead_keys.add(key_index)
        logger.warning("key_marked_dead", key_index=key_index, reason=reason)
        
        # Find next working key
        for i in range(len(self.api_keys)):
            if i not in self._dead_keys:
                self._current_key_index = i
                logger.info("switched_to_key", new_key_index=i)
                return
        
        logger.error("no_working_keys_remaining")
    
    def get_working_key_count(self) -> int:
        """Get number of keys that aren't marked as dead."""
        return len(self.api_keys) - len(self._dead_keys)
    
    def record_usage(self, operation: str, key_index: Optional[int] = None) -> None:
        """
        Record quota usage for an operation.
        
        Args:
            operation: The API operation (e.g., "search.list")
            key_index: Which key was used. Defaults to current key.
        """
        if key_index is None:
            key_index = self._current_key_index
        
        cost = QUOTA_COSTS.get(operation, 1)
        today = _quota_day()

        if today not in self._usage[key_index]:
            self._usage[key_index][today] = 0

        self._usage[key_index][today] += cost
        # Feed the durable accumulator so the periodic flush can persist it.
        _accumulate_usage(key_index, operation, cost)

        logger.debug(
            "quota_recorded",
            operation=operation,
            cost=cost,
            key_index=key_index,
            daily_total=self._usage[key_index][today]
        )
    
    def _get_remaining_quota(self, key_index: int, day: date) -> int:
        """Get remaining quota for a key on a given day."""
        used = self._usage[key_index].get(day, 0)
        return DAILY_QUOTA_LIMIT - used
    
    def get_status(self) -> dict:
        """Get current quota status for all keys."""
        today = _quota_day()
        status = {
            "date": today.isoformat(),
            "current_key_index": self._current_key_index,
            "keys": []
        }
        
        for i in range(len(self.api_keys)):
            used = self._usage[i].get(today, 0)
            remaining = DAILY_QUOTA_LIMIT - used
            status["keys"].append({
                "index": i,
                "used": used,
                "remaining": remaining,
                "exhausted": remaining <= 0
            })
        
        status["total_remaining"] = sum(k["remaining"] for k in status["keys"])
        return status
    
    def estimate_available_searches(self) -> int:
        """Estimate how many search operations we can still do today."""
        status = self.get_status()
        total_remaining = status["total_remaining"]
        search_cost = QUOTA_COSTS["search.list"]
        return total_remaining // search_cost

