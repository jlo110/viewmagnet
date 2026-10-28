"""Tests for Week 8 queue hardening — retry policy, idempotent enqueue,
DLQ push, healthcheck CLI.

The queue's sync fallback (no ``REDIS_URL``) handles the unit-test
environment fine for retry / idempotency by exercising the code paths
that don't actually need Redis. The DLQ + healthcheck functions are
tested in isolation with mocked Redis connections so they don't
require a live broker.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


class TestEnqueueRetryDefault:
    """``enqueue_job`` should attach a Retry policy by default."""

    def test_default_retry_kwargs_passed_to_rq(self):
        """When RQ is available, ``enqueue_job`` constructs a ``Retry``
        with the default max + intervals and forwards it to
        ``queue.enqueue``. Patching at the module level lets us verify
        the keyword without running an actual job."""
        from src.queue import client as queue_client

        fake_job = MagicMock(id="job-123")
        fake_queue = MagicMock()
        fake_queue.enqueue.return_value = fake_job
        fake_queue.connection = MagicMock()

        with patch.object(queue_client, "get_queue", return_value=fake_queue):
            with patch.object(
                queue_client,
                "_import_callable",
                return_value=lambda *a, **k: None,
            ):
                returned_id = queue_client.enqueue_job(
                    "dummy.module:fn", 42, job_id="render-session-42"
                )
        assert returned_id == "job-123"
        kwargs = fake_queue.enqueue.call_args.kwargs
        # Retry kwarg must be present, with our defaults.
        assert "retry" in kwargs
        assert kwargs["retry"].max == queue_client._DEFAULT_RETRY_MAX
        assert kwargs["retry"].intervals == queue_client._DEFAULT_RETRY_INTERVALS
        # Deterministic id flows through (Week 8 idempotency contract).
        assert kwargs["job_id"] == "render-session-42"

    def test_retry_max_zero_disables_retries(self):
        """Callers can opt out by passing ``retry_max=0`` — useful for
        side-effectful jobs where retry would double-fire."""
        from src.queue import client as queue_client

        fake_job = MagicMock(id="job-noretry")
        fake_queue = MagicMock()
        fake_queue.enqueue.return_value = fake_job
        fake_queue.connection = MagicMock()

        with patch.object(queue_client, "get_queue", return_value=fake_queue):
            with patch.object(
                queue_client,
                "_import_callable",
                return_value=lambda *a, **k: None,
            ):
                queue_client.enqueue_job(
                    "dummy.module:fn", retry_max=0
                )
        kwargs = fake_queue.enqueue.call_args.kwargs
        # No Retry → kwarg is absent so RQ uses no-retry default.
        assert "retry" not in kwargs


class TestIdempotentEnqueue:
    """Enqueue with the same deterministic ``job_id`` should return the
    existing job rather than queueing a duplicate."""

    def test_returns_existing_when_already_queued(self):
        from src.queue import client as queue_client

        fake_queue = MagicMock()
        fake_queue.connection = MagicMock()
        # Force enqueue to never be called — if it is, the test fails.
        fake_queue.enqueue.side_effect = AssertionError("enqueue was called")

        existing_job = MagicMock(id="dedupe-id")
        existing_job.get_status.return_value = "started"
        with patch.object(queue_client, "get_queue", return_value=fake_queue):
            with patch.object(
                queue_client,
                "_import_callable",
                return_value=lambda *a, **k: None,
            ):
                with patch("rq.job.Job.fetch", return_value=existing_job):
                    returned = queue_client.enqueue_job(
                        "dummy.module:fn", job_id="dedupe-id"
                    )
        assert returned == "dedupe-id"
        fake_queue.enqueue.assert_not_called()


class TestDLQPush:
    """The DLQ exception handler should JSON-encode the failure into
    ``viewmagnet:dlq`` and trim to 1000 entries."""

    def test_dlq_push_writes_structured_payload(self):
        from src.queue import client as queue_client

        conn = MagicMock()
        job = MagicMock(
            id="fail-id",
            func_name="src.x:run",
            args=[1, 2],
            kwargs={"k": "v"},
        )
        handled = queue_client._dlq_push(
            conn, job, ValueError, ValueError("nope"), None
        )
        assert handled is True
        conn.lpush.assert_called_once()
        # Cap-to-1000 trim must follow the push.
        conn.ltrim.assert_called_once_with(queue_client._DLQ_NAME, 0, 999)
        # Payload is JSON with the expected fields.
        pushed = conn.lpush.call_args.args[1]
        entry = json.loads(pushed)
        assert entry["job_id"] == "fail-id"
        assert entry["func_name"] == "src.x:run"
        assert entry["args"] == [1, 2]
        assert entry["kwargs"] == {"k": "v"}
        assert entry["error"] == "nope"
        assert entry["error_type"] == "ValueError"


class TestHealthcheck:
    """``run_healthcheck`` should return:
        * 1 when Redis is unreachable
        * 2 when the worker is stale + no heartbeat + queue has work
        * 0 when idle, making progress, OR mid-long-render (heartbeat fresh)."""

    def test_returns_2_when_stale_with_pending_work_and_no_heartbeat(self):
        from src.queue import client as queue_client

        stale_ts = (
            datetime.utcnow()
            - timedelta(seconds=queue_client._HEALTH_MAX_AGE_SECONDS + 60)
        ).isoformat()
        conn = MagicMock()
        conn.ping.return_value = True
        conn.get.return_value = stale_ts.encode()
        conn.exists.return_value = 0  # No heartbeat — worker really is stuck.

        fake_queue = MagicMock()
        fake_queue.count = 5

        with patch("redis.Redis.from_url", return_value=conn):
            with patch("rq.Queue", return_value=fake_queue):
                with patch.object(
                    queue_client,
                    "get_settings",
                    return_value=MagicMock(redis_url="redis://x:6379/0"),
                ):
                    code = queue_client.run_healthcheck()
        assert code == 2

    def test_returns_0_when_long_render_in_progress_with_heartbeat(self):
        """A 30-minute project render is past the stale threshold for
        ``_LAST_JOB_KEY`` but the live heartbeat keeps the worker
        marked healthy. This is the bug the heartbeat fixes."""
        from src.queue import client as queue_client

        stale_ts = (
            datetime.utcnow()
            - timedelta(seconds=queue_client._HEALTH_MAX_AGE_SECONDS + 600)
        ).isoformat()
        conn = MagicMock()
        conn.ping.return_value = True
        conn.get.return_value = stale_ts.encode()
        conn.exists.return_value = 1  # Heartbeat present → mid-render.

        fake_queue = MagicMock()
        fake_queue.count = 1

        with patch("redis.Redis.from_url", return_value=conn):
            with patch("rq.Queue", return_value=fake_queue):
                with patch.object(
                    queue_client,
                    "get_settings",
                    return_value=MagicMock(redis_url="redis://x:6379/0"),
                ):
                    code = queue_client.run_healthcheck()
        assert code == 0

    def test_returns_0_when_idle_and_no_work(self):
        from src.queue import client as queue_client

        conn = MagicMock()
        conn.ping.return_value = True
        conn.get.return_value = None  # Never run a job
        conn.exists.return_value = 0

        fake_queue = MagicMock()
        fake_queue.count = 0

        with patch("redis.Redis.from_url", return_value=conn):
            with patch("rq.Queue", return_value=fake_queue):
                with patch.object(
                    queue_client,
                    "get_settings",
                    return_value=MagicMock(redis_url="redis://x:6379/0"),
                ):
                    code = queue_client.run_healthcheck()
        assert code == 0

    def test_returns_1_when_redis_unreachable(self):
        from src.queue import client as queue_client

        conn = MagicMock()
        conn.ping.side_effect = RuntimeError("nope")

        with patch("redis.Redis.from_url", return_value=conn):
            with patch.object(
                queue_client,
                "get_settings",
                return_value=MagicMock(redis_url="redis://x:6379/0"),
            ):
                code = queue_client.run_healthcheck()
        assert code == 1


class TestHeartbeat:
    def test_heartbeat_sets_short_ttl(self):
        """The heartbeat key MUST be set with a TTL so a crashed worker's
        stale heartbeat doesn't fool the healthcheck after process death."""
        from src.queue import client as queue_client

        conn = MagicMock()
        queue_client._heartbeat(conn)
        conn.set.assert_called_once()
        kwargs = conn.set.call_args.kwargs
        assert kwargs.get("ex") == queue_client._HEARTBEAT_TTL_SECONDS


