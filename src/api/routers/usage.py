"""Per-user resource usage endpoints (Week 8).

Today this exposes the render-minute budget so the Studio + Renders
pages can show the quota card without re-querying every render-status
endpoint. Future siblings (LLM spend, storage GB) can live in the
same router so the frontend has one ``/usage/*`` namespace to reason
about.

Design rules:

* **Read-only.** Counters are owned by the feature that produces
  them (``record_render_minutes`` lives in ``render_budget.py``);
  this router only reads.
* **Returns shape the frontend can render directly.** No raw
  ``UserRenderUsage`` rows escape — the response is a flat
  ``RenderBudget`` matching the frontend's TS interface.
* **Never raises.** A DB blip returns the zero-usage snapshot rather
  than 500, so the quota card stays present even when reads
  transiently fail.
"""
from __future__ import annotations

import math
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User
from src.features.billing.render_budget import get_budget_snapshot

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["usage"])


class QueueSurge(BaseModel):
    """Worker queue surge snapshot piggybacked on the budget poll
    (P3 polish). The frontend uses this to show a "queue is busier
    than usual — your render will start in ~X seconds" banner so
    a backed-up worker doesn't look like a frozen UI.

    All fields are best-effort. When Redis isn't configured,
    ``available`` is False and the UI hides the banner.
    """

    available: bool
    level: str  # "normal" | "busy" | "slammed"
    queue_depth: int
    started: int
    estimated_wait_seconds: int


class RenderBudget(BaseModel):
    """Flat shape the frontend Quota card consumes directly.

    Mirrors ``BudgetSnapshot`` but JSON-safe (``math.inf`` → -1
    sentinel) and includes a precomputed ``percent_used`` so the
    progress bar doesn't have to do float math + handle
    division-by-zero.
    """

    plan: str
    minutes_used: float
    # ``-1`` signals "unlimited" so the JSON stays a plain number.
    # ``unlimited`` is the boolean the UI keys off of.
    minutes_limit: float
    minutes_remaining: float
    percent_used: float
    unlimited: bool
    month_start: datetime
    # P3 polish: ship the surge snapshot alongside the budget so the
    # frontend's existing ``useRenderBudget`` hook gets the surge
    # signal without a second round-trip.
    surge: QueueSurge | None = None


_UNLIMITED_SENTINEL = -1.0


def _to_response(snapshot) -> RenderBudget:
    """Convert the internal ``BudgetSnapshot`` (which uses ``math.inf``
    for unlimited plans) into the JSON-safe response shape.

    JSON can't carry infinity, so we collapse it to ``-1`` and let the
    ``unlimited`` boolean be the source of truth for the UI.
    """
    unlimited = snapshot.unlimited
    limit = (
        _UNLIMITED_SENTINEL
        if unlimited or not math.isfinite(snapshot.minutes_limit)
        else snapshot.minutes_limit
    )
    remaining = (
        _UNLIMITED_SENTINEL
        if unlimited or not math.isfinite(snapshot.minutes_remaining)
        else snapshot.minutes_remaining
    )
    # Probe queue depth + surge level (best-effort; returns an
    # ``available=False`` snapshot when Redis isn't configured so the
    # frontend can safely treat it as a no-op).
    from src.queue import get_queue_depth
    from src.queue.surge import classify_depth

    surge_snap = classify_depth(get_queue_depth())
    return RenderBudget(
        plan=snapshot.plan,
        minutes_used=round(snapshot.minutes_used, 2),
        minutes_limit=limit,
        minutes_remaining=remaining,
        percent_used=round(snapshot.percent_used, 1),
        unlimited=unlimited,
        month_start=snapshot.month_start,
        surge=QueueSurge(**surge_snap.to_dict()),
    )


@router.get("/usage/renders", response_model=RenderBudget)
@limiter.limit(Tier.READ)
async def get_user_render_budget(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Current-month render-minute usage for the calling user.

    Always returns a populated snapshot — a user who's never rendered
    anything sees a zero-usage row with the right plan-cap, so the
    Quota card looks correct on first paint. On read errors we
    synthesize the same zero snapshot rather than 500'ing so the rest
    of the dashboard keeps working.
    """
    try:
        snapshot = get_budget_snapshot(current_user.id)
        return _to_response(snapshot)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "usage.render_budget.read_failed",
            user_id=current_user.id,
            error=str(exc),
        )
        # Fail-safe stub. Mirrors the shape ``BudgetSnapshot`` would
        # return for a fresh free user so the UI doesn't crash on a
        # transient DB blip.
        return RenderBudget(
            plan="free",
            minutes_used=0.0,
            minutes_limit=30.0,
            minutes_remaining=30.0,
            percent_used=0.0,
            unlimited=False,
            month_start=datetime.utcnow().replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            ),
        )
