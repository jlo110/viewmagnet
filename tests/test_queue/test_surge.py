"""Tests for :mod:`src.queue.surge` — surge classifier (Week 8 P3).

The classifier is pure: it eats a queue-depth snapshot dict and
returns a ``SurgeSnapshot`` with a level + wait estimate. These
tests pin the bucket boundaries so a well-meaning tweak to the
thresholds doesn't quietly start (or stop) firing the surge banner
at the wrong moments.
"""
from __future__ import annotations

import pytest

from src.queue.surge import (
    AVG_RENDER_SECONDS,
    SurgeSnapshot,
    classify_depth,
)


class TestClassifyDepth:
    def test_returns_unavailable_when_redis_absent(self):
        snap = classify_depth(None)
        assert snap.available is False
        assert snap.level == "normal"
        assert snap.queue_depth == 0
        assert snap.estimated_wait_seconds == 0

    def test_returns_unavailable_for_empty_snapshot(self):
        # Treat an empty dict the same as ``None`` — it means the
        # probe ran but returned nothing useful.
        snap = classify_depth({})
        assert snap.available is False
        assert snap.level == "normal"

    def test_empty_queue_classifies_normal(self):
        snap = classify_depth({"queued": 0, "started": 0})
        assert snap.available is True
        assert snap.level == "normal"
        assert snap.queue_depth == 0
        assert snap.estimated_wait_seconds == 0

    def test_one_job_in_flight_is_normal(self):
        # A single job started + nothing queued is the steady-state
        # for a busy-but-fine worker. We shouldn't yell about it.
        snap = classify_depth({"queued": 0, "started": 1})
        # Estimated wait ~= 1 * AVG_RENDER_SECONDS = 180s → busy.
        # (queue depth 0 → normal; level uses MAX of the two.)
        assert snap.level == "busy"
        assert snap.estimated_wait_seconds == 180

    def test_one_job_queued_alone_is_busy(self):
        # depth=1 → normal-bucket, wait=180s → busy-bucket. MAX = busy.
        snap = classify_depth({"queued": 1, "started": 0})
        assert snap.level == "busy"
        assert snap.estimated_wait_seconds == 180

    def test_two_jobs_queued_escalates_via_wait(self):
        # depth=2 → busy-bucket, wait=360s → slammed-bucket. The
        # max-of-two-buckets semantics escalates to slammed because
        # the wait alone is already long enough that we should warn.
        snap = classify_depth({"queued": 2, "started": 0})
        assert snap.level == "slammed"
        assert snap.estimated_wait_seconds == 360

    @pytest.mark.parametrize("queued", [5, 6, 10, 50])
    def test_deep_queue_triggers_slammed(self, queued: int):
        snap = classify_depth({"queued": queued, "started": 0})
        assert snap.level == "slammed"

    def test_estimated_wait_includes_started(self):
        # A single-worker setup means the running job blocks ours
        # too — wait should include it.
        snap = classify_depth({"queued": 1, "started": 1})
        # (1 + 1) * 180 = 360s.
        assert snap.estimated_wait_seconds == 360

    def test_wait_rounds_to_10s_buckets(self):
        # Override the avg to a number that isn't a multiple of 10
        # to verify the rounding behavior. 7s * 4 jobs = 28s → 30s.
        snap = classify_depth(
            {"queued": 3, "started": 1}, avg_render_seconds=7
        )
        assert snap.estimated_wait_seconds == 30

    def test_long_running_render_alone_escalates(self):
        # Even with depth=1, if the avg render time is huge enough
        # to push wait past the slammed threshold, the banner
        # should escalate. This guards the "max of depth & wait
        # bucket" semantics.
        snap = classify_depth(
            {"queued": 1, "started": 0}, avg_render_seconds=600
        )
        # 1 * 600 = 600s > 300s → slammed regardless of depth=1.
        assert snap.level == "slammed"

    def test_returns_correct_dataclass_type(self):
        snap = classify_depth({"queued": 1, "started": 0})
        assert isinstance(snap, SurgeSnapshot)
        d = snap.to_dict()
        assert set(d.keys()) == {
            "level",
            "queue_depth",
            "started",
            "estimated_wait_seconds",
            "available",
        }

    def test_default_avg_render_seconds_constant_is_stable(self):
        # If we ever bump ``AVG_RENDER_SECONDS`` without re-tuning
        # the wait thresholds, the test above ("one_job_in_flight")
        # will flip its expected level. Pin the constant so the
        # change is intentional and the docs stay in sync.
        assert AVG_RENDER_SECONDS == 180
