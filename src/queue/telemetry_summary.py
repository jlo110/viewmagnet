"""Aggregation queries over the render-pipeline telemetry stream.

Companion to :mod:`src.queue.telemetry` (the emit side). Where the
emit module writes one ``AuditEvent`` row per lifecycle moment, this
module reads those rows back and rolls them into the small handful
of numbers an operator actually wants to look at:

  * how many renders we attempted (window-bounded)
  * how many landed (``completed``)
  * how many failed (``failed`` + ``dlq``)
  * how many were cancelled by the user (``cancelled``)
  * how many got blocked at the budget gate (``budget_blocked``)
  * end-to-end wall time (``queued`` → ``completed``)
  * failure breakdown by ``error_type`` (top-N)
  * a per-day time-series so we can render a 24h / 7d trend

All queries are scoped by a ``[since, until]`` window with a default
of "last 24h" so a casual page load doesn't scan the whole audit
table. Indexes already exist on ``(event_type, created_at)`` so the
filters are cheap even with millions of rows.

Why a dedicated module (instead of inline SQL in the router):

  * makes the aggregations testable without spinning up FastAPI
  * keeps the JSON-parsing-from-``details`` logic in one place; the
    audit table stores ``details`` as a JSON-encoded string and the
    router shouldn't have to know that
  * documents which fields we read from each event, so changes to
    :mod:`src.queue.telemetry` that drop a field will fail loudly
    in tests instead of silently producing zeros in the UI
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import AuditEvent

logger = structlog.get_logger(__name__)


# Default lookback window when the caller doesn't pass ``since``.
# 24h is the smallest window that still captures a daily render
# cohort end-to-end (queued → completed can take ~15 min for a long
# project but never spans days).
DEFAULT_LOOKBACK = timedelta(hours=24)

# Event types we read from the audit table. Keeping this here (vs
# inlining the strings) makes it cheap to grep for "which events
# does the dashboard depend on" the next time we add a lifecycle
# moment.
LIFECYCLE_EVENTS: tuple[str, ...] = (
    "render.queued",
    "render.started",
    "render.completed",
    "render.failed",
    "render.dlq",
    "render.cancelled",
    "render.budget_blocked",
    "render.retried",
)


def _parse_details(raw: Optional[str]) -> dict:
    """Decode the ``AuditEvent.details`` JSON blob, never raising.

    Audit rows are best-effort — a corrupt row or non-JSON details
    field should drop one data point, not 500 the whole dashboard.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_window(
    since: Optional[datetime],
    until: Optional[datetime],
) -> tuple[datetime, datetime]:
    """Clamp the (since, until) window to sensible defaults.

    Everything in the audit table is stored in UTC naive; callers
    may pass tz-aware or tz-naive datetimes — we coerce to naive UTC
    so the comparison against ``AuditEvent.created_at`` works
    regardless. Inverting the bounds yields an empty window rather
    than a backwards scan.
    """
    now = datetime.utcnow()
    if until is None:
        until = now
    if since is None:
        since = until - DEFAULT_LOOKBACK
    # Coerce tz-aware → naive UTC so comparisons with the column
    # (stored naive) don't raise.
    if since.tzinfo is not None:
        since = since.astimezone(timezone.utc).replace(tzinfo=None)
    if until.tzinfo is not None:
        until = until.astimezone(timezone.utc).replace(tzinfo=None)
    if since > until:
        # Inverted window → collapse to a microsecond *after* until
        # so the SQL ``WHERE created_at BETWEEN since AND until``
        # filter returns nothing rather than matching whatever
        # happens to land exactly on the boundary.
        since = until + timedelta(microseconds=1)
    return since, until


def _fetch_events(
    db: Session,
    since: datetime,
    until: datetime,
) -> list[AuditEvent]:
    """Pull the raw audit rows in window for the lifecycle events.

    Returns rows in chronological order so callers can stitch
    ``queued`` → ``completed`` pairs in a single pass without a
    secondary sort.
    """
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.event_type.in_(LIFECYCLE_EVENTS))
        .where(AuditEvent.created_at >= since)
        .where(AuditEvent.created_at <= until)
        .order_by(AuditEvent.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())


