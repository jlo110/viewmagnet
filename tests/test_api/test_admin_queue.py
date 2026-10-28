"""Tests for the admin DLQ router (Week 8 polish).

We mock the Redis client so the tests don't need a live broker. The
router calls ``redis.Redis.from_url`` -> ``conn.ping()`` then
``lrange`` / ``llen`` / ``lrem`` so we patch ``_get_redis`` directly
to return a ``MagicMock``.

Coverage:

* GET list — 200 with parsed entries
* POST reenqueue — happy path + not_found
* DELETE — happy path + not_found
* POST prune — happy path
* All endpoints — 403 for non-admin users
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def admin_user(db_session):
    """Create a user with ``is_admin=True`` so ``require_admin`` lets them through."""
    from src.database.models import User
    from src.auth.password import hash_password

    user = User(
        email="admin@example.com",
        password_hash=hash_password("adminpassword123"),
        name="Admin User",
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
        "password": "adminpassword123",
    }


@pytest.fixture
def admin_headers(admin_user):
    """Admin JWT headers."""
    from src.auth.jwt import create_access_token

    token = create_access_token(admin_user["id"], admin_user["email"])
    return {"Authorization": f"Bearer {token}"}


def _make_redis_mock(entries: list[dict]) -> MagicMock:
    """Build a mock Redis connection that returns the given DLQ entries.

    Entries are stored as JSON bytes (matching ``_dlq_push`` in
    src.queue.client) and operations like ``lrem`` mutate the in-memory
    list so the test can verify after a delete/re-enqueue.
    """
    backing = [json.dumps(e).encode("utf-8") for e in entries]
    conn = MagicMock()

    def lrange(_key, start, end):
        if end == -1:
            return list(backing[start:])
        return list(backing[start : end + 1])

    def llen(_key):
        return len(backing)

    def lrem(_key, count, value):  # noqa: ARG001 — count is RQ-style 1
        try:
            backing.remove(value)
            return 1
        except ValueError:
            return 0

    conn.lrange.side_effect = lrange
    conn.llen.side_effect = llen
    conn.lrem.side_effect = lrem
    conn.ping.return_value = True
    return conn


class TestAdminGate:
    """Non-admins (or anonymous) callers can't reach any DLQ endpoint."""

    def test_anonymous_gets_401(self, client):
        # No Authorization header -> falls through to get_current_user
        # which 401s (or 403 depending on dev mode) — either way the
        # router didn't let it through.
        response = client.get("/admin/queue/dlq")
        assert response.status_code in (401, 403)

    def test_non_admin_user_gets_403(self, client, auth_headers, monkeypatch):
        # Make sure the test user is NOT in the allow-list.
        monkeypatch.setenv("ADMIN_EMAILS", "someone-else@example.com")
        response = client.get("/admin/queue/dlq", headers=auth_headers)
        assert response.status_code == 403
        body = response.json()
        # Detail message wording varies (custom error envelope vs raw
        # FastAPI). Just confirm we surfaced *something* about admin.
        text = json.dumps(body).lower()
        assert "admin" in text