class TestDLQPrune:
    def test_drops_entries_older_than_max_age(self):
        """``prune_dlq`` retains only entries with ``failed_at`` newer
        than the cutoff. Older payloads are pruned; unparseable rows are
        kept defensively."""
        from src.queue import client as queue_client

        now = datetime.utcnow()
        old_entry = json.dumps(
            {
                "job_id": "old",
                "failed_at": (now - timedelta(days=45)).isoformat(),
                "func_name": "f",
                "error": "x",
            }
        ).encode()
        fresh_entry = json.dumps(
            {
                "job_id": "fresh",
                "failed_at": (now - timedelta(days=2)).isoformat(),
                "func_name": "f",
                "error": "y",
            }
        ).encode()
        unparseable = b"not-json"

        conn = MagicMock()
        conn.lrange.return_value = [fresh_entry, old_entry, unparseable]
        conn.exists.return_value = 1

        with patch("redis.Redis.from_url", return_value=conn):
            with patch.object(
                queue_client,
                "get_settings",
                return_value=MagicMock(redis_url="redis://x:6379/0"),
            ):
                dropped = queue_client.prune_dlq(max_age_days=30)

        assert dropped == 1
        # Two items survived (fresh + unparseable) and lpush rewrote the
        # list in reverse so order is preserved.
        lpush_calls = [c.args for c in conn.lpush.call_args_list]
        pushed_payloads = [c[1] for c in lpush_calls]
        assert unparseable in pushed_payloads
        assert fresh_entry in pushed_payloads
        assert old_entry not in pushed_payloads

    def test_returns_zero_when_nothing_to_prune(self):
        from src.queue import client as queue_client

        now = datetime.utcnow()
        fresh = json.dumps(
            {
                "job_id": "fresh",
                "failed_at": now.isoformat(),
                "func_name": "f",
                "error": "y",
            }
        ).encode()
        conn = MagicMock()
        conn.lrange.return_value = [fresh]

        with patch("redis.Redis.from_url", return_value=conn):
            with patch.object(
                queue_client,
                "get_settings",
                return_value=MagicMock(redis_url="redis://x:6379/0"),
            ):
                dropped = queue_client.prune_dlq(max_age_days=30)
        assert dropped == 0
        conn.lpush.assert_not_called()
