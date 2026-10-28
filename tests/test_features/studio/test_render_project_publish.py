"""Unit tests for the project render publisher wiring (Week 8).

We don't need a real Redis or a real ffmpeg subprocess — the tests
just need to verify that the lifecycle hooks
(``_set_project_status`` / ``_set_project_progress`` /
``_mark_project_done`` / ``_fail_project``) each call
``publish_progress`` with the expected event shape.

Why this matters: the WebSocket transport assumes every DB
transition is mirrored by a pub/sub event. A silent miss would
mean the Renders page hangs on "Working…" forever, and the user
would only learn the truth after a manual refresh — easy to
regress without a guardrail test.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.features.studio import render_project as rp


@pytest.fixture
def project(client, db_session):
    """Insert a minimal StudioProject row so the helpers' DB
    lookups succeed.

    Depends on the ``client`` fixture purely for its side-effect
    of pointing :mod:`src.database.connection`'s module-level
    engine + session factory at the test in-memory SQLite. The
    publish helpers call ``get_session()`` directly (not through
    the FastAPI dependency tree), so without that override the
    helpers would hit the prod connection module."""
    from src.auth.password import hash_password
    from src.database.models import StudioProject, User

    user = User(
        email="proj@example.com",
        password_hash=hash_password("x" * 20),
        name="Proj Publisher Test",
        plan="free",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    proj = StudioProject(
        user_id=user.id,
        title="P",
        default_aspect="9:16",
    )
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)
    return proj


class TestProjectPublishWiring:
    def test_set_status_publishes_rendering(self, project):
        with patch("src.queue.progress.publish_progress") as pub:
            rp._set_project_status(project.id, "rendering")
            pub.assert_called_once()
            kwargs = pub.call_args.kwargs
            assert kwargs["kind"] == "project"
            assert kwargs["render_id"] == project.id
            assert kwargs["status"] == "rendering"
            assert kwargs["user_id"] == project.user_id

    def test_set_progress_publishes_percent_and_message(self, project):
        with patch("src.queue.progress.publish_progress") as pub:
            rp._set_project_progress(project.id, 42, "Encoding")
            pub.assert_called_once()
            kwargs = pub.call_args.kwargs
            assert kwargs["status"] == "rendering"
            assert kwargs["percent"] == 42
            assert kwargs["message"] == "Encoding"

    def test_mark_done_publishes_download_url(self, project):
        with patch("src.queue.progress.publish_progress") as pub:
            rp._mark_project_done(project.id, "https://r2/o.mp4")
            pub.assert_called_once()
            kwargs = pub.call_args.kwargs
            assert kwargs["status"] == "done"
            assert kwargs["percent"] == 100
            assert kwargs["download_url"] == "https://r2/o.mp4"

    def test_fail_publishes_error_truncated(self, project):
        with patch("src.queue.progress.publish_progress") as pub:
            big = "x" * 5000
            rp._fail_project(project.id, big)
            pub.assert_called_once()
            kwargs = pub.call_args.kwargs
            assert kwargs["status"] == "failed"
            # The error field should be present and non-empty; the
            # exact truncation length is an implementation detail
            # but it MUST NOT be the full 5000 chars.
            assert kwargs["error"] is not None
            assert len(kwargs["error"]) <= 2000

    def test_publish_failure_does_not_propagate(self, project):
        # Simulate a Redis blip; the lifecycle helper MUST NOT
        # re-raise — the DB write already happened and the render
        # pipeline can't be sunk by pub/sub.
        with patch(
            "src.queue.progress.publish_progress",
            side_effect=RuntimeError("redis down"),
        ):
            rp._set_project_status(project.id, "rendering")
            rp._set_project_progress(project.id, 10, "Working")
            rp._mark_project_done(project.id, "https://r2/o.mp4")
            rp._fail_project(project.id, "boom")
            # Reaching here without raising is the assertion.


class TestSuppressionFlag:
    """The retry wrapper sets ``_SUPPRESS_FAILURE_NOTIFY=True`` for
    mid-retry attempts so the user doesn't get a failure email when
    the next attempt may yet succeed. The publish path still fires;
    only the notify path is gated."""

    def test_suppression_blocks_failure_notify(self, project):
        rp._SUPPRESS_FAILURE_NOTIFY = True
        try:
            with patch(
                "src.features.notifications.notify_render_failed"
            ) as notify:
                rp._notify_project_event(
                    project.id, success=False, error_message="x"
                )
                notify.assert_not_called()
        finally:
            rp._SUPPRESS_FAILURE_NOTIFY = False

    def test_no_suppression_lets_failure_notify_fire(self, project):
        rp._SUPPRESS_FAILURE_NOTIFY = False
        with patch(
            "src.features.notifications.notify_render_failed"
        ) as notify:
            rp._notify_project_event(
                project.id, success=False, error_message="x"
            )
            notify.assert_called_once()
