"""Shared helpers and Pydantic models used by multiple API routers.

When ``src/api/main.py`` was split into per-domain routers, anything used by
more than one router was lifted into this module so we don't have circular
imports between routers and ``main.py``. Pure per-router types stay local.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel

from src.config import PLAN_LIMITS
from src.database.models import User


# ---------------------------------------------------------------------------
# Shared response models
# ---------------------------------------------------------------------------

class StabilityWarning(BaseModel):
    """Warning about over-optimization (multiple analyses of the same video)."""
    level: str  # "medium" or "high"
    message: str
    recommendation: str
    analysis_count: int


class RecommendationCtaResponse(BaseModel):
    """A structured, deep-linkable recommendation. See
    :class:`src.features.llm_analyzer.RecommendationCta`."""
    label: str
    tool: str
    href: str
    context: dict = {}


class AlgorithmSignalsResponse(BaseModel):
    """Algorithm signals (Start, Keep, Repeat) for a video."""
    start_score: float
    keep_score: float
    repeat_score: float
    overall_score: float
    bottleneck: str
    bottleneck_message: str
    recommendations: list[str]
    # Optional for back-compat — older backends never set it. Frontend
    # prefers this list when present and falls back to regex-matching
    # ``recommendations`` otherwise.
    recommendation_ctas: list[RecommendationCtaResponse] = []


# ---------------------------------------------------------------------------
# Per-user usage limits + monthly rollover
# ---------------------------------------------------------------------------

def _maybe_reset_monthly_usage(user: User, session) -> None:
    """Reset monthly counters if the billing window has passed (30 days)."""
    now = datetime.utcnow()
    period_start = getattr(user, "usage_period_start", None) or user.created_at or now
    if (now - period_start) >= timedelta(days=30):
        user.analyses_this_month = 0
        user.usage_period_start = now
        session.flush()


def check_usage_limit(user: User, session) -> tuple[bool, str]:
    """Return ``(allowed, message)`` after applying plan + referral-bonus limits.

    Resets monthly counters if the billing window expired.
    """
    _maybe_reset_monthly_usage(user, session)

    from src.config import UNLIMITED_PLANS

    if user.plan in UNLIMITED_PLANS:
        return True, "Unlimited analyses"

    plan_cfg = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"])
    base_limit = plan_cfg.get("analyses_per_month", 10)
    if base_limit < 0:
        return True, "Unlimited analyses"

    referral_bonus = getattr(user, "referral_bonus_analyses", 0)
    total_limit = base_limit + referral_bonus

    used = user.analyses_this_month
    remaining = total_limit - used

    if remaining <= 0:
        return False, (
            f"Monthly limit reached ({total_limit} analyses). "
            "Upgrade your plan or invite friends for +5 bonus analyses each."
        )

    return True, f"{remaining} analyses remaining this month"


def increment_usage(user: User, session) -> None:
    """Bump a user's monthly + daily analysis counters and persist immediately."""
    _maybe_reset_monthly_usage(user, session)
    user.analyses_this_month += 1
    user.analyses_today += 1
    user.last_analysis_at = datetime.utcnow()
    session.commit()


# ---------------------------------------------------------------------------
# Channel handle resolution (used by /channel/* and /velocity/*)
# ---------------------------------------------------------------------------

def resolve_channel_handle(client, handle: str) -> Optional[str]:
    """Resolve a YouTube ``@handle`` to a channel ID using ``client.search_channels``.

    ``client`` is the project's :class:`src.youtube.client.YouTubeClient`
    (not the raw Google Python client). Returns the channel ID or ``None``
    if no match is found.
    """
    import structlog

    log = structlog.get_logger(__name__)
    clean_handle = handle.lstrip("@").lower()

    try:
        results = client.search_channels(query=clean_handle, max_results=10)
        if results and "items" in results:
            for item in results["items"]:
                snippet = item.get("snippet", {})
                custom_url = snippet.get("customUrl", "").lower().lstrip("@")
                channel_title = snippet.get("title", "").lower().replace(" ", "")

                if custom_url == clean_handle or channel_title == clean_handle:
                    return (
                        item.get("snippet", {}).get("channelId")
                        or item.get("id", {}).get("channelId")
                    )

            # If no exact match, fall back to the first result.
            if results["items"]:
                first = results["items"][0]
                return (
                    first.get("snippet", {}).get("channelId")
                    or first.get("id", {}).get("channelId")
                )
    except Exception as e:
        log.warning("resolve_channel_handle.failed", handle=handle, error=str(e))

    return None


# ---------------------------------------------------------------------------
# Alerts <-> Analyze bridge (in-memory; replaced by Redis in a follow-up)
# ---------------------------------------------------------------------------
# These two structures used to live as module-level globals in main.py and
# are shared between the /analyze hot path and the alerts router. Hoisted
# here so both routers can import them without circular imports.

_recent_analyses: dict = {}
_dismissed_alerts: set = set()


def _cache_analysis_for_alerts(
    channel_id: str, video_id: str, analysis_result: dict
) -> None:
    """Cache an analysis result so the alerts engine can rescan it later.

    Keeps the most-recent 20 analyses per channel in memory. This is the same
    behaviour as the pre-split implementation; a Redis-backed replacement is
    on the roadmap (tracked in the App-Wide Improvement Plan).
    """
    if channel_id not in _recent_analyses:
        _recent_analyses[channel_id] = {}

    _recent_analyses[channel_id][video_id] = {
        "result": analysis_result,
        "cached_at": datetime.utcnow(),
        "video_id": video_id,
    }

    if len(_recent_analyses[channel_id]) > 20:
        oldest = min(
            _recent_analyses[channel_id].items(),
            key=lambda x: x[1]["cached_at"],
        )
        del _recent_analyses[channel_id][oldest[0]]


__all__ = [
    "StabilityWarning",
    "AlgorithmSignalsResponse",
    "_maybe_reset_monthly_usage",
    "check_usage_limit",
    "increment_usage",
    "resolve_channel_handle",
    "_cache_analysis_for_alerts",
    "_recent_analyses",
    "_dismissed_alerts",
]
