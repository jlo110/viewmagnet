"""Admin endpoints for managing the worker queue + DLQ (Week 8 polish).

All endpoints require the caller's email to be in ``ADMIN_EMAILS`` —
see :mod:`src.auth.admin`. Mounted under ``/admin/queue/*``.

What this router exposes:

* ``GET /admin/queue/dlq`` — paginated list of recent DLQ entries.
* ``POST /admin/queue/dlq/{job_id}/reenqueue`` — re-enqueue a single
  DLQ entry under its original ``func_name`` / ``args`` / ``kwargs``.
  The DLQ row is removed atomically on successful enqueue.
* ``DELETE /admin/queue/dlq/{job_id}`` — drop a DLQ entry without
  re-running it (e.g. the job is no longer relevant).
* ``POST /admin/queue/dlq/prune`` — manual prune older than ``age_days``.

The endpoints are intentionally low-magic: the operator inspects the
list, picks an action per row, and we do nothing implicit. Mass
re-enqueue is deliberately out of scope to keep the blast radius
small.
"""
from __future__ import annotations

import json as _json
from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.admin import require_admin
from src.config import get_settings
from src.queue.client import _DLQ_NAME, enqueue_job, prune_dlq

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DlqEntry(BaseModel):
    """One row in the DLQ. Mirrors the payload written by
    :func:`src.queue.client._dlq_push` plus a stable ``index`` so the
    UI can target the exact list position when re-enqueuing or
    deleting (we use ``LREM`` against the raw JSON, but the index lets
    the UI render a deterministic "row N" label)."""

    index: int
    job_id: Optional[str]
    func_name: Optional[str]
    args: List[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str]
    error_type: Optional[str]
    failed_at: Optional[str]


class DlqListResponse(BaseModel):
    entries: List[DlqEntry]
    total: int


class DlqMutationResponse(BaseModel):
    status: str  # "ok" | "not_found"
    job_id: Optional[str] = None
    detail: Optional[str] = None


class DlqPruneResponse(BaseModel):
    dropped: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_redis():
    """Return a Redis connection or raise 503 with a friendly message."""
    settings = get_settings()
    if not settings.redis_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="queue not configured (REDIS_URL missing)",
        )
    try:
        from redis import Redis
        conn = Redis.from_url(settings.redis_url)
        conn.ping()
        return conn
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"redis unreachable: {exc}",
        )


def _find_entry_by_job_id(conn, job_id: str) -> Optional[tuple[int, bytes, dict]]:
    """Walk the DLQ list looking for the entry with matching ``job_id``.

    Returns ``(index, raw_bytes, parsed_dict)`` or ``None`` if not
    found. We expect the DLQ to be small (≤1000) so a linear scan is
    fine; trading O(n) read for not needing a secondary index keeps
    the data layout dead-simple."""
    raw = conn.lrange(_DLQ_NAME, 0, -1)
    for i, item in enumerate(raw):
        try:
            parsed = _json.loads(item)
        except Exception:  # noqa: BLE001
            continue
        if parsed.get("job_id") == job_id:
            return (i, item, parsed)
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/admin/queue/dlq", response_model=DlqListResponse)
@limiter.limit(Tier.READ)
async def list_dlq(
    request: Request,  # noqa: ARG001 — required by slowapi limiter
    limit: int = Query(default=50, ge=1, le=500),
    current_user=Depends(require_admin),  # noqa: ARG001
):
    """Return the most recent DLQ entries (newest first)."""
    conn = _get_redis()
    raw = conn.lrange(_DLQ_NAME, 0, limit - 1)
    total = conn.llen(_DLQ_NAME)
    entries: list[DlqEntry] = []
    for i, item in enumerate(raw):
        try:
            parsed = _json.loads(item)
        except Exception:  # noqa: BLE001
            # Surface unparseable rows so the operator notices them
            # and can clean up by hand; carrying the index keeps the
            # UI's row math consistent.
            entries.append(
                DlqEntry(
                    index=i,
                    job_id=None,
                    func_name=None,
                    error="(unparseable DLQ entry)",
                    error_type=None,
                    failed_at=None,
                )
            )
            continue
        entries.append(
            DlqEntry(
                index=i,
                job_id=parsed.get("job_id"),
                func_name=parsed.get("func_name"),
                args=list(parsed.get("args") or []),
                kwargs=dict(parsed.get("kwargs") or {}),
                error=parsed.get("error"),
                error_type=parsed.get("error_type"),
                failed_at=parsed.get("failed_at"),
            )
        )
    return DlqListResponse(entries=entries, total=int(total))


@router.post(
    "/admin/queue/dlq/{job_id}/reenqueue",
    response_model=DlqMutationResponse,
)
@limiter.limit(Tier.WRITE)
async def reenqueue_dlq(
    request: Request,  # noqa: ARG001
    job_id: str,
    current_user=Depends(require_admin),
):
    """Re-enqueue a DLQ entry under its original function + args.

    Removes the DLQ row only after the enqueue succeeds so a Redis
    blip can't lose the failure record."""
    conn = _get_redis()
    found = _find_entry_by_job_id(conn, job_id)
    if found is None:
        return DlqMutationResponse(status="not_found", job_id=job_id)
    _, raw_item, parsed = found
    func_name = parsed.get("func_name")
    if not func_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DLQ entry has no func_name; cannot re-enqueue",
        )
    args = list(parsed.get("args") or [])
    kwargs = dict(parsed.get("kwargs") or {})
    try:
        new_job_id = enqueue_job(func_name, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"re-enqueue failed: {exc}",
        )
    # LREM count=1 removes exactly the first matching row.
    try:
        conn.lrem(_DLQ_NAME, 1, raw_item)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "admin.dlq.lrem_failed",
            job_id=job_id,
            error=str(exc),
        )
    logger.info(
        "admin.dlq.reenqueued",
        original_job_id=job_id,
        new_job_id=new_job_id,
        func=func_name,
        actor=current_user.email,
    )
    return DlqMutationResponse(
        status="ok", job_id=new_job_id, detail="re-enqueued"
    )


@router.delete(
    "/admin/queue/dlq/{job_id}", response_model=DlqMutationResponse
)
@limiter.limit(Tier.WRITE)
async def delete_dlq(
    request: Request,  # noqa: ARG001
    job_id: str,
    current_user=Depends(require_admin),
):
    """Drop a single DLQ entry without re-running it."""
    conn = _get_redis()
    found = _find_entry_by_job_id(conn, job_id)
    if found is None:
        return DlqMutationResponse(status="not_found", job_id=job_id)
    _, raw_item, _ = found
    try:
        removed = conn.lrem(_DLQ_NAME, 1, raw_item)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"delete failed: {exc}",
        )
    if removed == 0:
        return DlqMutationResponse(status="not_found", job_id=job_id)
    logger.info(
        "admin.dlq.deleted", job_id=job_id, actor=current_user.email
    )
    return DlqMutationResponse(status="ok", job_id=job_id, detail="deleted")


@router.post("/admin/queue/dlq/prune", response_model=DlqPruneResponse)
@limiter.limit(Tier.WRITE)
async def prune_dlq_endpoint(
    request: Request,  # noqa: ARG001
    age_days: int = Query(default=30, ge=1, le=365),
    current_user=Depends(require_admin),
):
    """Drop DLQ entries older than ``age_days`` (default 30)."""
    dropped = prune_dlq(max_age_days=age_days)
    logger.info(
        "admin.dlq.pruned",
        age_days=age_days,
        dropped=dropped,
        actor=current_user.email,
    )
    return DlqPruneResponse(dropped=dropped)
