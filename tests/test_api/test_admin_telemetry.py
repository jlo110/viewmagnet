"""Tests for the admin telemetry router (Week 8 P3 polish).

The router is a thin pass-through over
:mod:`src.queue.telemetry_summary` + :mod:`src.queue.surge` — the
heavy lifting is unit-tested there. These tests focus on the API
seam:

  * shape of the response matches the Pydantic model the frontend
    consumes
  * admin gate is wired (anonymous / non-admin → 403/401)
  * the lookback bound is enforced (?lookback_hours over 720 fails
    validation)
  * the queue snapshot tolerates Redis being unavailable (returns
    ``available: False`` instead of 500)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.database.models import AuditEvent


# ---------------------------------------------------------------------------
# Fixtures — match the admin-queue test style so behavior is consistent
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user(db_session):
    from src.auth.password import hash_password
    from src.database.models import User

    user = User(
        email="telemetry-admin@example.com",
        password_hash=hash_password("adminpassword123"),
        name="Telemetry Admin",
        plan="pro",
        is_admin=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "plan": user.plan,
    }


@pytest.fixture
def admin_headers(admin_user):
    from src.auth.jwt import create_access_token

    token = create_access_token(admin_user["id"], admin_user["email"])
    return {"Authorization": f"Bearer {token}"}


def _seed_audit_events(db_session) -> None:
    """Seed a small render funnel so the rollup has data to work with."""
    now = datetime.utcnow()
    rows = [
        AuditEvent(
            user_id=1,
            event_type="render.queued",
            details=json.dumps({"render_kind": "session", "render_id": 1}),
            created_at=now - timedelta(minutes=10),
        ),
        AuditEvent(
            user_id=1,
            event_type="render.started",
            details=json.dumps({"render_kind": "session", "render_id": 1}),
            created_at=now - timedelta(minutes=9),
        ),
        AuditEvent(
            user_id=1,
            event_type="render.completed",
            details=json.dumps({"render_kind": "session", "render_id": 1}),
            created_at=now - timedelta(minutes=8),
        ),
        AuditEvent(
            user_id=1,
            event_type="render.failed",
            details=json.dumps({"error_type": "TimeoutError"}),
            created_at=now - timedelta(minutes=5),
        ),
        AuditEvent(
            user_id=2,
            event_type="render.cancelled",
            details=json.dumps({"render_kind": "project", "render_id": 7}),
            created_at=now - timedelta(minutes=3),
        ),
    ]
    for r in rows:
        db_session.add(r)
    db_session.commit()


# ---------------------------------------------------------------------------
# Admin gate
# ---------------------------------------------------------------------------


class TestAdminGate:
    def test_anonymous_blocked_from_renders(self, client):
        response = client.get("/admin/telemetry/renders")
        assert response.status_code in (401, 403)

    def test_anonymous_blocked_from_queue(self, client):
        response = client.get("/admin/telemetry/queue")
        assert response.status_code in (401, 403)

    def test_non_admin_blocked(self, client, auth_headers, monkeypatch):
        monkeypatch.setenv("ADMIN_EMAILS", "someone-else@example.com")
        response = client.get(
            "/admin/telemetry/renders", headers=auth_headers
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# /admin/telemetry/renders
# ---------------------------------------------------------------------------


class TestRenderTelemetry:
    def test_returns_summary_shape(
        self, client, admin_headers, db_session
    ):
        _seed_audit_events(db_session)
        response = client.get(
            "/admin/telemetry/renders", headers=admin_headers
        )
        assert response.status_code == 200, response.text
        data = response.json()
        # Top-level keys the frontend depends on.
        for key in (
            "window",
            "counts",
            "rates",
            "wait_seconds",
            "render_seconds",
            "top_errors",
            "by_day",
        ):
            assert key in data, f"missing top-level key: {key}"

        # Counts reflect the seeded events.
        assert data["counts"]["completed"] == 1
        assert data["counts"]["failed"] == 1
        assert data["counts"]["cancelled"] == 1

        # Cancel + failure are separated in rates (the whole point of
        # this dashboard) so the success rate is 1/3, not 1/2.
        assert pytest.approx(data["rates"]["success_rate"], abs=1e-3) == 1 / 3
        assert pytest.approx(data["rates"]["failure_rate"], abs=1e-3) == 1 / 3
        assert pytest.approx(data["rates"]["cancel_rate"], abs=1e-3) == 1 / 3

        # Wait / render duration samples from the paired events.
        assert data["wait_seconds"]["samples"] == 1
        assert data["render_seconds"]["samples"] == 1

        # Top errors picked up the TimeoutError tag from details.
        assert data["top_errors"][0]["error_type"] == "TimeoutError"

    def test_rejects_lookback_over_cap(self, client, admin_headers):
        # The endpoint caps lookback at 30d (720h) to keep the audit
        # scan bounded. Anything bigger should 422, not silently
        # widen the window.
        response = client.get(
            "/admin/telemetry/renders?lookback_hours=99999",
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_returns_zeros_for_quiet_window(
        self, client, admin_headers
    ):
        # No audit rows seeded — the rollup should return a
        # well-formed zero-everything payload instead of nulls.
        response = client.get(
            "/admin/telemetry/renders?lookback_hours=1",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["counts"]["queued"] == 0
        assert data["counts"]["completed"] == 0
        assert data["rates"]["success_rate"] == 0.0


# ---------------------------------------------------------------------------
# /admin/telemetry/queue
# ---------------------------------------------------------------------------


class TestQueueTelemetry:
    def test_reports_unavailable_when_redis_absent(
        self, client, admin_headers
    ):
        # ``get_queue_depth`` returns None when Redis isn't
        # configured — the endpoint should still 200 with
        # available=False so the dashboard hides the card instead
        # of showing a 500.
        with patch(
            "src.api.routers.admin_telemetry.get_queue_depth",
            return_value=None,
        ):
            response = client.get(
                "/admin/telemetry/queue", headers=admin_headers
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["available"] is False
        assert data["level"] == "normal"
        assert data["queue_depth"] == 0

    def test_reports_classified_surge_when_redis_present(
        self, client, admin_headers
    ):
        with patch(
            "src.api.routers.admin_telemetry.get_queue_depth",
            return_value={
                "queued": 6,
                "started": 1,
                "deferred": 0,
                "scheduled": 0,
            },
        ):
            response = client.get(
                "/admin/telemetry/queue", headers=admin_headers
            )
        assert response.status_code == 200
        data = response.json()
        assert data["available"] is True
        assert data["level"] == "slammed"
        assert data["queue_depth"] == 6
        assert data["started"] == 1
        assert data["estimated_wait_seconds"] > 0
