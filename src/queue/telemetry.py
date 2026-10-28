"""Render-pipeline telemetry helpers (Week 8 Day 6.1).

A thin, namespaced emit layer over ``structlog`` so the whole render
funnel (enqueue → start → progress → success / failure / retry / DLQ
/ email-sent) shows up under a single, queryable event prefix
``render.*`` regardless of which module fires it.

Why a dedicated module:

  - Before this, lifecycle moments were ad-hoc log lines with
    inconsistent shapes (``studio.render.failed`` here,
    ``queue.dlq_push`` there). That made the conversion funnel
    ("queued → completed") effectively unqueryable.
  - Centralizing the emit gives us a single point to later route
    events into Mixpanel / Segment / a webhook without touching
    every call site.
  - High-volume events (``render.progress``) are sampled to keep
    log volume sane while low-volume lifecycle events (``queued``,
    ``completed``, ``failed``, ``dlq``, ``budget_blocked``,
    ``email_sent``, ``retried``) get a row each.

Every event carries a consistent base shape — ``user_id``,
``render_kind`` ("session" | "project"), ``render_id`` — plus
event-specific fields. Anything missing is left out rather than
filled with ``None`` so the structured payload stays compact.

Audit events: the lifecycle moments worth tracing back per-user
(queued / completed / failed / budget_blocked / dlq) are also
written to the ``AuditEvent`` table via the shared
``record_audit_event`` helper, so the ops UI can answer "what
happened to user X's render?" without scanning logs. Progress is
intentionally NOT persisted (too high-volume).
"""
from __future__ import annotations

from typing import Any, Optional

import structlog

from src.auth.audit import record_audit_event

logger = structlog.get_logger(__name__)

# Sampling: log every Nth progress event so we keep volume in check
# while still seeing the curve. Set ``_PROGRESS_SAMPLE_EVERY=1`` in
# tests when you want to assert every event.
_PROGRESS_SAMPLE_EVERY = 5

# Lifecycle events worth persisting to the audit table. Keeping the
# list explicit (vs "everything except progress") makes it obvious
# which moments are queryable per-user.
_AUDITED_EVENTS: frozenset[str] = frozenset(
    {
        "render.queued",
        "render.started",
        "render.completed",
        "render.failed",
        "render.retried",
        "render.dlq",
        "render.cancelled",
        "render.budget_blocked",
        "render.email_sent",
    }
)


def _emit(
    event: str,
    *,
    user_id: Optional[int],
    render_kind: Optional[str],
    render_id: Optional[Any],
    audit: bool = True,
    **fields: Any,
) -> None:
    """Internal: emit a structured log + optional audit row.

    All public ``record_*`` functions thread through this so the
    payload shape stays uniform. ``audit=False`` lets the
    high-volume progress emitter skip the DB write.
    """
    base = {
        "user_id": user_id,
        "render_kind": render_kind,
        "render_id": render_id,
    }
    payload = {k: v for k, v in {**base, **fields}.items() if v is not None}
    # structlog: ``event`` becomes the log message; the rest are kv.
    logger.info(event, **payload)

    if audit and event in _AUDITED_EVENTS:
        try:
            record_audit_event(
                event_type=event,
                user_id=user_id,
                details=payload,
            )
        except Exception:  # noqa: BLE001
            # Audit writes are best-effort — never fail the caller.
            pass


# ---------------------------------------------------------------------------
# Public API — one function per lifecycle moment so call sites read like
# prose ("record_render_queued(...)") and the field set is documented
# in the signature.
# ---------------------------------------------------------------------------


def record_render_queued(
    *,
    user_id: Optional[int],
    render_kind: str,
    render_id: Any,
    projected_seconds: Optional[float] = None,
    job_id: Optional[str] = None,
    plan: Optional[str] = None,
) -> None:
    """Fired the moment the API hands the job to RQ (or sync fallback).

    ``projected_seconds`` is the budget estimate the API used for the
    pre-check; persisting it makes "the meter said X but ffmpeg
    rendered Y" debuggable.
    """
    _emit(
        "render.queued",
        user_id=user_id,
        render_kind=render_kind,
        render_id=render_id,
        projected_seconds=projected_seconds,
        job_id=job_id,
        plan=plan,
    )


def record_render_started(
    *,
    user_id: Optional[int],
    render_kind: str,
    render_id: Any,
    job_id: Optional[str] = None,
) -> None:
    """Worker has picked up the job and started actual work."""
    _emit(
        "render.started",
        user_id=user_id,
        render_kind=render_kind,
        render_id=render_id,
        job_id=job_id,
    )


