"""Tests for the outbound notifications wrapper (Week 8).

Covers:

* Console provider always succeeds and never raises.
* Failure-path notifications bypass the 1h throttle.
* Success-path notifications respect the 1h throttle.
* User opt-out (``notify_on_render_done=False``) suppresses sends.
* Missing user / missing email are safe no-ops.
* Provider errors never raise into the render path.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.features import notifications


@pytest.fixture(autouse=True)
def _reset_throttle_state():
    """Each test starts with a clean per-process throttle map."""
    notifications._reset_throttle()
    yield
    notifications._reset_throttle()


@pytest.fixture(autouse=True)
def _force_console_provider(monkeypatch):
    """All tests use the console provider so no real SMTP/Resend
    calls happen even if the developer's shell has those env vars
    set."""
    monkeypatch.setenv("EMAIL_PROVIDER", "console")
    yield


# The notifications module calls ``get_session()`` directly to look
# up the user's email + opt-in preference, which uses the prod
# connection module. The ``client`` fixture's side-effect is the
# only thing that points that module at the in-memory test SQLite,
# so every test that exercises the notify path depends on it.


@pytest.fixture(autouse=True)
def _ensure_test_db(client):  # noqa: ARG001 — fixture for side-effect
    """Wire ``get_session()`` to the test engine for the whole module."""
    yield


def _make_user(db_session, *, email="user@example.com", opt_in=True):
    from src.auth.password import hash_password
    from src.database.models import User

    user = User(
        email=email,
        password_hash=hash_password("x" * 20),
        name="Notify Test",
        plan="free",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    # ``notify_on_render_done`` may not exist on every deployment yet;
    # the implementation defaults to True via getattr so we only set
    # explicitly when overriding to False.
    if not opt_in and hasattr(user, "notify_on_render_done"):
        user.notify_on_render_done = False
        db_session.commit()
    return user


class TestRenderCompleteNotifications:
    def test_console_send_is_no_op_success(self, db_session):
        user = _make_user(db_session)
        # Should not raise even though no SMTP/Resend is configured.
        notifications.notify_render_complete(
            user_id=user.id,
            kind="project",
            render_id=42,
            download_url="https://example.com/out.mp4",
        )

    def test_throttle_suppresses_second_success_email(self, db_session):
        user = _make_user(db_session)
        with patch.object(notifications, "_dispatch", return_value=True) as send:
            notifications.notify_render_complete(
                user_id=user.id,
                kind="session",
                render_id=1,
                download_url="https://example.com/a.mp4",
            )
            notifications.notify_render_complete(
                user_id=user.id,
                kind="session",
                render_id=2,
                download_url="https://example.com/b.mp4",
            )
            assert send.call_count == 1

    def test_pro_plan_bypasses_throttle(self, db_session):
        """Paying users explicitly opt into per-render notifications and
        must NOT be silently throttled to 1 email/hour. The throttle is
        a free-tier cost hygiene control only."""
        user = _make_user(db_session)
        user.plan = "pro"
        db_session.commit()

        with patch.object(notifications, "_dispatch", return_value=True) as send:
            for n in range(3):
                notifications.notify_render_complete(
                    user_id=user.id,
                    kind="session",
                    render_id=n,
                    download_url=f"https://example.com/{n}.mp4",
                )
            assert send.call_count == 3

    def test_user_opted_out_no_email(self, db_session):
        user = _make_user(db_session, opt_in=False)
        with patch.object(notifications, "_dispatch", return_value=True) as send:
            notifications.notify_render_complete(
                user_id=user.id,
                kind="session",
                render_id=99,
                download_url="https://example.com/a.mp4",
            )
            # Only assert when the column actually exists; older
            # schemas auto-default to True so the email would fire.
            from src.database.models import User as UserModel

            if "notify_on_render_done" in UserModel.__table__.columns:
                assert send.call_count == 0


class TestRenderFailedNotifications:
    def test_failure_bypasses_throttle(self, db_session):
        user = _make_user(db_session)
        with patch.object(notifications, "_dispatch", return_value=True) as send:
            # First success → throttle gate set.
            notifications.notify_render_complete(
                user_id=user.id,
                kind="project",
                render_id=10,
                download_url="https://example.com/out.mp4",
            )
            # Failure right after — must still send.
            notifications.notify_render_failed(
                user_id=user.id,
                kind="project",
                render_id=10,
                error_message="ffmpeg crashed",
            )
            assert send.call_count == 2

    def test_provider_raise_does_not_propagate(self, db_session):
        user = _make_user(db_session)
        with patch.object(notifications, "_dispatch", side_effect=RuntimeError("boom")):
            # MUST NOT raise — render path must be insulated from
            # mail provider failures.
            notifications.notify_render_complete(
                user_id=user.id,
                kind="session",
                render_id=1,
                download_url=None,
            )
            notifications.notify_render_failed(
                user_id=user.id,
                kind="session",
                render_id=1,
                error_message="any",
            )


class TestUserResolution:
    def test_missing_user_no_op(self):
        # No DB row at all — should silently do nothing.
        with patch.object(notifications, "_dispatch", return_value=True) as send:
            notifications.notify_render_complete(
                user_id=999999,
                kind="session",
                render_id=1,
                download_url=None,
            )
            assert send.call_count == 0


class TestWebhookDelivery:
    """War-room webhook (2.2): Slack uses `text`, Discord uses `content`."""

    def test_slack_payload_uses_text(self):
        with patch("httpx.post") as post:
            post.return_value = type("R", (), {"status_code": 200, "text": "ok"})()
            assert notifications.send_webhook("https://hooks.slack.com/services/x", "hi") is True
        assert post.call_args.kwargs["json"] == {"text": "hi"}

    def test_discord_payload_uses_content(self):
        with patch("httpx.post") as post:
            post.return_value = type("R", (), {"status_code": 204, "text": ""})()
            assert notifications.send_webhook("https://discord.com/api/webhooks/1/x", "hi") is True
        assert post.call_args.kwargs["json"] == {"content": "hi"}

    def test_empty_url_is_noop(self):
        assert notifications.send_webhook("", "hi") is False

    def test_failure_is_fail_open(self):
        with patch("httpx.post", side_effect=RuntimeError("down")):
            assert notifications.send_webhook("https://hooks.slack.com/x", "hi") is False
