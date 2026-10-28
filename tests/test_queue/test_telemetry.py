"""Tests for the render-pipeline telemetry helpers (Week 8 Day 6.1).

The telemetry layer is best-effort by contract — every helper must:

  1. Emit a structlog event with the consistent ``render.<phase>``
     name + base fields (``user_id``, ``render_kind``, ``render_id``).
  2. Write an ``AuditEvent`` row for lifecycle phases.
  3. NOT raise when the audit write fails.

We assert all three. Each phase has its own focused test to make a
later regression easy to localize.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.queue import telemetry as tele


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_progress_sample_state():
    """``record_render_progress`` keeps a private bucket cursor as
    a function attribute so the per-percent sampler survives across
    calls. Clear it between tests so the first event in each test
    always fires."""
    if hasattr(tele.record_render_progress, "_last_bucket"):
        delattr(tele.record_render_progress, "_last_bucket")
    yield
    if hasattr(tele.record_render_progress, "_last_bucket"):
        delattr(tele.record_render_progress, "_last_bucket")


class _AuditCapture:
    """Side-effect helper — captures every ``record_audit_event``
    call so tests can introspect what landed in the audit table
    without touching SQLAlchemy."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)


# ---------------------------------------------------------------------------
# Audit-write fan-out
# ---------------------------------------------------------------------------


class TestAuditFanOut:
    def test_queued_writes_audit_row(self):
        capture = _AuditCapture()
        with patch.object(tele, "record_audit_event", side_effect=capture):
            tele.record_render_queued(
                user_id=42,
                render_kind="project",
                render_id=7,
                projected_seconds=120.5,
                job_id="job-abc",
                plan="free",
            )
        assert len(capture.calls) == 1
        call = capture.calls[0]
        assert call["event_type"] == "render.queued"
        assert call["user_id"] == 42
        assert call["details"]["render_kind"] == "project"
        assert call["details"]["render_id"] == 7
        assert call["details"]["projected_seconds"] == 120.5
        assert call["details"]["plan"] == "free"

    def test_completed_writes_audit_row(self):
        capture = _AuditCapture()
        with patch.object(tele, "record_audit_event", side_effect=capture):
            tele.record_render_completed(
                user_id=42,
                render_kind="session",
                render_id=7,
                duration_seconds=18.3,
                output_url="https://r2.example.com/x.mp4",
                minutes_billed=0.3,
            )
        assert len(capture.calls) == 1
        details = capture.calls[0]["details"]
        assert details["render_kind"] == "session"
        assert details["minutes_billed"] == 0.3
        assert details["output_url"] == "https://r2.example.com/x.mp4"

    def test_failed_writes_audit_row(self):
        capture = _AuditCapture()
        with patch.object(tele, "record_audit_event", side_effect=capture):
            tele.record_render_failed(
                user_id=99,
                render_kind="project",
                render_id=11,
                error="ffmpeg exit 1",
                error_type="RuntimeError",
            )
        assert capture.calls[0]["event_type"] == "render.failed"
        assert capture.calls[0]["details"]["error"] == "ffmpeg exit 1"

    def test_budget_blocked_writes_audit_row(self):
        capture = _AuditCapture()
        with patch.object(tele, "record_audit_event", side_effect=capture):
            tele.record_render_budget_blocked(
                user_id=5,
                render_kind="project",
                render_id=12,
                projected_seconds=300,
                minutes_remaining=2.5,
                plan="free",
            )
        assert capture.calls[0]["event_type"] == "render.budget_blocked"
        assert capture.calls[0]["details"]["minutes_remaining"] == 2.5

    def test_email_sent_writes_audit_row(self):
        capture = _AuditCapture()
        with patch.object(tele, "record_audit_event", side_effect=capture):
            tele.record_render_email_sent(
                user_id=5,
                render_kind="session",
                render_id=12,
                outcome="success",
                email="user@example.com",
            )
        assert capture.calls[0]["event_type"] == "render.email_sent"
        assert capture.calls[0]["details"]["outcome"] == "success"

    def test_dlq_writes_audit_row(self):
        capture = _AuditCapture()
        with patch.object(tele, "record_audit_event", side_effect=capture):
            tele.record_render_dlq(
                user_id=8,
                render_kind="session",
                render_id=22,
                job_id="job-xyz",
                func_name="src.features.studio.render:render_session",
                error="OOM",
                error_type="MemoryError",
            )
        assert capture.calls[0]["event_type"] == "render.dlq"
        assert capture.calls[0]["details"]["func_name"].endswith(
            "render_session"
        )

    def test_cancelled_writes_audit_row(self):
        """P3 polish: ``render.cancelled`` is its own audit event so
        the telemetry dashboard can split ``cancel_rate`` from
        ``failure_rate``. A regression that demoted cancel to a
        plain log line would make our success-rate chart lie."""
        capture = _AuditCapture()
        with patch.object(tele, "record_audit_event", side_effect=capture):
            tele.record_render_cancelled(
                user_id=11,
                render_kind="project",
                render_id=99,
                job_id="job-cancel",
                cancelled_by="user",
                previous_status="rendering",
                elapsed_seconds=12.5,
            )
        assert len(capture.calls) == 1
        call = capture.calls[0]
        assert call["event_type"] == "render.cancelled"
        assert call["user_id"] == 11
        details = call["details"]
        assert details["render_kind"] == "project"
        assert details["render_id"] == 99
        assert details["cancelled_by"] == "user"
        assert details["previous_status"] == "rendering"
        assert details["elapsed_seconds"] == 12.5
        assert details["job_id"] == "job-cancel"

    def test_cancelled_drops_none_fields(self):
        # Mirrors the pattern asserted for the other helpers — None
        # values are dropped from the payload so structured queries
        # don't have to special-case missing-vs-null.
        capture = _AuditCapture()
        with patch.object(tele, "record_audit_event", side_effect=capture):
            tele.record_render_cancelled(
                user_id=3,
                render_kind="session",
                render_id=4,
            )
        details = capture.calls[0]["details"]
        assert "elapsed_seconds" not in details
        assert "previous_status" not in details
        # cancelled_by defaults to "user" and is therefore present.
        assert details["cancelled_by"] == "user"


