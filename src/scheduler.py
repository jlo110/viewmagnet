"""Standalone background scheduler process.

Runs the hourly metrics sweep (``collect_due_metrics``) in a single dedicated
process. This is the production home for periodic jobs.

Why a separate process instead of the API lifespan?
    The API runs under ``uvicorn --workers N``; its lifespan executes once per
    worker, so a scheduler started there fires every job N times (duplicate
    snapshots, wasted YouTube quota, write races). Running the scheduler in its
    own single-instance process guarantees exactly-once scheduling.

Usage:
    RUN_SCHEDULER=true python -m src.scheduler

In docker-compose this is the ``scheduler`` service. The API keeps its
lifespan scheduler too, but gated behind ``RUN_SCHEDULER`` (default off) so a
single-worker dev API can still opt in.
"""
from __future__ import annotations

import signal
from datetime import datetime, timedelta

import structlog

logger = structlog.get_logger(__name__)


def register_jobs(scheduler) -> None:
    """Register all periodic jobs on the given APScheduler instance.

    Shared by this standalone runner and the API lifespan so the schedule is
    defined in exactly one place.
    """
    from src.features.publish_metrics import collect_due_metrics
    from src.tracking.jobs import (
        archive_thumbnails,
        backfill_channel_history,
        capture_video_heatmaps,
        check_collection_health,
        compute_topic_clusters,
        compute_topic_momentum,
        pull_owner_analytics,
        recompute_emerging_formats,
        compute_coverage,
        enrich_channels,
        check_model_drift,
        collect_channel_snapshots,
        collect_top_comments,
        collect_velocity_snapshots,
        discover_channels_search,
        discover_new_videos,
        expand_tracked_channels,
        persist_quota_usage,
        prune_non_english_channels,
        renew_websub_subscriptions,
        send_watchlist_alerts,
        send_niche_digests,
        db_backup_and_archive,
        db_capacity_guard,
        compute_niche_benchmarks,
        compute_timing_benchmarks,
    )

    scheduler.add_job(
        collect_due_metrics,
        trigger="interval",
        hours=1,
        id="collect_due_metrics",
        replace_existing=True,
        max_instances=1,
    )

    # Velocity time-series rebuild. Discover new uploads hourly; sample
    # checkpoint snapshots every 30 min (tight enough for the 1h/+2h-grace
    # window). Both are no-ops until channels are enrolled in TrackedChannel.
    # Throughput caps come from settings so they can be tuned to quota.
    from src.config import get_settings

    _s = get_settings()
    # Post-WebSub (7.5, verified live 2026-06-12): polling discovery is a slow
    # RECONCILIATION sweep, not the primary detector — pushes arrive in minutes
    # for subscribed channels. Was hourly (99.5% of all quota, measured); every
    # 6h x a cap covering the full tracked set catches any missed pushes.
    scheduler.add_job(
        discover_new_videos,
        trigger="interval",
        hours=6,
        id="velocity_discover_new_videos",
        replace_existing=True,
        max_instances=1,
        kwargs={"max_channels": _s.velocity_discover_max_channels},
    )
    scheduler.add_job(
        collect_velocity_snapshots,
        trigger="interval",
        minutes=30,
        id="velocity_collect_snapshots",
        replace_existing=True,
        max_instances=1,
        kwargs={"max_videos": _s.velocity_collect_max_videos},
    )

    # Phase 7.2: daily channel time-series (subs/views/upload growth). Once-per-
    # UTC-day per channel; the job itself skips channels already snapshotted today.
    scheduler.add_job(
        collect_channel_snapshots,
        trigger="interval",
        hours=24,
        id="channel_snapshots",
        replace_existing=True,
        max_instances=1,
    )

    # Phase 7.2: archive thumbnail bytes to R2 (URLs rotate). Hourly, capped;
    # content-addressed keys make it idempotent. No-op if R2 isn't configured.
    scheduler.add_job(
        archive_thumbnails,
        trigger="interval",
        hours=1,
        id="thumbnail_archive",
        replace_existing=True,
        max_instances=1,
    )

    # Phase 7.2: capture top comments for videos that just passed 24h. Every 2h.
    scheduler.add_job(
        collect_top_comments,
        trigger="interval",
        hours=2,
        id="top_comments",
        replace_existing=True,
        max_instances=1,
    )

    # Phase 3.2: model/data drift check off the live backtest. Daily.
    scheduler.add_job(
        check_model_drift,
        trigger="interval",
        hours=24,
        id="model_drift_check",
        replace_existing=True,
        max_instances=1,
    )

    # Quota observability: persist accumulated YouTube quota usage to the DB and
    # alert when remaining quota is low. Every 5 min — frequent enough to catch
    # exhaustion in time to react, cheap (a handful of upserts).
    scheduler.add_job(
        persist_quota_usage,
        trigger="interval",
        minutes=5,
        id="quota_persist",
        replace_existing=True,
        max_instances=1,
    )

    # Collection QA (7.6): window hit-rate monitoring — catches silent dataset
    # erosion (late/missed samples) that per-job success logs hide. Daily.
    scheduler.add_job(
        check_collection_health,
        trigger="interval",
        hours=24,
        id="collection_health",
        replace_existing=True,
        max_instances=1,
    )

    # Phase 8.1: Most-Replayed heatmap capture (public retention proxy). Every
    # 6h, bounded + throttled; no API quota. No-ops until tracked videos reach
    # ~2 weeks of age.
    scheduler.add_job(
        capture_video_heatmaps,
        trigger="interval",
        hours=6,
        id="heatmap_capture",
        replace_existing=True,
        max_instances=1,
    )

    # Phase 8.2: topic-saturation clusters from recent upload titles. Every 6h;
    # zero API quota (embeds already-collected snapshot titles).
    scheduler.add_job(
        compute_topic_clusters,
        trigger="interval",
        hours=6,
        id="topic_clusters",
        replace_existing=True,
        max_instances=1,
    )

    # Topic Momentum (2.1): per-topic breakout density + trend. Runs after the
    # cluster batch it reads; every 6h, zero quota. Surfaces "which topics are
    # heating up right now" from our own breakout feed — market timing, not a
    # packaging predictor.
    scheduler.add_job(
        compute_topic_momentum,
        trigger="interval",
        hours=6,
        id="topic_momentum",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now() + timedelta(minutes=5),  # after the cluster batch
    )

    # Owner analytics pull (3.2 display half): real CTR + retention for connected
    # channels, daily. Uses each user's own OAuth quota (not ours); best-effort.
    scheduler.add_job(
        pull_owner_analytics,
        trigger="interval",
        hours=24,
        id="owner_analytics",
        replace_existing=True,
        max_instances=1,
    )

    # Format Radar: mine emerging title formats from the breakout window. Every 6h;
    # zero API quota (clusters already-collected breakout titles). Ranked by
    # momentum/openness — the live answer to a static format archive. (6h also
    # shortens the post-deploy blank window vs daily.)
    scheduler.add_job(
        recompute_emerging_formats,
        trigger="interval",
        hours=6,
        id="emerging_formats",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now() + timedelta(minutes=2),  # refresh soon after each deploy
    )

    # Watchlist breakout alerts: email users when a channel they're watching breaks
    # out. Hourly; zero quota (reads collected snapshots); deduped + console-backed
    # until EMAIL_PROVIDER is configured (so no real mail goes out yet).
    scheduler.add_job(
        send_watchlist_alerts,
        trigger="interval",
        hours=1,
        id="watchlist_alerts",
        replace_existing=True,
        max_instances=1,
    )

    # Measured publish-timing hit rates (daily, zero quota). Correlational.
    scheduler.add_job(
        compute_timing_benchmarks,
        trigger="interval",
        hours=24,
        id="timing_benchmarks",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now() + timedelta(minutes=11),
    )

    # Measured niche/format view-trajectory percentiles (daily, zero quota).
    # Descriptive benchmarks that replaced a fabricated-constants endpoint.
    scheduler.add_job(
        compute_niche_benchmarks,
        trigger="interval",
        hours=24,
        id="niche_benchmarks",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now() + timedelta(minutes=7),
    )

    # Postgres volume watchdog (hourly). The 2026-07-17 outage was a silent
    # disk-full: checks watched row counts, not bytes, so the volume reached 100%
    # between check-ins and corrupted WAL beyond in-place recovery (13 days down).
    # This logs usage every hour and archives immediately when critical.
    scheduler.add_job(
        db_capacity_guard,
        trigger="interval",
        hours=1,
        id="db_capacity_guard",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now() + timedelta(minutes=3),
    )

    # Nightly DB backup + snapshot archival to R2 (08:00 UTC = overnight US).
    # Railway PG has no managed backups and this dataset has been lost once
    # before; archival keeps the 5GB Hobby volume flat. Backup runs first;
    # archive only fires if it succeeded (see src/tools/db_backup.py).
    scheduler.add_job(
        db_backup_and_archive,
        trigger="cron",
        hour=8,
        id="db_backup_archive",
        replace_existing=True,
        max_instances=1,
    )

    # Weekly digest: a Monday-morning roundup of the week's biggest breakouts on
    # each opted-in user's watchlist (ranked by durability). Distinct from the
    # hourly real-time alerts; the B2B retention hook. Zero quota; console-backed
    # until EMAIL_PROVIDER is set. Mon 13:00 UTC = 9am ET.
    scheduler.add_job(
        send_niche_digests,
        trigger="cron",
        day_of_week="mon",
        hour=13,
        id="niche_digest",
        replace_existing=True,
        max_instances=1,
    )

    # Per-niche coverage metric (daily; zero quota). Flags starved niches so the
    # stratified expansion knows where to grow. Spec: stratified-expansion.md.
    scheduler.add_job(
        compute_coverage,
        trigger="interval",
        hours=24,
        id="niche_coverage",
        replace_existing=True,
        max_instances=1,
    )

    # Gradual channel enrichment (subscriber_count -> size_tier). Every 6h, small
    # batch (1 unit/50 channels); drains the backfill + keeps new channels enriched.
    scheduler.add_job(
        enrich_channels,
        trigger="interval",
        hours=6,
        id="enrich_channels",
        replace_existing=True,
        max_instances=1,
    )

    # Plan 7.5: WebSub push-subscription enrollment/renewal. Every 6h; no-op
    # until WEBSUB_CALLBACK_URL is set. Replaces polling discovery's quota.
    scheduler.add_job(
        renew_websub_subscriptions,
        trigger="interval",
        hours=6,
        id="websub_renew",
        replace_existing=True,
        max_instances=1,
    )

    # Plan 8.11: tracked-set growth from mostPopular charts (English-only).
    # Daily (was weekly): ~72 quota units/run — negligible vs budget — so the set
    # grows steadily instead of in weekly lumps. Adds only newly-trending channels
    # (the existing set is already subscribed/collected); diminishing per run.
    scheduler.add_job(
        expand_tracked_channels,
        trigger="interval",
        days=1,
        id="expand_channels",
        replace_existing=True,
        max_instances=1,
        # Without an explicit first run, a daily job fires 24h after registration
        # and EVERY deploy resets that timer — so on a frequently-deployed service
        # it can starve. A near-future first run makes it fire each deploy too.
        next_run_time=datetime.now() + timedelta(minutes=4),
    )

    # Plan 8.12: English-first cleanup — deactivate tracked channels whose uploads
    # are predominantly non-English. Retroactive + ongoing counterpart to the
    # enrollment gate. Daily; zero quota (reads collected snapshots); reversible.
    scheduler.add_job(
        prune_non_english_channels,
        trigger="interval",
        days=1,
        id="prune_non_english",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now() + timedelta(minutes=3),  # first cleanup soon after deploy
    )

    # Plan 8.11: search-based discovery for STARVED niches (coverage-driven). The
    # mostPopular chart misses the mid-tail where breakouts are detectable; this
    # fills thin niches via English keyword search. Daily; ~12 search.list calls
    # (100 quota units each) — cheap on spare quota, grows the English set steadily.
    scheduler.add_job(
        discover_channels_search,
        trigger="interval",
        days=1,
        id="discover_channels_search",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now() + timedelta(minutes=7),  # fire each deploy (see expand note)
    )

    # Rebuild the lost training set from channels' upload history. Bounded
    # (~400 channels/run, ~2 quota units each) + idempotent, so it drains the
    # active set over ~2 weeks on spare quota without touching live collection.
    scheduler.add_job(
        backfill_channel_history,
        trigger="interval",
        hours=6,
        id="backfill_channel_history",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now() + timedelta(minutes=5),  # start the rebuild after deploy
    )


def main() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    # One-shot DB migration (only when MIGRATE_DB_TO is set): copies Supabase ->
    # Railway PG from inside the container, then continues to normal scheduling.
    # Remove the env var once it has completed. No-op otherwise.
    from src.tools.migrate_db import maybe_run_boot_migration
    maybe_run_boot_migration()

    scheduler = BlockingScheduler(
        job_defaults={"misfire_grace_time": 300, "coalesce": True},
        timezone="UTC",
    )
    register_jobs(scheduler)

    def _shutdown(signum, _frame):
        logger.info("scheduler.shutdown", signal=signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("scheduler.started", jobs=[j.id for j in scheduler.get_jobs()])
    scheduler.start()


if __name__ == "__main__":
    main()
