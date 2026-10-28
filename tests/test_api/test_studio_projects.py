"""Tests for the Studio multi-clip projects API (Week 7 + 8).

Covers:

* Create / list / get / patch / delete project
* Append clip (must own the underlying EditSession)
* Reorder clip (position renumbering keeps the sequence contiguous)
* Ripple-delete (positions after the deleted clip shift down by 1)
* Render endpoint: 400 on empty, 402 on budget exceeded, idempotent
  when already in-flight, fires the pub/sub event with ``kind="project"``.

The router uses the same sync ``get_session`` pattern as the rest of
the codebase, so the standard dashboard fixtures (``client``,
``test_user``, ``auth_headers``, ``db_session``) work.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest


def _seed_session(db_session, user_id: int, clip_key: str, title: str) -> int:
    """Insert an EditSession we can attach to a project. Returns its id."""
    from src.database.models import EditSession

    session = EditSession(
        user_id=user_id,
        clip_key=clip_key,
        source_video_url="https://example.com/v.mp4",
        source_clip_index=0,
        source_start_time=0.0,
        source_end_time=10.0,
        title=title,
        spec="{}",
    )
    db_session.add(session)
    db_session.commit()
    return session.id


class TestProjectCrud:
    def test_create_project_returns_spec(self, client, auth_headers):
        response = client.post(
            "/studio/projects",
            json={"title": "My long-form video", "default_aspect": "16:9"},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["title"] == "My long-form video"
        assert data["default_aspect"] == "16:9"
        assert data["clips"] == []
        assert data["last_render_status"] == "idle"

    def test_list_projects_returns_user_projects_newest_first(
        self, client, auth_headers
    ):
        client.post(
            "/studio/projects", json={"title": "First"}, headers=auth_headers
        )
        client.post(
            "/studio/projects", json={"title": "Second"}, headers=auth_headers
        )
        response = client.get("/studio/projects", headers=auth_headers)
        assert response.status_code == 200
        titles = [p["title"] for p in response.json()]
        # Newest-first ordering
        assert titles[:2] == ["Second", "First"]

    def test_patch_project_updates_fields(self, client, auth_headers):
        created = client.post(
            "/studio/projects", json={"title": "Initial"}, headers=auth_headers
        ).json()
        response = client.patch(
            f"/studio/projects/{created['id']}",
            json={
                "title": "Renamed",
                "default_transition_type": "fade",
                "default_transition_ms": 500,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Renamed"
        assert data["default_transition_type"] == "fade"
        assert data["default_transition_ms"] == 500

    def test_get_project_404_for_other_users(self, client, auth_headers):
        """Project lookup is scoped to the authenticated user."""
        response = client.get("/studio/projects/99999", headers=auth_headers)
        assert response.status_code == 404

    def test_create_and_patch_persists_description(
        self, client, auth_headers
    ):
        """Week 9 Connected Tools: the Distribution Hub handoff
        depends on ``description`` flowing through both POST and
        PATCH. Without this round-trip the publish caption can't
        pre-fill from the project."""
        created = client.post(
            "/studio/projects",
            json={
                "title": "Long form",
                "description": "Seeded from the script writer.",
            },
            headers=auth_headers,
        ).json()
        assert created["description"] == "Seeded from the script writer."

        patched = client.patch(
            f"/studio/projects/{created['id']}",
            json={"description": "Replaced caption text"},
            headers=auth_headers,
        )
        assert patched.status_code == 200
        assert patched.json()["description"] == "Replaced caption text"

        # Empty-string PATCH clears the description (so the UI has a
        # way to remove it without a separate endpoint).
        cleared = client.patch(
            f"/studio/projects/{created['id']}",
            json={"description": ""},
            headers=auth_headers,
        )
        assert cleared.status_code == 200
        assert cleared.json()["description"] is None

    def test_delete_project(self, client, auth_headers):
        created = client.post(
            "/studio/projects", json={"title": "doomed"}, headers=auth_headers
        ).json()
        response = client.delete(
            f"/studio/projects/{created['id']}", headers=auth_headers
        )
        assert response.status_code == 204
        followup = client.get(
            f"/studio/projects/{created['id']}", headers=auth_headers
        )
        assert followup.status_code == 404


class TestProjectClips:
    def _make_project(self, client, auth_headers, title: str = "P") -> int:
        return client.post(
            "/studio/projects", json={"title": title}, headers=auth_headers
        ).json()["id"]

    def test_append_clip_rejects_other_users_session(
        self, client, auth_headers, db_session
    ):
        """Cross-tenant session ids must be rejected (we never want
        a user to splice somebody else's session into their project)."""
        from src.database.models import User

        other = User(
            email="other@example.com",
            plan="free",
        )
        db_session.add(other)
        db_session.commit()
        other_session_id = _seed_session(db_session, other.id, "abc123", "Theirs")

        project_id = self._make_project(client, auth_headers)
        response = client.post(
            f"/studio/projects/{project_id}/clips",
            json={"edit_session_id": other_session_id},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_append_clip_assigns_contiguous_positions(
        self, client, auth_headers, test_user, db_session
    ):
        project_id = self._make_project(client, auth_headers)
        s1 = _seed_session(db_session, test_user["id"], "key_a", "A")
        s2 = _seed_session(db_session, test_user["id"], "key_b", "B")
        s3 = _seed_session(db_session, test_user["id"], "key_c", "C")

        for sid in (s1, s2, s3):
            r = client.post(
                f"/studio/projects/{project_id}/clips",
                json={"edit_session_id": sid},
                headers=auth_headers,
            )
            assert r.status_code == 201, r.text

        full = client.get(
            f"/studio/projects/{project_id}", headers=auth_headers
        ).json()
        positions = [c["position"] for c in full["clips"]]
        titles = [c["title"] for c in full["clips"]]
        assert positions == [0, 1, 2]
        assert titles == ["A", "B", "C"]

    def test_patch_clip_position_renumbers_contiguously(
        self, client, auth_headers, test_user, db_session
    ):
        """Moving the last clip to position 0 should leave positions
        as [0, 1, 2] with the moved clip now first."""
        project_id = self._make_project(client, auth_headers)
        s1 = _seed_session(db_session, test_user["id"], "key_a", "A")
        s2 = _seed_session(db_session, test_user["id"], "key_b", "B")
        s3 = _seed_session(db_session, test_user["id"], "key_c", "C")
        for sid in (s1, s2, s3):
            client.post(
                f"/studio/projects/{project_id}/clips",
                json={"edit_session_id": sid},
                headers=auth_headers,
            )

        # Find the clip-row id of "C" (position 2 originally).
        spec = client.get(
            f"/studio/projects/{project_id}", headers=auth_headers
        ).json()
        c_clip_id = next(
            c["id"] for c in spec["clips"] if c["title"] == "C"
        )

        response = client.patch(
            f"/studio/projects/{project_id}/clips/{c_clip_id}",
            json={"position": 0},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        positions = [c["position"] for c in data["clips"]]
        titles = [c["title"] for c in data["clips"]]
        assert positions == [0, 1, 2]
        assert titles == ["C", "A", "B"]

    def test_delete_clip_ripples_positions(
        self, client, auth_headers, test_user, db_session
    ):
        """Deleting the middle clip shifts everything after it down."""
        project_id = self._make_project(client, auth_headers)
        s1 = _seed_session(db_session, test_user["id"], "key_a", "A")
        s2 = _seed_session(db_session, test_user["id"], "key_b", "B")
        s3 = _seed_session(db_session, test_user["id"], "key_c", "C")
        for sid in (s1, s2, s3):
            client.post(
                f"/studio/projects/{project_id}/clips",
                json={"edit_session_id": sid},
                headers=auth_headers,
            )

        spec = client.get(
            f"/studio/projects/{project_id}", headers=auth_headers
        ).json()
        b_clip_id = next(c["id"] for c in spec["clips"] if c["title"] == "B")

        response = client.delete(
            f"/studio/projects/{project_id}/clips/{b_clip_id}",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        titles = [c["title"] for c in data["clips"]]
        positions = [c["position"] for c in data["clips"]]
        assert titles == ["A", "C"]
        assert positions == [0, 1]

    def test_patch_clip_trim_and_transition(
        self, client, auth_headers, test_user, db_session
    ):
        project_id = self._make_project(client, auth_headers)
        sid = _seed_session(db_session, test_user["id"], "key_only", "Only")
        client.post(
            f"/studio/projects/{project_id}/clips",
            json={"edit_session_id": sid},
            headers=auth_headers,
        )
        spec = client.get(
            f"/studio/projects/{project_id}", headers=auth_headers
        ).json()
        clip_id = spec["clips"][0]["id"]
        response = client.patch(
            f"/studio/projects/{project_id}/clips/{clip_id}",
            json={
                "trim_in_seconds": 1.5,
                "trim_out_seconds": 0.5,
                "transition_in_type": "zoom_in",
                "transition_in_ms": 400,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        clip = response.json()["clips"][0]
        assert clip["trim_in_seconds"] == 1.5
        assert clip["trim_out_seconds"] == 0.5
        assert clip["transition_in_type"] == "zoom_in"
        assert clip["transition_in_ms"] == 400


class TestProjectRender:
    """Project render endpoint — pre-flight gates, idempotency, events."""

    def _make_project_with_clip(
        self, client, auth_headers, db_session, user_id: int, duration: float = 30.0
    ) -> int:
        """Helper: create a project with one ``duration``-second clip,
        return the project id."""
        project_id = client.post(
            "/studio/projects",
            json={"title": "Render test"},
            headers=auth_headers,
        ).json()["id"]
        # Seed a session matching ``duration``.
        from src.database.models import EditSession

        session = EditSession(
            user_id=user_id,
            clip_key="render_test_key",
            source_video_url="https://example.com/v.mp4",
            source_clip_index=0,
            source_start_time=0.0,
            source_end_time=duration,
            title="Render test clip",
            spec="{}",
        )
        db_session.add(session)
        db_session.commit()
        client.post(
            f"/studio/projects/{project_id}/clips",
            json={"edit_session_id": session.id},
            headers=auth_headers,
        )
        return project_id

    def test_render_400_when_no_clips(self, client, auth_headers):
        """Empty project rejected with the unified error envelope's
        ``error.message`` carrying the human-readable reason."""
        project_id = client.post(
            "/studio/projects",
            json={"title": "Empty"},
            headers=auth_headers,
        ).json()["id"]
        response = client.post(
            f"/studio/projects/{project_id}/render", headers=auth_headers
        )
        assert response.status_code == 400
        body = response.json()
        assert "no clips" in body["error"]["message"].lower()

    def test_render_idempotent_when_already_in_flight(
        self, client, auth_headers, test_user, db_session
    ):
        """A second click while the previous render is still queued/
        rendering returns the same job id rather than enqueueing twice."""
        project_id = self._make_project_with_clip(
            client, auth_headers, db_session, test_user["id"]
        )
        # Force the project into ``rendering`` state directly so we
        # don't depend on an actual ffmpeg invocation succeeding.
        from src.database.connection import get_session as _gs
        from src.database.models import StudioProject

        with _gs() as db:
            row = db.get(StudioProject, project_id)
            row.last_render_status = "rendering"
            row.last_render_job_id = "existing-job-id"
            db.commit()

        response = client.post(
            f"/studio/projects/{project_id}/render", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "rendering"
        assert body["job_id"] == "existing-job-id"

    def test_publish_project_event_has_kind_project(self, monkeypatch):
        """``_publish_project_event`` must tag events with kind="project"
        so the frontend can route them to the project card. Pinning this
        contract here avoids a silent regression that would route project
        events to single-clip cards."""
        from src.features.studio import render_project as rp

        captured: dict = {}

        def fake_publish(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(
            "src.queue.progress.publish_progress", fake_publish
        )

        # Inject a fake StudioProject get so we don't need a real row.
        class _FakeProject:
            user_id = 42

        monkeypatch.setattr(
            rp,
            "get_session",
            lambda: _SessionCM(_FakeProject()),
        )

        rp._publish_project_event(
            project_id=99,
            status="rendering",
            percent=42,
            message="Halfway",
        )

        assert captured["kind"] == "project"
        assert captured["render_id"] == 99
        assert captured["user_id"] == 42
        assert captured["percent"] == 42
        assert captured["status"] == "rendering"


class _SessionCM:
    """Minimal context-manager stand-in for ``get_session()`` so the
    event-publishing test doesn't need a real DB connection."""

    def __init__(self, project_row):
        self._row = project_row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, model, pk):  # noqa: D401, ARG002
        return self._row


class TestUnifiedRendersQueue:
    """``GET /studio/renders`` should return both single-clip and
    project renders, newest-first, omitting rows in the ``idle`` state
    so the queue isn't cluttered with sessions that were never rendered."""

    def test_lists_both_kinds_newest_first(
        self, client, auth_headers, test_user, db_session
    ):
        from datetime import datetime, timedelta

        from src.database.models import EditSession, StudioProject

        # Two renders with controlled updated_at so the ordering is
        # deterministic and asserts can be exact.
        now = datetime.utcnow()
        sess = EditSession(
            user_id=test_user["id"],
            clip_key="queue_clip_1",
            source_video_url="https://example.com/v.mp4",
            source_clip_index=0,
            source_start_time=0.0,
            source_end_time=10.0,
            title="Older session",
            spec="{}",
            last_render_status="done",
            last_render_url="https://r2.example.com/out1.mp4",
            updated_at=now - timedelta(hours=2),
        )
        db_session.add(sess)
        proj = StudioProject(
            user_id=test_user["id"],
            title="Newer project",
            default_aspect="9:16",
            last_render_status="rendering",
            render_progress=40,
            render_progress_message="Concatenating",
            updated_at=now,
        )
        db_session.add(proj)
        # Add an idle session that MUST be filtered out.
        db_session.add(
            EditSession(
                user_id=test_user["id"],
                clip_key="queue_clip_idle",
                source_video_url="https://example.com/v.mp4",
                source_clip_index=0,
                source_start_time=0.0,
                source_end_time=10.0,
                title="Idle — never rendered",
                spec="{}",
                last_render_status="idle",
                updated_at=now - timedelta(minutes=1),
            )
        )
        db_session.commit()

        response = client.get("/studio/renders", headers=auth_headers)
        assert response.status_code == 200, response.text
        items = response.json()
        # ``idle`` filtered out → exactly 2 items.
        assert len(items) == 2
        # Newest-first: project (now) before session (now - 2h).
        assert items[0]["kind"] == "project"
        assert items[0]["render_id"] == proj.id
        assert items[0]["status"] == "rendering"
        assert items[0]["progress"] == 40
        assert items[0]["open_path"] == f"/dashboard/studio/project/{proj.id}"
        # Projects don't have a clip key (they're a stitched bundle).
        assert items[0]["clip_key"] is None
        assert items[1]["kind"] == "session"
        assert items[1]["render_id"] == sess.id
        assert items[1]["status"] == "done"
        assert "queue_clip_1" in items[1]["open_path"]
        assert items[1]["download_url"] == "https://r2.example.com/out1.mp4"
        # Sessions surface clip_key so the Renders UI can fire a real
        # ``POST /studio/render`` retry without bouncing through Studio.
        assert items[1]["clip_key"] == "queue_clip_1"