def summarize_renders(
    db: Session,
    *,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    top_errors: int = 5,
) -> dict:
    """Return the rolled-up render-pipeline summary for an admin UI.

    Returns shape::

        {
          "window": {"since": ISO, "until": ISO, "lookback_seconds": int},
          "counts": {
            "queued": int, "started": int, "completed": int,
            "failed": int, "dlq": int, "cancelled": int,
            "budget_blocked": int, "retried": int,
          },
          "rates": {
            "success_rate": float (0..1),
            "failure_rate": float (0..1),
            "cancel_rate": float (0..1),
          },
          "wait_seconds": {
            "p50": float | None, "p95": float | None, "samples": int,
          },
          "render_seconds": {
            "p50": float | None, "p95": float | None, "samples": int,
          },
          "top_errors": [{"error_type": str, "count": int}],
          "by_day": [{"date": "YYYY-MM-DD", "queued": int, "completed": int, "failed": int}],
        }

    Notes:

      * "Wait" = ``queued.created_at`` → ``started.created_at``;
        "Render" = ``started.created_at`` → ``completed.created_at``.
        Both rely on render_id + render_kind to pair events; if a
        ``queued`` event lacks a matching ``started`` (e.g. because
        the worker crashed) we just don't contribute to wait.
      * Percentiles are computed via simple nearest-rank (no numpy
        dependency); good enough for an at-a-glance dashboard.
      * Daily buckets use UTC date for stability across DST.
    """
    since, until = _normalize_window(since, until)
    events = _fetch_events(db, since, until)

    counts: Counter[str] = Counter()
    by_day: dict[str, dict[str, int]] = defaultdict(
        lambda: {"queued": 0, "completed": 0, "failed": 0}
    )
    error_types: Counter[str] = Counter()

    # Pair (kind, id) → list of (event_type, ts) so we can compute
    # wait and render durations without N+1 queries. We accept a
    # small dup-key risk (same render_id reused across kinds is
    # already keyed by kind) — the production data we've seen
    # doesn't have collisions.
    pairs: dict[tuple[str, str], list[tuple[str, datetime]]] = defaultdict(list)

    for evt in events:
        short = evt.event_type.removeprefix("render.")
        counts[short] += 1
        day = evt.created_at.date().isoformat()
        if short in ("queued", "completed", "failed"):
            by_day[day][short] += 1
        if short in ("queued", "started", "completed"):
            details = _parse_details(evt.details)
            kind = details.get("render_kind") or "unknown"
            rid = details.get("render_id")
            if rid is not None:
                pairs[(kind, str(rid))].append((short, evt.created_at))
        if short in ("failed", "dlq"):
            details = _parse_details(evt.details)
            et = (
                details.get("error_type")
                or details.get("error_class")
                or "Unknown"
            )
            error_types[str(et)] += 1

    # Roll the pairs into duration lists. We only contribute one
    # data point per (kind, id) per phase so a retried render
    # doesn't double-count.
    wait_durations: list[float] = []
    render_durations: list[float] = []
    for events_for_render in pairs.values():
        events_for_render.sort(key=lambda x: x[1])
        ts_by_event: dict[str, datetime] = {}
        for et, ts in events_for_render:
            ts_by_event.setdefault(et, ts)
        if "queued" in ts_by_event and "started" in ts_by_event:
            delta = (ts_by_event["started"] - ts_by_event["queued"]).total_seconds()
            if delta >= 0:
                wait_durations.append(delta)
        if "started" in ts_by_event and "completed" in ts_by_event:
            delta = (ts_by_event["completed"] - ts_by_event["started"]).total_seconds()
            if delta >= 0:
                render_durations.append(delta)

    def _pct(values: list[float], pct: int) -> Optional[float]:
        """Nearest-rank percentile. Returns ``None`` on empty input."""
        if not values:
            return None
        ranked = sorted(values)
        # nearest-rank: 0-indexed → ceil(p/100 * N) - 1, clamped.
        idx = max(0, min(len(ranked) - 1, int(round(pct / 100 * len(ranked) - 1))))
        return float(ranked[idx])

    queued = counts.get("queued", 0)
    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0) + counts.get("dlq", 0)
    cancelled = counts.get("cancelled", 0)

    # Denominator = "renders that reached a terminal state in window".
    # Cancellations count toward the denominator (the user did
    # something) but not toward success or failure — they get their
    # own rate. ``max(1, …)`` avoids divide-by-zero when there's
    # nothing in window yet.
    terminal = completed + failed + cancelled
    denom = max(1, terminal)

    return {
        "window": {
            "since": since.isoformat() + "Z",
            "until": until.isoformat() + "Z",
            "lookback_seconds": int((until - since).total_seconds()),
        },
        "counts": {
            "queued": queued,
            "started": counts.get("started", 0),
            "completed": completed,
            "failed": counts.get("failed", 0),
            "dlq": counts.get("dlq", 0),
            "cancelled": cancelled,
            "budget_blocked": counts.get("budget_blocked", 0),
            "retried": counts.get("retried", 0),
        },
        "rates": {
            "success_rate": round(completed / denom, 4) if terminal else 0.0,
            "failure_rate": round(failed / denom, 4) if terminal else 0.0,
            "cancel_rate": round(cancelled / denom, 4) if terminal else 0.0,
        },
        "wait_seconds": {
            "p50": _pct(wait_durations, 50),
            "p95": _pct(wait_durations, 95),
            "samples": len(wait_durations),
        },
        "render_seconds": {
            "p50": _pct(render_durations, 50),
            "p95": _pct(render_durations, 95),
            "samples": len(render_durations),
        },
        "top_errors": [
            {"error_type": et, "count": c}
            for et, c in error_types.most_common(top_errors)
        ],
        "by_day": [
            {
                "date": d,
                "queued": by_day[d]["queued"],
                "completed": by_day[d]["completed"],
                "failed": by_day[d]["failed"],
            }
            for d in sorted(by_day)
        ],
    }
