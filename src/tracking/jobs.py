"""Scheduled velocity-tracking jobs.

These are the periodic entry points the dedicated scheduler process runs to
rebuild the velocity time-series (the dataset that was lost). They mirror the
CLI ``check-new-videos`` / ``collect-snapshots`` commands but are import-safe,
self-contained (own session), and never raise — a failure logs and is retried
on the next tick rather than killing the scheduler.

Registered in :func:`src.scheduler.register_jobs`.

Cadence rationale: the earliest checkpoint window is ``1h`` with a 2h grace, so
snapshots must be collected at least every ~2h to avoid missing it. We discover
new uploads hourly and collect snapshots every 30 minutes.
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def discover_new_videos(max_channels: int = 200) -> dict:
    """Check tracked channels for new uploads and enroll them for tracking."""
    from src.config import get_settings
    from src.database.connection import get_session
    from src.tracking.video_tracker import VideoTracker
    from src.youtube.client import YouTubeClient
    from src.youtube.quota_store import get_today_usage

    try:
        # Quota reserve: discovery is the expensive, least time-critical job.
        # If today's persisted remaining quota is below the reserve, skip this
        # run so the cheap capture jobs (snapshots/channels/comments) keep their
        # headroom. Best-effort — a read failure must not block discovery.
        reserve = get_settings().youtube_quota_discovery_reserve
        try:
            with get_session() as session:
                remaining = get_today_usage(session)["total_remaining"]
            if remaining < reserve:
                logger.warning(
                    "velocity.discover_skipped_low_quota",
                    remaining=remaining,
                    reserve=reserve,
                )
                return {"skipped_low_quota": True, "remaining": remaining}
        except Exception as qe:  # observability must not gate collection
            logger.debug("velocity.discover_quota_check_failed", error=str(qe))

        client = YouTubeClient()
        with get_session() as session:
            tracker = VideoTracker(session, youtube_client=client)
            result = tracker.check_for_new_videos(max_channels=max_channels)
        logger.info(
            "velocity.discover_complete",
            channels=result.channels_checked,
            new_videos=result.new_videos_found,
            errors=result.errors,
        )
        return {
            "channels": result.channels_checked,
            "new_videos": result.new_videos_found,
            "errors": result.errors,
        }
    except Exception as e:  # never let a scheduled run crash the scheduler
        logger.warning("velocity.discover_failed", error=str(e))
        return {"error": str(e)}


def collect_velocity_snapshots(max_videos: int = 500) -> dict:
    """Sample in-window checkpoints for all videos currently being tracked."""
    from src.database.connection import get_session
    from src.tracking.video_tracker import VideoTracker
    from src.youtube.client import YouTubeClient

    try:
        client = YouTubeClient()
        with get_session() as session:
            tracker = VideoTracker(session, youtube_client=client)
            result = tracker.collect_snapshots(max_videos=max_videos)
        logger.info(
            "velocity.collect_complete",
            snapshots=result.snapshots_collected,
            errors=result.errors,
        )
        return {"snapshots": result.snapshots_collected, "errors": result.errors}
    except Exception as e:
        logger.warning("velocity.collect_failed", error=str(e))
        return {"error": str(e)}


def collect_channel_snapshots(max_channels: int = 6000) -> dict:
    """Phase 7.2: daily channel time-series (subs / total views / video count).

    Sub growth over time is irreplaceable (can't be backfilled) and is both a
    feature and the denominator for "views vs. the channel's own trajectory."
    One snapshot per channel per UTC day; ~1 quota unit / 50 channels.
    """
    from datetime import datetime

    from sqlalchemy import func

    from src.database.connection import get_session
    from src.database.models import ChannelSnapshot, TrackedChannel
    from src.youtube.client import YouTubeClient

    try:
        client = YouTubeClient()
        written = 0
        with get_session() as session:
            today = datetime.utcnow().date()
            done_today = {
                r[0] for r in session.query(ChannelSnapshot.channel_id)
                .filter(func.date(ChannelSnapshot.snapshot_at) == today).all()
            }
            channels = [
                c[0] for c in session.query(TrackedChannel.channel_id)
                .filter(TrackedChannel.is_active == True)  # noqa: E712
                .limit(max_channels).all()
                if c[0] not in done_today
            ]
            for i in range(0, len(channels), 50):
                try:
                    for ci in client.get_channel_details(channels[i:i + 50]):
                        session.add(ChannelSnapshot(
                            channel_id=ci.channel_id,
                            subscriber_count=ci.subscriber_count or 0,
                            total_views=ci.total_views or 0,
                            video_count=ci.video_count or 0,
                        ))
                        written += 1
                except Exception as e:
                    logger.warning("channel_snapshot.batch_failed", error=str(e))
                if client.get_quota_status()["total_remaining"] < 50:
                    logger.warning("channel_snapshot.low_quota_stop", written=written)
                    break
            session.commit()
        logger.info("channel_snapshots.complete", written=written)
        return {"written": written}
    except Exception as e:
        logger.warning("channel_snapshots.failed", error=str(e))
        return {"error": str(e)}


def archive_thumbnails(max_items: int = 2000) -> dict:
    """Phase 7.2: archive thumbnail image BYTES to R2 (URLs rotate/expire).

    Keyed by ``thumbnails/<video_id>/<sha1(url)[:12]>.jpg`` — content-addressed,
    so re-runs skip already-stored images (cheap HEAD) and a thumbnail *swap*
    (new URL) naturally creates a new object. Enables retroactive CLIP
    embeddings (6.1) and thumbnail-swap impact analysis (7.4).
    """
    import hashlib

    import boto3
    import requests
    from botocore.config import Config
    from sqlalchemy import distinct

    from src.config import get_settings
    from src.database.connection import get_session
    from src.database.models import VideoSnapshot

    # Inline R2 client (avoids importing the video_analysis package, which
    # eager-loads the audio/librosa stack).
    s = get_settings()
    if not all([s.r2_account_id, s.r2_access_key_id, s.r2_secret_access_key]):
        logger.info("thumbnail_archive.skipped_no_r2")
        return {"skipped_no_r2": True}

    try:
        r2 = boto3.client(
            "s3",
            endpoint_url=f"https://{s.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=s.r2_access_key_id,
            aws_secret_access_key=s.r2_secret_access_key,
            config=Config(signature_version="s3v4", retries={"max_attempts": 2}),
        )
        bucket = s.r2_bucket_name

        def _exists(key):
            try:
                r2.head_object(Bucket=bucket, Key=key)
                return True
            except Exception:
                return False

        with get_session() as session:
            pairs = session.query(
                distinct(VideoSnapshot.video_id), VideoSnapshot.thumbnail_url
            ).filter(VideoSnapshot.thumbnail_url.isnot(None)).limit(max_items * 3).all()
        archived = skipped = errors = 0
        seen: set[str] = set()
        for vid, url in pairs:
            if not url or not vid:
                continue
            key = f"thumbnails/{vid}/{hashlib.sha1(url.encode()).hexdigest()[:12]}.jpg"
            if key in seen:
                continue
            seen.add(key)
            try:
                if _exists(key):
                    skipped += 1
                    continue
                r = requests.get(url, timeout=10)
                if r.status_code == 200 and len(r.content) > 1000:
                    r2.put_object(Bucket=bucket, Key=key, Body=r.content,
                                  ContentType="image/jpeg")
                    archived += 1
                if archived >= max_items:
                    break
            except Exception as e:
                errors += 1
                logger.debug("thumbnail_archive.item_failed", video_id=vid, error=str(e))
        logger.info("thumbnail_archive.complete", archived=archived, skipped=skipped, errors=errors)
        return {"archived": archived, "skipped": skipped, "errors": errors}
    except Exception as e:
        logger.warning("thumbnail_archive.failed", error=str(e))
        return {"error": str(e)}


def collect_top_comments(max_videos: int = 1200, top_n: int = 30) -> dict:
    """Phase 7.2: capture top ~30 comments for recent tracked videos (past 24h).

    The early comment set is a viewer-intent / FAQ / next-video-idea signal and
    a leading indicator. One-time per video (skips videos that already have
    comments). Restricted to videos published in the last ~10 days so the
    sample reflects early reaction. ~1 quota unit per video. Caps widened to use
    spare quota (we run at ~4% of budget) for broader coverage of breakouts.
    """
    from datetime import datetime, timedelta

    from sqlalchemy.exc import IntegrityError

    from src.config import get_settings
    from src.database.connection import get_session
    from src.database.models import TrackedVideo, VideoComment
    from src.features.comment_analyzer import CommentFetcher

    try:
        s = get_settings()
        fetcher = CommentFetcher(api_key=s.youtube1 or s.youtube_api_key_1)
        written = videos_done = errors = 0
        with get_session() as session:
            cutoff = datetime.utcnow() - timedelta(days=10)
            have = {r[0] for r in session.query(VideoComment.video_id).distinct().all()}
            candidates = (
                session.query(TrackedVideo)
                .filter(TrackedVideo.checkpoint_24h == True,  # noqa: E712
                        TrackedVideo.published_at >= cutoff)
                .limit(max_videos * 2).all()
            )
            todo = [v for v in candidates if v.video_id not in have][:max_videos]
            for v in todo:
                try:
                    comments = fetcher.fetch_comments(v.video_id, max_results=top_n, order="relevance")
                    for c in comments:
                        pub = c.published_at.replace(tzinfo=None) if c.published_at else None
                        session.add(VideoComment(
                            video_id=v.video_id, comment_id=c.comment_id,
                            author_name=(c.author_name or "")[:255] or None,
                            author_channel_id=c.author_channel_id or None,
                            text=c.text or "", like_count=c.like_count or 0,
                            reply_count=c.reply_count or 0, published_at=pub,
                        ))
                    session.flush()
                    written += len(comments)
                    videos_done += 1
                except IntegrityError:
                    session.rollback()
                except Exception as e:
                    errors += 1
                    logger.debug("top_comments.video_failed", video_id=v.video_id, error=str(e))
            session.commit()
        logger.info("top_comments.complete", videos=videos_done, comments=written, errors=errors)
        return {"videos": videos_done, "comments": written, "errors": errors}
    except Exception as e:
        logger.warning("top_comments.failed", error=str(e))
        return {"error": str(e)}


def capture_video_heatmaps(max_videos: int = 60) -> dict:
    """Phase 8.1: capture Most-Replayed heatmaps for tracked videos past ~2 weeks.

    The public retention-shape proxy (true retention is owner-private). Zero API
    quota — watch-page fetches via yt-dlp, throttled + bounded per run. No-ops
    until the first tracked videos reach eligibility age (~Jun 21 for the
    collection started Jun 8).
    """
    from src.database.connection import get_session
    from src.tracking.heatmap_capture import capture_heatmaps

    try:
        with get_session() as session:
            result = capture_heatmaps(session, max_videos=max_videos)
        logger.info("heatmaps.complete", **result)
        return result
    except Exception as e:
        logger.warning("heatmaps.failed", error=str(e))
        return {"error": str(e)}


def compute_topic_clusters() -> dict:
    """Phase 8.2: cluster recent upload titles into topics (saturation index).

    Zero API quota — works entirely on collected snapshot titles. Embeds with
    MiniLM (already a dep), greedy cosine clustering, stores one batch per run.
    Feeds the timing advisor + reach/breakout features + 7.6 stratification.
    """
    from src.database.connection import get_session
    from src.features.topic_saturation import build_topic_clusters

    try:
        with get_session() as session:
            result = build_topic_clusters(session)
        logger.info("topics.complete", **result)
        return result
    except Exception as e:
        logger.warning("topics.failed", error=str(e))
        return {"error": str(e)}


def db_backup_and_archive() -> dict:
    """Nightly: full logical backup of the DB to R2, then archive old completed
    videos' snapshots out of Postgres (keeps the 5GB volume flat). Archive only
    runs if the backup succeeded; rows are deleted only after their archive
    object is uploaded and size-verified. See src/tools/db_backup.py."""
    from src.tools.db_backup import run_backup_and_archive

    try:
        result = run_backup_and_archive()
        logger.info("db_maintenance.complete", **{
            "backup_tables": result["backup"]["tables"],
            "archived": result["archive"].get("archived", 0),
        })
        return result
    except Exception as e:
        logger.warning("db_maintenance.failed", error=str(e)[:200])
        return {"error": str(e)}


def compute_timing_benchmarks() -> dict:
    """Daily: measured publish-hour / weekday hit rates (zero quota).

    Descriptive and correlational; replaces the fabricated optimal_upload_hour
    the old benchmarks endpoint served. See src/features/timing_insights.py."""
    from src.database.connection import get_session
    from src.features.timing_insights import compute_timing_benchmarks as _c

    try:
        with get_session() as session:
            result = _c(session)
        logger.info("timing_benchmarks.complete", **result)
        return result
    except Exception as e:
        logger.warning("timing_benchmarks.failed", error=str(e)[:200])
        return {"error": str(e)}


def compute_niche_benchmarks() -> dict:
    """Daily: recompute measured view-trajectory percentiles per niche/format.

    Pure description of collected snapshots (no model). Replaces the old
    /benchmarks endpoint that served invented constants. Zero API quota."""
    from src.database.connection import get_session
    from src.features.niche_benchmarks import compute_benchmarks

    try:
        with get_session() as session:
            result = compute_benchmarks(session)
        logger.info("niche_benchmarks.complete", **result)
        return result
    except Exception as e:
        logger.warning("niche_benchmarks.failed", error=str(e)[:200])
        return {"error": str(e)}


def db_capacity_guard() -> dict:
    """Hourly: watch Postgres volume usage; archive immediately if it's critical.

    Added after the 2026-07-17 silent disk-full crashed Postgres for 13 days --
    monitoring watched row counts, not bytes. See src/tools/db_backup.py."""
    from src.tools.db_backup import capacity_guard

    try:
        return capacity_guard()
    except Exception as e:
        logger.warning("db_capacity_guard.failed", error=str(e)[:200])
        return {"error": str(e)}


def pull_owner_analytics() -> dict:
    """Phase 3.2 (display half): pull real owner CTR + retention for connected
    channels (daily). Uses each user's own OAuth/analytics quota — not ours.
    Best-effort; a bad token never stops the batch."""
    from src.database.connection import get_session
    from src.features.owner_analytics import pull_owner_analytics as _pull

    try:
        with get_session() as session:
            result = _pull(session)
        logger.info("owner_analytics.complete", **result)
        return result
    except Exception as e:
        logger.warning("owner_analytics.failed", error=str(e))
        return {"error": str(e)}


def compute_topic_momentum() -> dict:
    """Phase 2.1: per-topic breakout density + trend (daily). Where audiences are
    rewarding content right now — the honest market-timing signal. Zero API quota
    (reads the topic-cluster batch + the live breakout feed)."""
    from src.database.connection import get_session
    from src.features.topic_saturation import compute_topic_momentum as _compute

    try:
        with get_session() as session:
            result = _compute(session)
        logger.info("topic_momentum.complete", **result)
        return result
    except Exception as e:
        logger.warning("topic_momentum.failed", error=str(e))
        return {"error": str(e)}


def recompute_emerging_formats() -> dict:
    """Format Radar: mine title formats from the live breakout window (daily).

    Zero API quota — works on already-collected breakout titles. Clusters them,
    induces template skeletons, and ranks by momentum/openness. See
    ``src/features/emerging_formats.py`` + ``docs/specs/emerging-formats.md``.
    """
    from src.database.connection import get_session
    from src.features.emerging_formats import compute_emerging_formats

    try:
        with get_session() as session:
            result = compute_emerging_formats(session)
        logger.info("formats.job.complete", **result)
        return result
    except Exception as e:
        logger.warning("formats.job.failed", error=str(e))
        return {"error": str(e)}


def compute_coverage() -> dict:
    """Per-niche coverage metric (daily): are we tracking enough, niche by niche?

    Zero API quota — derives each channel's niche from its videos' categories and
    counts breakouts/formats per niche. Flags starved niches for expansion. See
    ``src/features/niche_coverage.py`` + ``docs/specs/stratified-expansion.md``.
    """
    from src.database.connection import get_session
    from src.features.niche_coverage import compute_niche_coverage

    try:
        with get_session() as session:
            result = compute_niche_coverage(session)
        logger.info("coverage.job.complete", **result)
        return result
    except Exception as e:
        logger.warning("coverage.job.failed", error=str(e))
        return {"error": str(e)}


def enrich_channels(limit: int = 200) -> dict:
    """Backfill subscriber_count + size_tier for un-enriched channels (gradual).

    1 quota unit / 50 channels. Drains the backlog over many runs and keeps newly
    enrolled channels enriched; needed for the tier mix in the coverage metric.
    """
    from src.database.connection import get_session
    from src.features.niche_coverage import enrich_pending_channels
    from src.youtube.client import YouTubeClient

    try:
        client = YouTubeClient()
        with get_session() as session:
            result = enrich_pending_channels(session, client, limit=limit)
        logger.info("coverage.enrich.complete", **result)
        return result
    except Exception as e:
        logger.warning("coverage.enrich.failed", error=str(e))
        return {"error": str(e)}


def expand_tracked_channels(limit: int = 1500) -> dict:
    """Plan 8.11: weekly tracked-set growth from mostPopular charts.

    Enrolls that week's newly-trending English channels (the existing set is
    already subscribed/collected; this only ADDS). Capped per run so growth is
    steady, not spiky. ~72 quota units (6 regions × 12 categories). New channels
    get WebSub-subscribed by the next ``websub_renew`` tick.
    """
    from src.database.connection import get_session
    from src.tracking.channel_expansion import expand_tracked_set
    from src.youtube.client import YouTubeClient

    try:
        client = YouTubeClient()
        with get_session() as session:
            result = expand_tracked_set(session, client, limit=limit)
        logger.info("expand.complete", **result)
        return result
    except Exception as e:
        logger.warning("expand.failed", error=str(e))
        return {"error": str(e)}


def backfill_channel_history(max_channels: int = 400) -> dict:
    """Rebuild the lost training set from channels' upload history.

    Walks active English channels not yet backfilled, pulls recent uploads +
    final stats (~2 quota units/channel), and writes outlier-labelled
    ``BackfillVideo`` rows the model scripts can train on. Idempotent + bounded;
    drains the whole set over ~2 weeks on spare quota.
    """
    from src.database.connection import get_session
    from src.tracking.backfill import backfill_channel_history as _backfill
    from src.youtube.client import YouTubeClient

    try:
        client = YouTubeClient()
        with get_session() as session:
            result = _backfill(session, client, max_channels=max_channels)
        logger.info("backfill.job_complete", **result)
        return result
    except Exception as e:
        logger.warning("backfill.job_failed", error=str(e))
        return {"error": str(e)}


def discover_channels_search(max_queries: int = 12, limit: int = 1000) -> dict:
    """Plan 8.11: fill starved niches via English keyword search (search.list).

    Targeted mid-tail discovery the mostPopular chart misses — pointed only at
    niches NicheCoverage flags as thin, bounded to ``max_queries`` search calls
    (100 quota units each). Enrolls English channels not already tracked
    (``enrolled_via='search'``); new channels get WebSub-subscribed next tick.
    """
    from src.database.connection import get_session
    from src.tracking.channel_expansion import discover_channels_by_search
    from src.youtube.client import YouTubeClient

    try:
        client = YouTubeClient()
        with get_session() as session:
            result = discover_channels_by_search(
                session, client, max_queries=max_queries, limit=limit
            )
        logger.info("search_discovery.complete", **result)
        return result
    except Exception as e:
        logger.warning("search_discovery.failed", error=str(e))
        return {"error": str(e)}


def send_watchlist_alerts() -> dict:
    """Email users when a channel on their watchlist breaks out (deduped).

    Detects breakouts across the tracked set, fans them to watchers, sends one
    digest per user via the provider-pluggable sender (console until EMAIL_PROVIDER
    is set). Zero API quota (reads collected snapshots).
    """
    from src.database.connection import get_session
    from src.features.watchlist_alerts import send_watchlist_alerts as _send

    try:
        with get_session() as session:
            result = _send(session)
        logger.info("watchlist_alerts.complete", **result)
        return result
    except Exception as e:
        logger.warning("watchlist_alerts.failed", error=str(e))
        return {"error": str(e)}


def send_niche_digests() -> dict:
    """Weekly: email opted-in users a roundup of the week's biggest breakouts on
    their watchlist (ranked by durability). Zero API quota (reads snapshots);
    console-backed until EMAIL_PROVIDER is set, so no real mail goes out yet.
    """
    from src.database.connection import get_session
    from src.features.niche_digest import send_niche_digests as _send

    try:
        with get_session() as session:
            result = _send(session)
        logger.info("niche_digest.complete", **result)
        return result
    except Exception as e:
        logger.warning("niche_digest.failed", error=str(e))
        return {"error": str(e)}


def prune_non_english_channels() -> dict:
    """Plan 8.12: deactivate tracked channels whose uploads are mostly non-English.

    Retroactive + ongoing English-first cleanup (the enrollment gate only covers
    channels added after it shipped). Reversible — flips ``is_active=False``,
    never deletes. Zero API quota (reads already-collected snapshots).
    """
    from src.database.connection import get_session
    from src.tracking.channel_expansion import prune_non_english_channels as _prune

    try:
        with get_session() as session:
            result = _prune(session)
        logger.info("prune.complete", **result)
        return result
    except Exception as e:
        logger.warning("prune.failed", error=str(e))
        return {"error": str(e)}


def renew_websub_subscriptions() -> dict:
    """Plan 7.5: enroll/renew WebSub push subscriptions for tracked channels.

    Zero-quota upload notifications replace polling discovery (99.5% of our
    YouTube quota). No-ops until WEBSUB_CALLBACK_URL is configured. Bounded
    per run; full set enrolls in ~2 days at the default batch size.
    """
    from src.database.connection import get_session
    from src.tracking.websub import renew_due_subscriptions

    try:
        from src.config import get_settings

        with get_session() as session:
            result = renew_due_subscriptions(
                session, batch=get_settings().websub_subscribe_batch
            )
        logger.info("websub.renew_complete", **result)
        return result
    except Exception as e:
        logger.warning("websub.renew_failed", error=str(e))
        return {"error": str(e)}


def persist_quota_usage() -> dict:
    """Flush accumulated YouTube quota usage to the DB, log it, and alert if low.

    Quota is spent in memory across many short-lived ``QuotaManager`` instances;
    this drains the process-global accumulator into ``youtube_quota_usage`` so
    the per-day total survives restarts and is queryable (admin endpoint). Logs
    a ``quota.status`` line every run and a ``quota.alert`` warning when the
    remaining fraction drops below ``youtube_quota_alert_pct`` — the cue to cut
    discovery cadence before jobs actually starve.
    """
    from src.config import get_settings
    from src.database.connection import get_session
    from src.youtube.quota_store import (
        evaluate_quota_alert,
        flush_quota_usage,
        get_today_usage,
    )

    try:
        with get_session() as session:
            flushed = flush_quota_usage(session)
            status = get_today_usage(session)
        alert = evaluate_quota_alert(status, get_settings().youtube_quota_alert_pct)
        logger.info(
            "quota.status",
            date=status["date"],
            used=status["total_used"],
            remaining=status["total_remaining"],
            pct_remaining=status["pct_remaining"],
            keys_exhausted=status["keys_exhausted"],
            flushed=flushed["flushed"],
        )
        if alert:
            logger.warning("quota.alert", **alert)
        return {"flushed": flushed["flushed"], "status": status, "alert": alert}
    except Exception as e:
        logger.warning("quota.persist_failed", error=str(e))
        return {"error": str(e)}


def check_collection_health() -> dict:
    """Collection QA (7.6): log per-checkpoint window hit-rate and alert on drops.

    The irreplaceable failure mode is *silent* dataset erosion — quota
    exhaustion or a stalled scheduler making us sample late/never while every
    job still logs success. This measures the fraction of *eligible* checkpoint
    windows we actually captured and warns when a checkpoint's recent hit-rate
    falls below ``collection_hit_rate_alert``.
    """
    from src.config import get_settings
    from src.database.connection import get_session
    from src.tracking.collection_health import (
        evaluate_health_alert,
        get_collection_health,
        get_stream_anomalies,
    )

    try:
        with get_session() as session:
            summary = get_collection_health(session)
            anomalies = get_stream_anomalies(session)
        alerts = evaluate_health_alert(
            summary, get_settings().collection_hit_rate_alert
        )
        logger.info(
            "collection.health",
            videos=summary.get("videos_considered"),
            overall_hit_rate=summary.get("overall_hit_rate"),
            recent_overall_hit_rate=summary.get("recent_overall_hit_rate"),
            per_checkpoint={
                c["checkpoint"]: c["recent_hit_rate"] for c in summary["checkpoints"]
            },
            view_decrease_rate=anomalies.get("decrease_rate"),
        )
        if alerts:
            logger.warning("collection.health_alert", alerts=alerts)
        # A spike in view DECREASES (>2% of checkpoint pairs) = platform-wide
        # purge or a data bug (mislabeled checkpoints) — either way, look.
        rate = anomalies.get("decrease_rate")
        if rate is not None and rate > 0.02:
            logger.warning("collection.view_decrease_spike", **anomalies)
        return {"summary": summary, "alerts": alerts, "stream_anomalies": anomalies}
    except Exception as e:
        logger.warning("collection.health_failed", error=str(e))
        return {"error": str(e)}


def check_model_drift(min_pairs: int = 200) -> dict:
    """Phase 3.2: detect model/data drift from the live backtest harness.

    Compares current per-horizon MAPE (model if wired, else best baseline)
    against a stored reference (first known-good run) and logs warn/alert on
    degradation. The retrain *trigger* is data-gated; this is the detector.
    """
    import json
    from pathlib import Path

    from src.ml.drift import DriftReport, _current_metric, evaluate_backtest_drift

    ref_path = Path("data/ml/drift_reference.json")
    try:
        from scripts.backtest_predictions import backtest

        rows, _ = backtest(min_pairs=min_pairs)
        if not rows:
            logger.info("drift.no_data")
            return {"status": "no_data"}

        current = {
            r["horizon"]: _current_metric(r, "model_mape")
            for r in rows if _current_metric(r, "model_mape") is not None
        }
        if not ref_path.exists():
            ref_path.parent.mkdir(parents=True, exist_ok=True)
            ref_path.write_text(json.dumps(current, indent=1))
            logger.info("drift.reference_initialized", horizons=len(current))
            return {"status": "reference_initialized", "horizons": len(current)}

        reference = json.loads(ref_path.read_text())
        report = DriftReport(evaluate_backtest_drift(rows, reference))
        summary = report.summary()
        if report.alerts:
            logger.warning("drift.alert", **summary)
        elif report.warnings:
            logger.warning("drift.warn", **summary)
        else:
            logger.info("drift.ok", **summary)
        return {"status": "checked", **summary}
    except Exception as e:
        logger.warning("drift.failed", error=str(e))
        return {"error": str(e)}