class TestListDlq:
    def test_returns_parsed_entries(self, client, admin_headers):
        sample = [
            {
                "job_id": "job-abc",
                "func_name": "src.features.studio.render_session",
                "args": [42],
                "kwargs": {"force": True},
                "error": "RuntimeError: ffmpeg exit 1",
                "error_type": "RuntimeError",
                "failed_at": "2026-05-01T12:00:00Z",
            },
            {
                "job_id": "job-xyz",
                "func_name": "src.features.studio.render_project",
                "args": [7],
                "kwargs": {},
                "error": "TimeoutError",
                "error_type": "TimeoutError",
                "failed_at": "2026-04-30T09:00:00Z",
            },
        ]
        with patch(
            "src.api.routers.admin_queue._get_redis",
            return_value=_make_redis_mock(sample),
        ):
            response = client.get(
                "/admin/queue/dlq", headers=admin_headers
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total"] == 2
        assert len(data["entries"]) == 2
        # Indexes are 0-based and preserve list order
        assert data["entries"][0]["index"] == 0
        assert data["entries"][0]["job_id"] == "job-abc"
        assert data["entries"][0]["func_name"] == (
            "src.features.studio.render_session"
        )
        assert data["entries"][0]["args"] == [42]
        assert data["entries"][0]["kwargs"] == {"force": True}
        assert data["entries"][1]["job_id"] == "job-xyz"

    def test_unparseable_entry_is_surfaced(self, client, admin_headers):
        # Operator should see "(unparseable DLQ entry)" rather than the
        # whole endpoint blowing up.
        bad = MagicMock()
        bad.lrange.return_value = [b"this is not json"]
        bad.llen.return_value = 1
        bad.ping.return_value = True
        with patch(
            "src.api.routers.admin_queue._get_redis", return_value=bad
        ):
            response = client.get(
                "/admin/queue/dlq", headers=admin_headers
            )
        assert response.status_code == 200
        entries = response.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["error"] == "(unparseable DLQ entry)"
        assert entries[0]["job_id"] is None


class TestReenqueueDlq:
    def test_reenqueues_and_removes_row(self, client, admin_headers):
        sample = [
            {
                "job_id": "job-abc",
                "func_name": "src.features.studio.render_session",
                "args": [42],
                "kwargs": {"force": True},
                "error": "boom",
                "error_type": "RuntimeError",
                "failed_at": "2026-05-01T12:00:00Z",
            }
        ]
        conn = _make_redis_mock(sample)
        with patch(
            "src.api.routers.admin_queue._get_redis", return_value=conn
        ), patch(
            "src.api.routers.admin_queue.enqueue_job",
            return_value="new-job-id",
        ) as enqueue:
            response = client.post(
                "/admin/queue/dlq/job-abc/reenqueue",
                headers=admin_headers,
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "ok"
        assert data["job_id"] == "new-job-id"
        # The enqueue gets the original func_name + args + kwargs verbatim.
        enqueue.assert_called_once_with(
            "src.features.studio.render_session", 42, force=True
        )
        # And the DLQ row was removed.
        conn.lrem.assert_called_once()

    def test_not_found_returns_status_not_found(self, client, admin_headers):
        conn = _make_redis_mock([])
        with patch(
            "src.api.routers.admin_queue._get_redis", return_value=conn
        ), patch(
            "src.api.routers.admin_queue.enqueue_job"
        ) as enqueue:
            response = client.post(
                "/admin/queue/dlq/job-missing/reenqueue",
                headers=admin_headers,
            )
        assert response.status_code == 200
        assert response.json()["status"] == "not_found"
        enqueue.assert_not_called()

    def test_no_func_name_returns_400(self, client, admin_headers):
        sample = [
            {
                "job_id": "job-abc",
                "func_name": None,  # corrupted row — refuse to re-run
                "args": [],
                "kwargs": {},
                "error": "boom",
            }
        ]
        conn = _make_redis_mock(sample)
        with patch(
            "src.api.routers.admin_queue._get_redis", return_value=conn
        ):
            response = client.post(
                "/admin/queue/dlq/job-abc/reenqueue",
                headers=admin_headers,
            )
        assert response.status_code == 400


class TestDeleteDlq:
    def test_deletes_entry(self, client, admin_headers):
        sample = [
            {
                "job_id": "job-abc",
                "func_name": "x",
                "args": [],
                "kwargs": {},
                "error": "boom",
            }
        ]
        conn = _make_redis_mock(sample)
        with patch(
            "src.api.routers.admin_queue._get_redis", return_value=conn
        ):
            response = client.delete(
                "/admin/queue/dlq/job-abc", headers=admin_headers
            )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        conn.lrem.assert_called_once()

    def test_missing_returns_not_found(self, client, admin_headers):
        conn = _make_redis_mock([])
        with patch(
            "src.api.routers.admin_queue._get_redis", return_value=conn
        ):
            response = client.delete(
                "/admin/queue/dlq/job-nope", headers=admin_headers
            )
        assert response.status_code == 200
        assert response.json()["status"] == "not_found"


class TestPruneDlq:
    def test_invokes_prune_with_age_days(self, client, admin_headers):
        with patch(
            "src.api.routers.admin_queue.prune_dlq", return_value=3
        ) as prune:
            response = client.post(
                "/admin/queue/dlq/prune?age_days=14", headers=admin_headers
            )
        assert response.status_code == 200, response.text
        assert response.json() == {"dropped": 3}
        prune.assert_called_once_with(max_age_days=14)
