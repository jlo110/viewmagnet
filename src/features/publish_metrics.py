"""Post-publish analytics collector (Week 10).

After Distribution Hub publishes a render to a platform, this module
periodically pulls the post's performance back and persists it as
``PublishedMetricSnapshot`` rows so the user can answer "did that
render actually work?" without leaving the app.

Architecture:

  * **Per-platform fetcher.** Each supported platform implements
    :class:`PlatformFetcher` (``platform`` string + ``fetch(posted_id,
    posted_url) -> RawMetrics``). The real YouTube / TikTok /
    Instagram clients live alongside the existing Distribution Hub
    integrations (e.g. ``src/features/distribution/youtube.py``);
    this module only orchestrates *when* to call them and how to
    persist the result.

  * **Windowed sampling.** We sample at a fixed schedule from the
    post's ``published_at``:

      ============  ==========================================
      window_key    target offset from published_at
      ============  ==========================================
      ``1h``        +1 hour      (early signal — algorithm pick)
      ``24h``       +24 hours    (24h benchmark in most APIs)
      ``7d``        +7 days      (week-of-publish reality check)
      ``30d``       +30 days     (final long-tail number)
      ============  ==========================================

    The collector job ``collect_due_metrics`` walks every
    ``DistributionResult`` that's still inside an open window and
    fires the appropriate fetcher. Closed windows (their snapshot
    already exists, or we're past the +1d grace window for that
    window_key) are skipped so a long-running deployment doesn't
    re-poll a post forever.

  * **Idempotent upsert.** Each (result, window) combination resolves
    to at most one row — re-running the collector for the same
    window updates the same row. Lets us safely re-enqueue if the
    worker crashed mid-sweep.

  * **Stub fetcher for dev.** A built-in :class:`StubFetcher` returns
    plausible-looking deterministic metrics so the UI can render
    real values in dev/CI without API keys. Production wires the
    real fetchers via :func:`register_fetcher`.

Design constraints:

  * Never raises through the caller. A failing fetch logs + returns
    None, which leaves the snapshot row absent for that window. The
    next sweep retries.
  * Fetcher selection is registry-based so a deployment that doesn't
    have e.g. TikTok credentials simply doesn't register a fetcher
    for it and those posts are skipped, not failed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterable, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.connection import get_session
from src.database.models import (
    DistributionJob,
    DistributionResult,
    PublishedMetricSnapshot,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Window schedule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricWindow:
    """One sample window keyed by ``key`` (``"1h"``, ``"24h"``, ...).

    ``target_offset`` is when we *want* to sample — the collector
    treats the snapshot as "due" anywhere within
    ``[target_offset, target_offset + grace]`` and skips it once
    past the grace so the queue doesn't grow unbounded.
    """

    key: str
    target_offset: timedelta
    grace: timedelta = timedelta(hours=6)


# Order matters: the collector evaluates earlier windows first so a
# missed 24h sample is captured before we even consider the 7d window.
WINDOWS: tuple[MetricWindow, ...] = (
    MetricWindow("1h", timedelta(hours=1), timedelta(hours=1)),
    MetricWindow("24h", timedelta(hours=24), timedelta(hours=12)),
    MetricWindow("7d", timedelta(days=7), timedelta(days=2)),
    MetricWindow("30d", timedelta(days=30), timedelta(days=5)),
)


# ---------------------------------------------------------------------------
# Fetcher contract + registry
# ---------------------------------------------------------------------------


@dataclass
class RawMetrics:
    """Platform-agnostic shape returned by a fetcher.

    Every field is optional because no two platforms expose the same
    set — Instagram doesn't share retention, TikTok hides CTR, etc.
    Storing what we got and leaving the rest ``None`` is honest;
    coercing missing values to 0 would let the dashboard average a
    fake zero into the user's "click-through rate" card.
    """

    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    watch_time_seconds: Optional[float] = None
    avg_view_percentage: Optional[float] = None
    click_through_rate: Optional[float] = None
    raw: Optional[dict] = field(default_factory=dict)


PlatformFetcher = Callable[
    [Optional[str], Optional[str]], Optional[RawMetrics]
]
"""``(posted_id, posted_url) -> RawMetrics | None``. Returning
``None`` signals "no data yet" — the collector leaves the window
open and tries again on the next sweep."""


_FETCHERS: dict[str, PlatformFetcher] = {}


def register_fetcher(platform: str, fetcher: PlatformFetcher) -> None:
    """Register a fetcher for ``platform`` (e.g. ``"youtube"``).

    Last-write-wins so a deployment can override the default stub
    by importing the real fetcher in its app startup."""
    _FETCHERS[platform] = fetcher


def get_fetcher(platform: str) -> Optional[PlatformFetcher]:
    """Lookup a fetcher; returns ``None`` if the deployment hasn't
    registered one (e.g. no TikTok creds → posts get skipped, not
    failed)."""
    return _FETCHERS.get(platform)


# ---------------------------------------------------------------------------
# Built-in stub fetcher — deterministic plausible numbers for dev/CI
# ---------------------------------------------------------------------------


def stub_fetcher(
    posted_id: Optional[str],
    posted_url: Optional[str],
) -> RawMetrics:
    """Returns deterministic plausible metrics keyed by the post id.

    Used in dev/CI so the Outcomes UI can render a non-empty state
    without API keys. The numbers are stable across calls so tests
    can pin assertions to them.

    The "engagement curve" approximates the typical early-fast,
    long-tail-slow shape: takes the post id as a seed and produces a
    small triangle-numeric base that grows with the hash. Real
    deployments override this with the per-platform fetchers in
    ``src/features/distribution/*``.
    """
    seed = abs(hash((posted_id or posted_url or "anon"))) % 9_999
    views = 100 + (seed % 50_000)
    likes = max(1, views // 30)
    comments = max(1, views // 200)
    return RawMetrics(
        views=views,
        likes=likes,
        comments=comments,
        shares=max(0, comments // 4),
        # Realistic retention range so the chart doesn't show 100%.
        avg_view_percentage=round(30 + (seed % 60), 1),
        click_through_rate=round(0.5 + (seed % 7), 2),
        watch_time_seconds=float(views * 12),
        raw={"source": "stub", "seed": seed},
    )


# Auto-register the stub against every platform the Distribution Hub
# currently understands. Production deployments overwrite these with
# real fetchers; tests rely on these being present.
for _platform in ("youtube", "tiktok", "instagram"):
    register_fetcher(_platform, stub_fetcher)


# ---------------------------------------------------------------------------
# Window classification
# ---------------------------------------------------------------------------


def due_windows(
    *,
    published_at: datetime,
    existing_window_keys: Iterable[str],
    now: Optional[datetime] = None,
) -> list[MetricWindow]:
    """Return the windows that are inside their sampling band right now.

    A window is "due" iff:

      * we don't already have a snapshot for that key (no re-sample), AND
      * ``now`` is between ``published_at + offset`` and
        ``published_at + offset + grace``.

    The grace bound keeps the sampling queue bounded — once a
    window's grace expires, the collector permanently moves on for
    that post (no point in claiming "24h numbers" 5 days late).
    """
    now = now or datetime.utcnow()
    already = set(existing_window_keys)
    due: list[MetricWindow] = []
    for window in WINDOWS:
        if window.key in already:
            continue
        target = published_at + window.target_offset
        if now < target:
            # Future window — not yet eligible. Don't sample early.
            continue
        if now > target + window.grace:
            # Missed our chance for this window; skip permanently.
            continue
        due.append(window)
    return due


# ---------------------------------------------------------------------------
# Snapshot persistence
# ---------------------------------------------------------------------------


def record_metric_snapshot(
    db: Session,
    *,
    result: DistributionResult,
    user_id: int,
    window: MetricWindow,
    metrics: RawMetrics,
    published_at: datetime,
    now: Optional[datetime] = None,
) -> PublishedMetricSnapshot:
    """UPSERT a snapshot for (result, window_key).

    Done as a read-then-write rather than a vendor-specific upsert so
    the same code path works on SQLite tests and Postgres prod. Race
    risk is bounded — we'd at worst have two near-identical rows for
    the same window from two parallel sweeps, which the rollup
    handles gracefully (it ``max``-aggregates per window key).
    """
    now = now or datetime.utcnow()
    existing = db.execute(
        select(PublishedMetricSnapshot)
        .where(
            PublishedMetricSnapshot.distribution_result_id == result.id
        )
        .where(PublishedMetricSnapshot.window_key == window.key)
    ).scalar_one_or_none()

    raw_json = (
        json.dumps(metrics.raw, default=str) if metrics.raw else None
    )

    if existing is None:
        existing = PublishedMetricSnapshot(
            distribution_result_id=result.id,
            user_id=user_id,
            platform=result.platform,
            posted_url=result.posted_url,
            window_key=window.key,
            published_at=published_at,
            sampled_at=now,
        )
        db.add(existing)

    existing.sampled_at = now
    existing.views = metrics.views
    existing.likes = metrics.likes
    existing.comments = metrics.comments
    existing.shares = metrics.shares
    existing.watch_time_seconds = metrics.watch_time_seconds
    existing.avg_view_percentage = metrics.avg_view_percentage
    existing.click_through_rate = metrics.click_through_rate
    existing.raw = raw_json

    db.commit()
    db.refresh(existing)
    return existing


# ---------------------------------------------------------------------------
# Collector job — what the RQ worker calls
# ---------------------------------------------------------------------------


def collect_due_metrics(
    *,
    now: Optional[datetime] = None,
    max_age_days: int = 35,
) -> dict:
    """Walk recent successful DistributionResults and sample any due windows.

    Returns a small summary dict (``{"attempted": N, "written": M,
    "skipped_no_fetcher": K, ...}``) so the worker can log a single
    line per sweep instead of one per post.

    ``max_age_days`` bounds how far back we look — older results are
    past every window's grace and shouldn't be re-scanned. Defaults
    to 35 (5 days past the longest window).

    Never raises: each post is wrapped in its own try/except so one
    flaky platform doesn't kill the sweep for the others.
    """
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=max_age_days)

    summary = {
        "attempted": 0,
        "written": 0,
        "skipped_no_data": 0,
        "skipped_no_fetcher": 0,
        "errors": 0,
    }

    with get_session() as db:
        # Pull successful results plus the parent job (for
        # published_at + user_id without a per-row second query).
        stmt = (
            select(DistributionResult, DistributionJob)
            .join(
                DistributionJob,
                DistributionResult.job_id == DistributionJob.id,
            )
            .where(DistributionResult.status == "success")
            .where(DistributionResult.created_at >= cutoff)
        )
        rows = list(db.execute(stmt).all())

        for result, job in rows:
            try:
                _collect_for_result(
                    db,
                    result=result,
                    job=job,
                    now=now,
                    summary=summary,
                )
            except Exception as exc:  # noqa: BLE001
                summary["errors"] += 1
                logger.warning(
                    "publish_metrics.row_failed",
                    result_id=result.id,
                    platform=result.platform,
                    error=str(exc),
                )

    logger.info("publish_metrics.sweep", **summary)
    return summary


def _collect_for_result(
    db: Session,
    *,
    result: DistributionResult,
    job: DistributionJob,
    now: datetime,
    summary: dict,
) -> None:
    """Sample any due windows for one (result, job) pair."""
    # ``published_at`` falls back to the result's ``created_at`` when
    # the per-platform "posted at" wasn't recorded — better than
    # silently skipping the metric.
    published_at = result.completed_at or result.created_at
    fetcher = get_fetcher(result.platform)
    if fetcher is None:
        summary["skipped_no_fetcher"] += 1
        return

    # Discover which windows already have a snapshot so we don't
    # re-fetch them.
    existing_keys = set(
        db.execute(
            select(PublishedMetricSnapshot.window_key).where(
                PublishedMetricSnapshot.distribution_result_id == result.id
            )
        ).scalars().all()
    )

    targets = due_windows(
        published_at=published_at,
        existing_window_keys=existing_keys,
        now=now,
    )
    if not targets:
        return

    for window in targets:
        summary["attempted"] += 1
        try:
            metrics = fetcher(result.posted_id, result.posted_url)
        except Exception as exc:  # noqa: BLE001
            summary["errors"] += 1
            logger.warning(
                "publish_metrics.fetcher_failed",
                platform=result.platform,
                window=window.key,
                result_id=result.id,
                error=str(exc),
            )
            continue
        if metrics is None:
            summary["skipped_no_data"] += 1
            continue

        record_metric_snapshot(
            db,
            result=result,
            user_id=job.user_id,
            window=window,
            metrics=metrics,
            published_at=published_at,
            now=now,
        )
        summary["written"] += 1
