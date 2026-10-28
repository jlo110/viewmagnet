"""RQ-based durable job queue.

When ``REDIS_URL`` is set, jobs go to RQ and are processed by ``rq worker``.
Otherwise they run synchronously in-process (so tests + DEV_MODE still work).

Week 8 hardening:

* **Retry with backoff.** Every enqueue defaults to ``max=2`` retries
  with a [30s, 120s] backoff so transient failures (download
  timeout, ffmpeg OOM on a hot worker) heal themselves without a user
  having to click Retry. Permanent failures (bad spec, missing
  source) blow past the retries and land on the dead-letter queue.
* **Dead-letter queue.** Jobs that fail every retry are pushed onto
  ``viewmagnet:dlq`` for manual inspection — running ``python -m
  src.queue.client --dlq`` lists them. Keeps the live failure
  surface focused on actionable items.
* **Idempotency.** Each render job is keyed by ``(kind, render_id)``
  so a double-click in the UI (or a stale duplicate enqueue from a
  flaky worker fork) re-uses the running job id instead of starting
  a second one.
* **Healthcheck.** ``python -m src.queue.client --healthcheck`` exits
  non-zero when Redis is unreachable or the last successful job is
  older than the freshness threshold (default 10 min). Wires into
  docker-compose ``healthcheck`` so an unhealthy worker is restarted
  before a customer notices.
* **Optional Sentry hook.** ``SENTRY_DSN`` enables structured error
  reporting on job failures without coupling RQ to a Sentry import
  (the import is lazy + fail-open).

Usage:
    from src.queue import enqueue_job
    enqueue_job("src.features.distribution_hub:run_distribution_job", job_id)
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import structlog

from src.config import get_settings

# macOS-specific guard: when the parent (Python+ML deps loaded) forks a
# worker, Objective-C frameworks crash the child unless this is set. We
# export it as early as possible so any later subprocess/fork inherits it.
# See: https://github.com/rq/rq/issues/1418
if sys.platform == "darwin":
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

logger = structlog.get_logger(__name__)

_queue = None
_using_sync_fallback = False

# RQ keys for worker freshness + DLQ. Kept here so the healthcheck
# command and the worker process agree on the namespace.
_DLQ_NAME = "viewmagnet:dlq"
_LAST_JOB_KEY = "viewmagnet:worker:last_success_at"
# Per-job heartbeat key — refreshed every ~20s while a long render is in
# progress (TTL 60s so a crashed worker's heartbeat expires within a
# minute). The healthcheck treats EITHER a recent success OR a recent
# heartbeat as healthy, so a 30-minute project render doesn't trip the
# "stuck worker" detector and get the container restarted mid-encode.
_HEARTBEAT_KEY = "viewmagnet:worker:heartbeat_at"
_HEARTBEAT_INTERVAL_SECONDS = 20
_HEARTBEAT_TTL_SECONDS = 60
_HEALTH_MAX_AGE_SECONDS = 600  # 10 min — generous so idle workers stay healthy

# Default retry policy applied to every enqueue unless the caller
# opts out. Two retries with 30s + 120s backoff covers transient
# network blips + Redis hiccups without being aggressive enough to
# hammer a downstream that's actually down.
_DEFAULT_RETRY_MAX = 2
_DEFAULT_RETRY_INTERVALS = [30, 120]


def report_render_exception(
    exc: BaseException,
    *,
    user_id: Optional[int] = None,
    render_kind: Optional[str] = None,
    render_id: Optional[Any] = None,
    duration_elapsed_s: Optional[float] = None,
    **extra_tags: Any,
) -> None:
    """Forward a render-job exception to Sentry with structured tags.

    Public counterpart of the internal ``_sentry_capture`` — render
    code paths (``render_session`` / ``render_project`` worker
    failures) call this so the resulting Sentry issue is filterable
    by ``user_id``, ``render_kind``, ``render_id``, and
    ``duration_elapsed_s`` without scraping payloads.

    No-op when ``SENTRY_DSN`` is unset. Lazy-imports ``sentry_sdk``
    so a deployment without Sentry stays first-pip-install green.
    Never raises — telemetry is best-effort by contract.
    """
    _sentry_capture(
        exc,
        user_id=user_id,
        render_kind=render_kind,
        render_id=render_id,
        duration_elapsed_s=duration_elapsed_s,
        **extra_tags,
    )


def add_render_breadcrumb(
    *,
    category: str,
    message: str,
    level: str = "info",
    data: Optional[dict[str, Any]] = None,
) -> None:
    """Drop a structured breadcrumb into the Sentry scope.

    Used by lifecycle moments that don't capture exceptions themselves
    (cancel, requeue, soft-cap nudge) so that *if* the render later
    fails and lands a Sentry issue, the trail shows what the user did
    leading up to the failure. Without this, a cancel-then-retry
    sequence looks like an unexplained reset in the Sentry timeline.

    ``category`` is a free-form tag (``render.cancel``, ``render.retry``)
    so Sentry's UI can collapse / filter by it. ``data`` should be a
    flat dict of small scalars — Sentry truncates large breadcrumb
    payloads silently.

    No-op when Sentry isn't configured. Never raises — breadcrumbs are
    pure observability sugar and must not break the request that
    triggered them.
    """
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk

        # Drop ``None`` values so the breadcrumb payload stays tight.
        clean = (
            {k: v for k, v in data.items() if v is not None}
            if data
            else None
        )
        sentry_sdk.add_breadcrumb(
            category=category,
            message=message,
            level=level,
            data=clean,
        )
    except Exception:  # noqa: BLE001
        # Never let a breadcrumb crash the caller. Swallow silently.
        pass


def get_queue_depth() -> Optional[dict[str, int]]:
    """Snapshot how many jobs are sitting in the worker queue.

    Returns a dict shaped ``{"queued": N, "started": M, "deferred": K,
    "scheduled": S}`` or ``None`` when Redis isn't configured / RQ
    isn't reachable. Callers (e.g. the budget pre-check) use this to
    decide whether to surface a "we're slammed" surge banner so users
    don't blame us for a queue we already know about.

    Cheap — RQ exposes counts via Redis ``LLEN`` on its registries, so
    this is O(1) per registry regardless of how many jobs are
    enqueued. Best-effort: returns ``None`` rather than raising on
    any error path (we'd rather degrade the surge banner than 500 the
    render endpoint)."""
    queue = get_queue()
    if queue is None:
        return None
    try:
        from rq.registry import (
            DeferredJobRegistry,
            ScheduledJobRegistry,
            StartedJobRegistry,
        )

        started = StartedJobRegistry(queue=queue)
        deferred = DeferredJobRegistry(queue=queue)
        scheduled = ScheduledJobRegistry(queue=queue)
        return {
            "queued": int(queue.count),
            "started": int(started.count),
            "deferred": int(deferred.count),
            "scheduled": int(scheduled.count),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("queue.depth_probe_failed", error=str(exc))
        return None


def _sentry_capture(exc: BaseException, **tags: Any) -> None:
    """Forward an exception to Sentry if configured. No-op otherwise.

    Lazy-imports ``sentry_sdk`` so a project without Sentry installed
    or configured stays first-pip-install green. Tags become indexable
    fields (user_id, render_kind, etc.) so the issue UI lets us
    filter without grepping payloads.
    """
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for k, v in tags.items():
                if v is not None:
                    scope.set_tag(k, str(v))
            sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001
        # Sentry must never break the worker. Swallow silently.
        pass


def _import_callable(dotted: str) -> Callable:
    """Resolve a ``module.path:callable`` (or ``module.path.callable``) reference."""
    if ":" in dotted:
        module_path, attr = dotted.split(":", 1)
    else:
        module_path, _, attr = dotted.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


def get_queue():
    """Return the singleton RQ Queue (or ``None`` when running synchronously)."""
    global _queue, _using_sync_fallback
    if _queue is not None:
        return _queue
    
    settings = get_settings()
    if not settings.redis_url:
        logger.info("queue.sync_fallback", message="REDIS_URL not set; running jobs synchronously")
        _using_sync_fallback = True
        return None
    
    try:
        from redis import Redis
        from rq import Queue
        connection = Redis.from_url(settings.redis_url)
        _queue = Queue("viewmagnet", connection=connection)
        logger.info("queue.connected", url=settings.redis_url.split("@")[-1])
        return _queue
    except ImportError:
        logger.warning("queue.rq_not_installed", message="rq package not installed; jobs will run synchronously")
        _using_sync_fallback = True
        return None
    except Exception as e:
        logger.error("queue.connect_failed", error=str(e))
        _using_sync_fallback = True
        return None


def cancel_job(job_id: str) -> bool:
    """Cancel a queued or in-progress RQ job by id.

    Returns ``True`` when a job was found and cancellation was sent.
    For jobs that are merely *queued* this removes them from the
    queue; for *started* jobs RQ asks the worker to stop after the
    current FFmpeg call returns (we don't kill subprocesses
    mid-encode, that'd leak temp files).

    Best-effort across all failure modes — no Redis, no such job,
    Redis errors — return ``False`` and let the caller decide
    whether to surface the failure. We never raise."""
    queue = get_queue()
    if queue is None:
        return False
    try:
        from rq.job import Job
        from rq.command import send_stop_job_command
        job = Job.fetch(job_id, connection=queue.connection)
        status = job.get_status()
        if status in ("queued", "deferred", "scheduled"):
            job.cancel()
            return True
        if status == "started":
            try:
                send_stop_job_command(queue.connection, job_id)
                return True
            except Exception as exc:  # noqa: BLE001
                # Older RQ versions lack send_stop_job_command — fall
                # back to ``job.cancel`` which at least flags the job
                # so the next worker tick won't re-attempt the retry.
                logger.warning(
                    "queue.cancel_stop_failed", job_id=job_id, error=str(exc)
                )
                job.cancel()
                return True
        # Terminal — nothing to cancel.
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("queue.cancel_failed", job_id=job_id, error=str(exc))
        return False


def enqueue_job(
    job_function: str,
    *args: Any,
    job_timeout: int = 600,
    job_id: Optional[str] = None,
    retry_max: Optional[int] = None,
    retry_intervals: Optional[list[int]] = None,
    **kwargs: Any,
) -> Optional[str]:
    """Enqueue a function by dotted path. Returns RQ job id (or None for sync).

    ``job_function`` may be ``module.path:function`` or ``module.path.function``.

    Week 8: every job ships with a Retry policy by default
    (``max=2``, intervals ``[30s, 120s]``) so transient failures heal
    themselves. Callers can opt out by passing ``retry_max=0`` (for
    jobs where retries would be incorrect — e.g. webhooks with side
    effects). Permanent failures bubble through to the dead-letter
    queue (see :func:`run_worker`).

    Idempotency: when ``job_id`` is provided and a job with that id is
    already in any RQ status (queued/started/deferred), this returns
    the existing id instead of enqueueing a duplicate. Callers that
    want strict double-click protection should pass a deterministic
    id like ``f"render-project-{project_id}"``.
    """
    queue = get_queue()
    if queue is None:
        # Synchronous fallback -- run inline so dev/tests work without Redis.
        func = _import_callable(job_function)
        try:
            func(*args, **kwargs)
            return None
        except Exception as e:
            logger.error("queue.sync_job_failed", job=job_function, error=str(e))
            # No Sentry in sync mode either — let the caller's error
            # handler shape the response.
            raise

    func = _import_callable(job_function)

    # Idempotent enqueue when a deterministic id is supplied. RQ
    # raises NoSuchJobError when the id isn't present, so we treat
    # that as "go ahead and enqueue".
    if job_id is not None:
        try:
            from rq.job import Job
            existing = Job.fetch(job_id, connection=queue.connection)
            if existing.get_status() in (
                "queued", "started", "deferred", "scheduled",
            ):
                logger.info(
                    "queue.enqueue_dedup",
                    job=job_function,
                    job_id=job_id,
                    existing_status=existing.get_status(),
                )
                return existing.id
        except Exception:  # noqa: BLE001
            # Job doesn't exist → continue to enqueue normally.
            pass

    retry_kwargs: dict[str, Any] = {}
    effective_max = (
        retry_max if retry_max is not None else _DEFAULT_RETRY_MAX
    )
    if effective_max > 0:
        try:
            from rq import Retry
            retry_kwargs["retry"] = Retry(
                max=effective_max,
                interval=retry_intervals or _DEFAULT_RETRY_INTERVALS,
            )
        except ImportError:
            # Older RQ versions without Retry — silently skip rather
            # than fail the enqueue. Callers can still retry manually.
            pass

    job = queue.enqueue(
        func,
        *args,
        job_timeout=job_timeout,
        job_id=job_id,
        **retry_kwargs,
        **kwargs,
    )
    logger.info(
        "queue.enqueued",
        job=job_function,
        job_id=job.id,
        retries=effective_max,
    )
    return job.id


def _mark_worker_healthy(connection) -> None:
    """Stamp a Redis key with the current timestamp so the healthcheck
    command can verify the worker is making progress. Called from
    inside the RQ exception handler chain on every successful job."""
    try:
        connection.set(_LAST_JOB_KEY, datetime.utcnow().isoformat())
    except Exception:  # noqa: BLE001
        # Health stamp is best-effort; never fail a job because of it.
        pass


def _heartbeat(connection) -> None:
    """Refresh the per-job heartbeat key with a short TTL.

    Called on a background thread while a render is in flight so the
    healthcheck can distinguish a long-but-progressing render from a
    truly stuck worker. The 60s TTL means a crashed worker's heartbeat
    expires before the next healthcheck probe — no false-healthy reads
    after the worker dies."""
    try:
        connection.set(
            _HEARTBEAT_KEY,
            datetime.utcnow().isoformat(),
            ex=_HEARTBEAT_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001
        pass


def _retry_telemetry(connection, job, exc_type, exc_value, traceback) -> bool:  # noqa: ARG001
    """Pre-DLQ exception handler — fires ``render.retried`` when RQ
    is going to schedule another attempt.

    Sits earlier in the ``exception_handlers`` chain than
    :func:`_dlq_push` so we always observe the retry first. Returns
    ``True`` so RQ keeps invoking the rest of the chain (it stops on
    ``False`` returns).
    """
    try:
        will_retry = bool(getattr(job, "should_retry", False))
        if not will_retry:
            return True
        func = getattr(job, "func_name", None) or ""
        render_kind: Optional[str] = None
        if "render_project" in func:
            render_kind = "project"
        elif "render_session" in func:
            render_kind = "session"
        args = list(getattr(job, "args", []) or [])
        render_id = args[0] if args else None
        # ``retries_left`` is set BEFORE the retry decrement, so the
        # 1-indexed attempt that just failed is ``max - left + 1``.
        max_retries = int(
            getattr(getattr(job, "retry", None), "max", 0) or 0
        )
        retries_left = int(getattr(job, "retries_left", 0) or 0)
        attempt = max(1, max_retries - retries_left + 1)
        from src.queue.telemetry import record_render_retried
        record_render_retried(
            user_id=None,  # cheap to look up but skipped — retry-rate by user is rare
            render_kind=render_kind,
            render_id=render_id,
            attempt=attempt,
            error=str(exc_value)[:500],
            error_type=exc_type.__name__ if exc_type else None,
        )
    except Exception:  # noqa: BLE001
        pass
    return True


def _dlq_push(connection, job, exc_type, exc_value, traceback) -> bool:  # noqa: ARG001
    """Final RQ exception handler — push the failed job onto the
    dead-letter queue so it survives RQ's failed-job-ttl expiry.

    Returns ``True`` to mark the failure handled (it still ends up in
    RQ's failed registry; the DLQ is an additional durable record).
    Mirrors the standard RQ pattern: a list of dicts the operator
    can pop + inspect with ``rq info`` or our ``--dlq`` command.
    """
    try:
        import json
        payload = {
            "job_id": getattr(job, "id", None),
            "func_name": getattr(job, "func_name", None),
            "args": list(getattr(job, "args", []) or []),
            "kwargs": dict(getattr(job, "kwargs", {}) or {}),
            "error": str(exc_value),
            "error_type": exc_type.__name__ if exc_type else None,
            "failed_at": datetime.utcnow().isoformat(),
        }
        connection.lpush(_DLQ_NAME, json.dumps(payload))
        # Cap DLQ at 1000 entries so it doesn't grow unbounded — old
        # entries naturally get evicted as new ones arrive.
        connection.ltrim(_DLQ_NAME, 0, 999)
        logger.warning(
            "queue.dlq_push",
            job_id=payload["job_id"],
            func=payload["func_name"],
            error_type=payload["error_type"],
        )

        # Recover the render context (kind, render_id, owning user)
        # from the job's args so BOTH the Sentry tags AND the
        # ``render.dlq`` telemetry event carry it. Render jobs are
        # dispatched as ``func(session_id_or_project_id)`` so the
        # first arg is the render id; the func name disambiguates
        # session vs project. Missing data → ``None`` (don't fail).
        func = payload.get("func_name") or ""
        render_kind: Optional[str] = None
        if "render_project" in func:
            render_kind = "project"
        elif "render_session" in func:
            render_kind = "session"
        render_id: Optional[Any] = None
        args = payload.get("args") or []
        if args:
            render_id = args[0]
        user_id: Optional[int] = None
        if render_kind and render_id is not None:
            try:
                from src.database.connection import get_session
                from src.database.models import EditSession, StudioProject

                with get_session() as db:
                    if render_kind == "session":
                        row = db.get(EditSession, int(render_id))
                    else:
                        row = db.get(StudioProject, int(render_id))
                    if row is not None:
                        user_id = row.user_id
            except Exception:  # noqa: BLE001
                pass

        # Sentry capture: with the render context inlined as tags
        # the issue page in Sentry filters cleanly by tenant /
        # render kind without having to grep the JSON payload.
        _sentry_capture(
            exc_value,
            job_id=payload["job_id"],
            func=payload["func_name"],
            error_type=payload["error_type"],
            user_id=user_id,
            render_kind=render_kind,
            render_id=render_id,
        )

        try:
            from src.queue.telemetry import record_render_dlq
            record_render_dlq(
                user_id=user_id,
                render_kind=render_kind,
                render_id=render_id,
                job_id=payload.get("job_id"),
                func_name=payload.get("func_name"),
                error=payload.get("error") or "",
                error_type=payload.get("error_type"),
            )
        except Exception:  # noqa: BLE001
            # Telemetry is best-effort; the DLQ + Sentry paths above
            # already captured the failure.
            pass
    except Exception as exc:  # noqa: BLE001
        # DLQ write itself failed — log but don't suppress the RQ
        # default failed-registry path.
        logger.warning("queue.dlq_push_failed", error=str(exc))
    # Returning True swallows the default RQ failure handler (which is
    # fine — the failed-registry entry already exists). Returning
    # False would re-raise.
    return True


def _success_callback(job, connection, *_args, **_kwargs) -> None:  # noqa: ARG001
    """RQ ``success_callback`` — stamps the freshness key so the
    healthcheck can tell the difference between an idle worker (Redis
    fine, no recent jobs) and a stuck worker (Redis fine, jobs in
    queue but never completing)."""
    _mark_worker_healthy(connection)


def run_worker() -> None:
    """Entry-point for the RQ worker process (``python -m src.queue.client``).

    On macOS we use ``SimpleWorker`` which runs jobs in-process (no fork).
    Forking with mediapipe/OpenCV/YOLO already loaded crashes the child with
    SIGABRT 6 even with ``OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`` set,
    because some Objective-C frameworks initialize on first use and don't
    respect the flag once they've started in the parent.
    Linux/CI keeps the default forking ``Worker`` for parallelism + crash
    isolation between jobs.

    Week 8: the worker now installs:
      * a success callback that stamps a "last successful job at" key
        (the healthcheck reads it), and
      * a final exception handler that pushes the failed job onto the
        DLQ list AND fires the Sentry hook (when configured) before
        RQ writes its standard failed-registry entry.
    """
    queue = get_queue()
    if queue is None:
        raise RuntimeError("REDIS_URL must be set to run the queue worker")

    worker_kwargs: dict[str, Any] = {
        "connection": queue.connection,
        # Order matters: ``_retry_telemetry`` runs first so a job
        # that's going to be retried emits ``render.retried`` BEFORE
        # ``_dlq_push`` would have considered it final. The DLQ push
        # itself short-circuits internally when the job will retry,
        # so chaining them is safe.
        "exception_handlers": [_retry_telemetry, _dlq_push],
    }

    if sys.platform == "darwin":
        from rq import SimpleWorker
        worker = SimpleWorker([queue], **worker_kwargs)
        logger.info("queue.worker_started", mode="SimpleWorker (no-fork, macOS)")
    else:
        from rq import Worker
        worker = Worker([queue], **worker_kwargs)
        logger.info("queue.worker_started", mode="Worker (forking)")

    # Stamp the freshness key on boot so an idle-but-just-started
    # worker reports healthy immediately (rather than failing the
    # first healthcheck because no job has run yet).
    _mark_worker_healthy(queue.connection)

    # Background heartbeat thread — keeps ``_HEARTBEAT_KEY`` warm
    # every ~20s (TTL 60s) so a 30-minute project render doesn't
    # look like a stuck worker to the healthcheck. The thread is a
    # daemon so it dies when the main worker process exits.
    import threading
    stop_heartbeat = threading.Event()

    def _heartbeat_loop() -> None:
        # Stamp once immediately so the first healthcheck after boot
        # sees a fresh heartbeat without waiting the full interval.
        _heartbeat(queue.connection)
        while not stop_heartbeat.wait(_HEARTBEAT_INTERVAL_SECONDS):
            _heartbeat(queue.connection)

    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop, name="rq-heartbeat", daemon=True
    )
    heartbeat_thread.start()

    # ``success_callback`` on Job is a per-job hook; we wire it via a
    # monkey-patch on the worker's perform_job so the stamp happens
    # after every successful run without modifying every enqueue site.
    original_perform = worker.perform_job

    def _stamp_on_success(*args: Any, **kwargs: Any) -> Any:
        ok = original_perform(*args, **kwargs)
        if ok:
            _mark_worker_healthy(queue.connection)
        return ok

    worker.perform_job = _stamp_on_success  # type: ignore[method-assign]

    try:
        worker.work(with_scheduler=False)
    finally:
        stop_heartbeat.set()


def run_healthcheck() -> int:
    """``python -m src.queue.client --healthcheck`` — exit non-zero
    when the worker looks unhealthy.

    Two failure modes:

    1. Redis unreachable → exit 1 (the worker can't possibly be doing
       work without Redis).
    2. No recent successful job AND no recent heartbeat AND queue
       depth > 0 → exit 2 (the worker is alive but stuck — there's
       work waiting, nothing is consuming it, and no one is even
       checking in).

    Crucially, a long-running render keeps the worker "healthy" via
    the per-job heartbeat (refreshed every 20s, TTL 60s), so a 30-min
    project render doesn't trip the healthcheck mid-encode and get
    docker-compose to restart the container.

    Idle workers (queue empty AND no recent job) are considered
    healthy — that's the steady state for off-hours. Exits 0.
    """
    settings = get_settings()
    if not settings.redis_url:
        print("UNHEALTHY: REDIS_URL not configured")
        return 1
    try:
        from redis import Redis
        conn = Redis.from_url(settings.redis_url)
        conn.ping()
    except Exception as exc:  # noqa: BLE001
        print(f"UNHEALTHY: redis unreachable ({exc})")
        return 1

    try:
        from rq import Queue
        queue = Queue("viewmagnet", connection=conn)
        queue_depth = queue.count
    except Exception as exc:  # noqa: BLE001
        print(f"UNHEALTHY: queue unreadable ({exc})")
        return 1

    raw_ts = conn.get(_LAST_JOB_KEY)
    last_success_age: Optional[float] = None
    if raw_ts is not None:
        last = datetime.fromisoformat(
            raw_ts.decode() if isinstance(raw_ts, bytes) else raw_ts
        )
        last_success_age = (datetime.utcnow() - last).total_seconds()

    # The heartbeat key has a 60s TTL — if Redis returns a value, the
    # worker is alive RIGHT NOW (or died <60s ago). Only need to check
    # presence, not age.
    has_recent_heartbeat = conn.exists(_HEARTBEAT_KEY) > 0

    if last_success_age is None and not has_recent_heartbeat:
        if queue_depth > 0:
            print(
                f"UNHEALTHY: no successful jobs, no heartbeat, "
                f"{queue_depth} waiting"
            )
            return 2
        print("HEALTHY: idle (no jobs run yet, queue empty)")
        return 0

    stale_success = (
        last_success_age is not None
        and last_success_age > _HEALTH_MAX_AGE_SECONDS
    )
    if stale_success and not has_recent_heartbeat and queue_depth > 0:
        print(
            f"UNHEALTHY: last success {int(last_success_age)}s ago, "
            f"no heartbeat, {queue_depth} jobs waiting"
        )
        return 2

    heartbeat_note = "with heartbeat" if has_recent_heartbeat else "no heartbeat"
    age_note = (
        f"last success {int(last_success_age)}s ago"
        if last_success_age is not None
        else "no success yet"
    )
    print(
        f"HEALTHY: {age_note}, {heartbeat_note}, queue depth {queue_depth}"
    )
    return 0


_DLQ_MAX_AGE_DAYS = 30


def prune_dlq(max_age_days: int = _DLQ_MAX_AGE_DAYS) -> int:
    """Drop DLQ entries older than ``max_age_days``.

    The DLQ already self-trims at 1000 entries via ``ltrim`` on every
    push, but an instance with low failure volume can still hoard
    months-old payloads under that cap. This sweeps anything past the
    retention window so the operator UI doesn't surface noise from
    last quarter's outage.

    Returns the number of entries pruned. Safe to call repeatedly;
    a no-op when the DLQ is empty or Redis is unreachable.
    """
    settings = get_settings()
    if not settings.redis_url:
        return 0
    try:
        from redis import Redis
        import json as _json

        conn = Redis.from_url(settings.redis_url)
        raw = conn.lrange(_DLQ_NAME, 0, -1)
        if not raw:
            return 0
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        keep: list[bytes] = []
        dropped = 0
        for item in raw:
            try:
                entry = _json.loads(item)
                failed_at = entry.get("failed_at")
                if not failed_at:
                    keep.append(item)
                    continue
                ts = datetime.fromisoformat(failed_at)
                if ts < cutoff:
                    dropped += 1
                    continue
                keep.append(item)
            except Exception:  # noqa: BLE001
                # Unparseable rows stay — operator can inspect and
                # remove manually rather than have us silently nuke
                # data we don't recognize.
                keep.append(item)
        if dropped == 0:
            return 0
        # Replace the list atomically: rename to a temp key so a
        # concurrent push isn't lost, rewrite from ``keep``, then
        # rename back over.
        tmp_key = f"{_DLQ_NAME}:rewrite"
        conn.delete(tmp_key)
        if keep:
            # lpush in reverse so LRANGE order is preserved (newest
            # first, matching ``_dlq_push`` insert order).
            for entry in reversed(keep):
                conn.lpush(tmp_key, entry)
        # Single atomic rename so a concurrent reader never sees an
        # empty list.
        conn.rename(tmp_key, _DLQ_NAME) if conn.exists(tmp_key) else conn.delete(_DLQ_NAME)
        logger.info(
            "queue.dlq_pruned",
            dropped=dropped,
            kept=len(keep),
            max_age_days=max_age_days,
        )
        return dropped
    except Exception as exc:  # noqa: BLE001
        logger.warning("queue.dlq_prune_failed", error=str(exc))
        return 0


def show_dlq(limit: int = 20) -> int:
    """``python -m src.queue.client --dlq`` — print the most recent
    dead-letter entries so operators can decide whether to re-enqueue
    or delete them."""
    settings = get_settings()
    if not settings.redis_url:
        print("REDIS_URL not configured; no DLQ to read.")
        return 1
    try:
        from redis import Redis
        import json as _json
        conn = Redis.from_url(settings.redis_url)
        raw = conn.lrange(_DLQ_NAME, 0, limit - 1)
    except Exception as exc:  # noqa: BLE001
        print(f"DLQ read failed: {exc}")
        return 1

    if not raw:
        print("DLQ is empty.")
        return 0

    print(f"DLQ — most recent {len(raw)} failures:\n")
    for item in raw:
        try:
            entry = _json.loads(item)
            print(
                f"  [{entry.get('failed_at')}] {entry.get('func_name')} "
                f"(job_id={entry.get('job_id')}) — "
                f"{entry.get('error_type')}: {entry.get('error', '')[:120]}"
            )
        except Exception:  # noqa: BLE001
            print(f"  (unparseable) {item!r}")
    return 0


def _cli() -> int:
    """Parse argv and dispatch to worker / healthcheck / dlq.

    Default (no flags) runs the worker, matching the legacy
    ``python -m src.queue.client`` behavior used in docker-compose.
    """
    parser = argparse.ArgumentParser(prog="src.queue.client")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Print queue health and exit non-zero when unhealthy.",
    )
    parser.add_argument(
        "--dlq",
        action="store_true",
        help="Print the most recent dead-letter queue entries and exit.",
    )
    parser.add_argument(
        "--dlq-limit",
        type=int,
        default=20,
        help="Number of DLQ entries to show (with --dlq). Default 20.",
    )
    parser.add_argument(
        "--prune-dlq",
        action="store_true",
        help=(
            "Prune DLQ entries older than --dlq-age days (default "
            f"{_DLQ_MAX_AGE_DAYS}) and exit."
        ),
    )
    parser.add_argument(
        "--dlq-age",
        type=int,
        default=_DLQ_MAX_AGE_DAYS,
        help="Age (in days) for --prune-dlq retention. Default 30.",
    )
    args = parser.parse_args()
    if args.healthcheck:
        return run_healthcheck()
    if args.dlq:
        return show_dlq(limit=args.dlq_limit)
    if args.prune_dlq:
        n = prune_dlq(max_age_days=args.dlq_age)
        print(f"Pruned {n} DLQ entries older than {args.dlq_age} days.")
        return 0
    # Opportunistic prune on worker boot so a long-running deployment
    # doesn't accumulate stale entries that the operator might mistake
    # for fresh failures.
    try:
        prune_dlq()
    except Exception:  # noqa: BLE001
        pass
    run_worker()
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
