"""Durable YouTube quota accounting: flush, read, and alert.

The :class:`~src.youtube.quota.QuotaManager` counts usage only in memory, so
it evaporates on restart and can't be inspected from outside the process.
This module makes quota observable:

* :func:`flush_quota_usage` drains the process-global accumulator (fed by every
  ``record_usage`` call) into the ``youtube_quota_usage`` table, incrementing
  on conflict so the per-day total is accurate across restarts and processes.
* :func:`get_today_usage` / :func:`get_usage_history` read the table back for
  the scheduler log line and the admin endpoint.
* :func:`evaluate_quota_alert` decides whether we're close enough to running
  out that we should cut a job's cadence.

Sync DB (matches the jobs + admin router, which both use ``get_session``).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

import structlog
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from src.config import get_settings
from src.database.models import YouTubeQuotaUsage
from src.youtube.quota import (
    DAILY_QUOTA_LIMIT,
    drain_pending_usage,
    restore_pending_usage,
)

logger = structlog.get_logger(__name__)


def _num_keys() -> int:
    try:
        return max(1, len(get_settings().youtube_api_keys))
    except Exception:  # pragma: no cover - settings misconfig
        return 1


def flush_quota_usage(session) -> dict:
    """Drain the in-memory accumulator into the table (increment-on-conflict).

    Returns ``{"flushed": <units>, "rows": <row_count>}``. On any DB error the
    drained deltas are restored to the accumulator so nothing is lost — they're
    retried on the next flush.
    """
    deltas = drain_pending_usage()
    if not deltas:
        return {"flushed": 0, "rows": 0}
    try:
        for (usage_date, key_index, operation), units in deltas.items():
            if units <= 0:
                continue
            res = session.execute(
                update(YouTubeQuotaUsage)
                .where(
                    YouTubeQuotaUsage.usage_date == usage_date,
                    YouTubeQuotaUsage.key_index == key_index,
                    YouTubeQuotaUsage.operation == operation,
                )
                .values(units=YouTubeQuotaUsage.units + units)
            )
            if res.rowcount == 0:
                # No existing row — insert. A concurrent inserter (other
                # process) can win the race; fall back to the increment update.
                try:
                    session.execute(
                        insert(YouTubeQuotaUsage).values(
                            usage_date=usage_date,
                            key_index=key_index,
                            operation=operation,
                            units=units,
                        )
                    )
                    session.flush()
                except IntegrityError:
                    session.rollback()
                    session.execute(
                        update(YouTubeQuotaUsage)
                        .where(
                            YouTubeQuotaUsage.usage_date == usage_date,
                            YouTubeQuotaUsage.key_index == key_index,
                            YouTubeQuotaUsage.operation == operation,
                        )
                        .values(units=YouTubeQuotaUsage.units + units)
                    )
        session.commit()
    except Exception:
        session.rollback()
        restore_pending_usage(deltas)
        raise
    return {"flushed": sum(deltas.values()), "rows": len(deltas)}


def compute_status(rows: List[tuple], num_keys: int) -> dict:
    """Build a today-status dict from ``(key_index, operation, units)`` rows.

    Pure (no DB) so it's unit-testable. ``rows`` are the persisted per-key,
    per-operation totals for the day.
    """
    capacity = num_keys * DAILY_QUOTA_LIMIT
    per_key: dict[int, int] = {}
    per_op: dict[str, int] = {}
    for key_index, operation, units in rows:
        per_key[key_index] = per_key.get(key_index, 0) + units
        per_op[operation] = per_op.get(operation, 0) + units

    total_used = sum(per_key.values())
    total_remaining = max(0, capacity - total_used)
    # A key is "exhausted" once its accounted usage reaches the per-key limit.
    keys_exhausted = sum(1 for u in per_key.values() if u >= DAILY_QUOTA_LIMIT)

    return {
        "capacity": capacity,
        "num_keys": num_keys,
        "total_used": total_used,
        "total_remaining": total_remaining,
        "pct_remaining": round(total_remaining / capacity, 4) if capacity else 0.0,
        "keys_exhausted": keys_exhausted,
        "by_operation": dict(sorted(per_op.items(), key=lambda kv: -kv[1])),
        "by_key": [
            {
                "key_index": i,
                "used": per_key.get(i, 0),
                "remaining": max(0, DAILY_QUOTA_LIMIT - per_key.get(i, 0)),
                "exhausted": per_key.get(i, 0) >= DAILY_QUOTA_LIMIT,
            }
            for i in range(num_keys)
        ],
    }


def get_today_usage(session, on: Optional[str] = None) -> dict:
    """Return today's aggregated quota status from the table.

    "Today" is the YouTube quota day (US/Pacific), matching how QuotaManager
    accounts usage, so reporting lines up with the actual reset boundary."""
    from src.youtube.quota import _quota_day

    usage_date = on or _quota_day().isoformat()
    rows = session.execute(
        select(
            YouTubeQuotaUsage.key_index,
            YouTubeQuotaUsage.operation,
            YouTubeQuotaUsage.units,
        ).where(YouTubeQuotaUsage.usage_date == usage_date)
    ).all()
    status = compute_status([(r[0], r[1], r[2]) for r in rows], _num_keys())
    status["date"] = usage_date
    return status


def get_usage_history(session, days: int = 7) -> List[dict]:
    """Per-day total used / remaining for the last ``days`` days (UTC)."""
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    capacity = _num_keys() * DAILY_QUOTA_LIMIT
    rows = session.execute(
        select(
            YouTubeQuotaUsage.usage_date,
            func.sum(YouTubeQuotaUsage.units),
        )
        .where(YouTubeQuotaUsage.usage_date >= start)
        .group_by(YouTubeQuotaUsage.usage_date)
        .order_by(YouTubeQuotaUsage.usage_date)
    ).all()
    return [
        {
            "date": d,
            "used": int(used or 0),
            "remaining": max(0, capacity - int(used or 0)),
            "pct_remaining": round(max(0, capacity - int(used or 0)) / capacity, 4)
            if capacity
            else 0.0,
        }
        for d, used in rows
    ]


def evaluate_quota_alert(status: dict, alert_pct: float) -> Optional[dict]:
    """Return an alert dict when remaining quota is low, else ``None``.

    ``critical`` once everything is gone (no runway left); ``warn`` once below
    the configured threshold (time to cut a job's cadence).
    """
    pct = status.get("pct_remaining", 1.0)
    if status.get("total_remaining", 1) <= 0:
        level = "critical"
    elif pct < alert_pct:
        level = "warn"
    else:
        return None
    return {
        "level": level,
        "pct_remaining": pct,
        "total_remaining": status.get("total_remaining"),
        "total_used": status.get("total_used"),
        "keys_exhausted": status.get("keys_exhausted"),
        "capacity": status.get("capacity"),
    }