# ---------------------------------------------------------------------------
# Progress sampling — high-volume so it must NOT touch the audit table
# ---------------------------------------------------------------------------


class TestProgressSampling:
    def test_progress_never_writes_audit(self):
        capture = _AuditCapture()
        with patch.object(tele, "record_audit_event", side_effect=capture):
            for pct in range(0, 101, 5):
                tele.record_render_progress(
                    user_id=1,
                    render_kind="session",
                    render_id=1,
                    percent=float(pct),
                    message=f"{pct}%",
                )
        assert capture.calls == []

    def test_progress_samples_at_bucket_boundaries(self):
        # The default bucket count is 5 (i.e. ~20% steps). 0/20/40/
        # 60/80/100 each push a new bucket, so we expect 6 emits;
        # the intermediate values reuse the prior bucket and drop.
        emits: list[dict] = []

        def fake_logger_info(event, **fields):
            emits.append({"event": event, **fields})

        with patch.object(tele.logger, "info", side_effect=fake_logger_info):
            # Each whole-percent step from 0..100 — we expect emits
            # ONLY at fresh buckets (0, 20, 40, 60, 80, 100).
            for pct in range(0, 101):
                tele.record_render_progress(
                    user_id=1,
                    render_kind="session",
                    render_id=1,
                    percent=float(pct),
                )
        # Six distinct buckets at 20% intervals.
        assert len(emits) == 6
        for emit in emits:
            assert emit["event"] == "render.progress"

    def test_progress_with_none_percent_always_emits(self):
        emits: list[dict] = []

        def fake_logger_info(event, **fields):
            emits.append({"event": event, **fields})

        with patch.object(tele.logger, "info", side_effect=fake_logger_info):
            tele.record_render_progress(
                user_id=1,
                render_kind="project",
                render_id=42,
                percent=None,
                message="Starting",
            )
        assert len(emits) == 1
        assert emits[0]["message"] == "Starting"


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_audit_exception_does_not_propagate(self):
        # If the DB is down, the helper must swallow the error so
        # callers (the render worker) never break on telemetry.
        def boom(**_kwargs):
            raise RuntimeError("db is on fire")

        with patch.object(tele, "record_audit_event", side_effect=boom):
            # Must not raise.
            tele.record_render_queued(
                user_id=1,
                render_kind="session",
                render_id=1,
                projected_seconds=10,
                job_id="x",
                plan="free",
            )

    def test_none_fields_are_dropped_from_payload(self):
        captured_fields: dict = {}

        def fake_logger_info(event, **fields):  # noqa: ARG001
            captured_fields.update(fields)

        with patch.object(tele.logger, "info", side_effect=fake_logger_info), \
             patch.object(tele, "record_audit_event"):
            tele.record_render_queued(
                user_id=1,
                render_kind="session",
                render_id=1,
                projected_seconds=10,
                # job_id + plan omitted on purpose
            )
        assert "job_id" not in captured_fields
        assert "plan" not in captured_fields
        # Base fields still present
        assert captured_fields["user_id"] == 1
        assert captured_fields["render_kind"] == "session"
        assert captured_fields["projected_seconds"] == 10