def record_render_progress(
    *,
    user_id: Optional[int],
    render_kind: str,
    render_id: Any,
    percent: Optional[float],
    message: Optional[str] = None,
) -> None:
    """High-volume tick. Sampled — only every Nth call lands in the
    log to keep aggregation cheap. Always skipped from the audit DB.
    """
    if percent is None:
        # Without a percent we can't sample; treat as a milestone.
        sampled = True
    else:
        # Sample at fixed percent buckets (0/25/50/75/100) so the
        # log stream is human-readable and we still capture both
        # endpoints.
        bucket = int(percent // (100 / _PROGRESS_SAMPLE_EVERY))
        sampled = bucket != getattr(record_render_progress, "_last_bucket", -1)
        if sampled:
            record_render_progress._last_bucket = bucket  # type: ignore[attr-defined]
    if not sampled:
        return
    _emit(
        "render.progress",
        user_id=user_id,
        render_kind=render_kind,
        render_id=render_id,
        percent=percent,
        message=message,
        audit=False,
    )


def record_render_completed(
    *,
    user_id: Optional[int],
    render_kind: str,
    render_id: Any,
    duration_seconds: Optional[float] = None,
    output_url: Optional[str] = None,
    minutes_billed: Optional[float] = None,
) -> None:
    """Render finished successfully + the output is reachable."""
    _emit(
        "render.completed",
        user_id=user_id,
        render_kind=render_kind,
        render_id=render_id,
        duration_seconds=duration_seconds,
        output_url=output_url,
        minutes_billed=minutes_billed,
    )


def record_render_failed(
    *,
    user_id: Optional[int],
    render_kind: str,
    render_id: Any,
    error: str,
    error_type: Optional[str] = None,
    duration_seconds: Optional[float] = None,
) -> None:
    """Render reached a terminal failure (after retries, if any)."""
    _emit(
        "render.failed",
        user_id=user_id,
        render_kind=render_kind,
        render_id=render_id,
        error=error,
        error_type=error_type,
        duration_seconds=duration_seconds,
    )


def record_render_retried(
    *,
    user_id: Optional[int],
    render_kind: str,
    render_id: Any,
    attempt: int,
    error: Optional[str] = None,
    error_type: Optional[str] = None,
) -> None:
    """RQ auto-retry kicked in. ``attempt`` is 1-indexed."""
    _emit(
        "render.retried",
        user_id=user_id,
        render_kind=render_kind,
        render_id=render_id,
        attempt=attempt,
        error=error,
        error_type=error_type,
    )


def record_render_dlq(
    *,
    user_id: Optional[int],
    render_kind: Optional[str],
    render_id: Optional[Any],
    job_id: Optional[str],
    func_name: Optional[str],
    error: str,
    error_type: Optional[str] = None,
) -> None:
    """Job exhausted retries and landed on the dead-letter queue.

    ``user_id`` / ``render_kind`` / ``render_id`` are best-effort —
    the DLQ payload only knows the original args/kwargs the caller
    passed, so we try to pull them out at the call site.
    """
    _emit(
        "render.dlq",
        user_id=user_id,
        render_kind=render_kind,
        render_id=render_id,
        job_id=job_id,
        func_name=func_name,
        error=error,
        error_type=error_type,
    )


def record_render_email_sent(
    *,
    user_id: Optional[int],
    render_kind: str,
    render_id: Any,
    outcome: str,
    email: Optional[str] = None,
) -> None:
    """Render-completion (or failure) notification was sent.

    ``outcome`` is ``"success"`` or ``"failure"`` so we can split
    open-rate by what we told the user.
    """
    _emit(
        "render.email_sent",
        user_id=user_id,
        render_kind=render_kind,
        render_id=render_id,
        outcome=outcome,
        email=email,
    )


def record_render_cancelled(
    *,
    user_id: Optional[int],
    render_kind: str,
    render_id: Any,
    job_id: Optional[str] = None,
    cancelled_by: str = "user",
    previous_status: Optional[str] = None,
    elapsed_seconds: Optional[float] = None,
) -> None:
    """User (or operator) cancelled an in-flight render.

    Distinguished from ``render.failed`` so dashboards can compute
    a true failure rate that doesn't count user-initiated stops.
    ``cancelled_by`` is ``"user"`` for the normal "X Cancel" button
    or ``"admin"`` for operator-driven cancels from the queue
    admin UI; ``previous_status`` lets us split "queued cancel" vs
    "in-flight cancel" since they cost very different things.
    """
    _emit(
        "render.cancelled",
        user_id=user_id,
        render_kind=render_kind,
        render_id=render_id,
        job_id=job_id,
        cancelled_by=cancelled_by,
        previous_status=previous_status,
        elapsed_seconds=elapsed_seconds,
    )


def record_render_budget_blocked(
    *,
    user_id: Optional[int],
    render_kind: str,
    render_id: Optional[Any] = None,
    projected_seconds: Optional[float] = None,
    minutes_remaining: Optional[float] = None,
    plan: Optional[str] = None,
) -> None:
    """API rejected the enqueue because the user is out of budget."""
    _emit(
        "render.budget_blocked",
        user_id=user_id,
        render_kind=render_kind,
        render_id=render_id,
        projected_seconds=projected_seconds,
        minutes_remaining=minutes_remaining,
        plan=plan,
    )
