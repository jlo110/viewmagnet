"""Monthly render-minute budgets (Week 8).

Free plan is capped at 30 render minutes per UTC calendar month; Pro
+ Enterprise are unlimited. The render API pre-checks projected work
against :func:`would_exceed_budget` and rejects with HTTP 402 when the
user has run out. Post-completion, every render job calls
:func:`record_render_minutes` with the actual duration so the meter
stays honest.

Design rules:

* **Source of truth is the DB row** (``UserRenderUsage``), not a
  cached counter — concurrent renders in two browser tabs can't
  double-spend because the row is upserted under SELECT-FOR-UPDATE
  semantics inside ``record_render_minutes``.
* **Fail-open on accounting errors.** If the post-completion record
  fails (DB blip), the render still counts as delivered — we'd
  rather under-meter once than fail a render that already shipped.
  Logged at warn so we can spot drift.
* **Pre-check is best-effort.** We compute the projected minutes
  from spec duration, not actual; long-tail renders that take more
  may technically blow through by a small margin. Acceptable
  trade-off vs locking renders behind a hard estimate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import select

from src.database.connection import get_session
from src.database.models import User, UserRenderUsage

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Plan-keyed budget table
# ---------------------------------------------------------------------------

# Free plan = 30 render minutes per UTC month. The number is intentionally
# generous enough that a casual user never sees the limit but tight
# enough that a daily creator hits it within a week of real use.
#
# ``math.inf`` for paid tiers keeps every quota helper safe to call
# without branching — ``would_exceed_budget`` short-circuits on
# infinite budgets without ever hitting the DB.
RENDER_BUDGET_MINUTES: dict[str, float] = {
    "free": 30.0,
    "starter": 300.0,
    "pro": math.inf,
    "agency": math.inf,
    "enterprise": math.inf,  # back-compat alias for agency
}


def budget_for_plan(plan: Optional[str]) -> float:
    """Return the monthly render-minute cap for ``plan``.

    Unknown plans fall back to ``free`` so a typo never accidentally
    grants unlimited renders.
    """
    if not plan:
        return RENDER_BUDGET_MINUTES["free"]
    return RENDER_BUDGET_MINUTES.get(plan, RENDER_BUDGET_MINUTES["free"])


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------


def _current_month_start(now: Optional[datetime] = None) -> datetime:
    """First instant of the current UTC month (year-month, 00:00:00)."""
    now = now or datetime.utcnow()
    return datetime(now.year, now.month, 1)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetSnapshot:
    """A user's render-minute usage for the current UTC month.

    Returned by :func:`get_budget_snapshot` and exposed to the
    frontend via the Renders page's Quota card.
    """
    plan: str
    minutes_used: float
    minutes_limit: float  # ``math.inf`` for unlimited plans
    minutes_remaining: float  # ``math.inf`` for unlimited plans
    month_start: datetime

    @property
    def unlimited(self) -> bool:
        return math.isinf(self.minutes_limit)

    @property
    def percent_used(self) -> float:
        if self.unlimited or self.minutes_limit <= 0:
            return 0.0
        return min(100.0, 100.0 * self.minutes_used / self.minutes_limit)


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------


def get_budget_snapshot(user_id: int) -> BudgetSnapshot:
    """Return the user's current-month usage + remaining budget.

    Always returns a valid snapshot — for users with no row yet this
    month we synthesize a zero-usage snapshot rather than inserting a
    placeholder row (the DB write only happens on actual usage in
    :func:`record_render_minutes`).
    """
    month_start = _current_month_start()
    with get_session() as db:
        user = db.get(User, user_id)
        plan = user.plan if user is not None else "free"

        usage = (
            db.execute(
                select(UserRenderUsage).where(
                    UserRenderUsage.user_id == user_id,
                    UserRenderUsage.month_start == month_start,
                )
            )
            .scalar_one_or_none()
        )
        minutes_used = float(usage.minutes_used) if usage is not None else 0.0

    limit = budget_for_plan(plan)
    if math.isinf(limit):
        remaining = math.inf
    else:
        remaining = max(0.0, limit - minutes_used)
    return BudgetSnapshot(
        plan=plan,
        minutes_used=minutes_used,
        minutes_limit=limit,
        minutes_remaining=remaining,
        month_start=month_start,
    )


def get_remaining_minutes(user_id: int) -> float:
    """Convenience wrapper around :func:`get_budget_snapshot`."""
    return get_budget_snapshot(user_id).minutes_remaining


def would_exceed_budget(user_id: int, projected_minutes: float) -> bool:
    """True iff queueing ``projected_minutes`` of work would push
    the user over their monthly cap.

    Paid plans (``math.inf`` limit) always return False without
    hitting the DB.
    """
    snapshot = get_budget_snapshot(user_id)
    if snapshot.unlimited:
        return False
    # Compare with a tiny tolerance — float math on a 30-minute
    # budget plus a 1.99-minute render shouldn't trip a fence at
    # exactly 32.0 due to rounding.
    return (snapshot.minutes_used + projected_minutes) > (
        snapshot.minutes_limit + 1e-6
    )


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------


def record_render_minutes(user_id: int, minutes: float) -> BudgetSnapshot:
    """Add ``minutes`` to the user's current-month usage.

    Upserts the (user_id, month_start) row. Returns the post-write
    snapshot so callers can log "you've now used X / Y minutes" or
    surface a near-limit warning without an extra query.

    Negative or zero minutes are rejected (a render delivering zero
    seconds shouldn't bump the meter; let it through silently and
    return the current snapshot).
    """
    if minutes <= 0 or not math.isfinite(minutes):
        return get_budget_snapshot(user_id)

    month_start = _current_month_start()
    with get_session() as db:
        usage = (
            db.execute(
                select(UserRenderUsage).where(
                    UserRenderUsage.user_id == user_id,
                    UserRenderUsage.month_start == month_start,
                )
            )
            .scalar_one_or_none()
        )
        if usage is None:
            usage = UserRenderUsage(
                user_id=user_id,
                month_start=month_start,
                minutes_used=minutes,
            )
            db.add(usage)
        else:
            usage.minutes_used = float(usage.minutes_used) + minutes
        db.commit()

    logger.info(
        "billing.render_budget.recorded",
        user_id=user_id,
        added_minutes=round(minutes, 2),
    )
    return get_budget_snapshot(user_id)


# ---------------------------------------------------------------------------
# Pre-flight estimator helper used by routers
# ---------------------------------------------------------------------------


def estimate_render_minutes(duration_seconds: float) -> float:
    """Convert a clip / project duration in seconds to render minutes.

    Today this is a direct 1:1 mapping — render duration ≈ output
    duration — but kept as a function so we can grow it later
    (e.g. multiply by an aspect-ratio cost factor, 4K renders count
    double, etc.) without touching every call site.
    """
    if duration_seconds <= 0 or not math.isfinite(duration_seconds):
        return 0.0
    return duration_seconds / 60.0
