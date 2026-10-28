"""Tests for the structured Sentry tag plumbing on render failures
(Week 8 Day 5.5).

We don't ship Sentry in the test deps — instead we verify the
``_sentry_capture`` shim:

1. No-ops when ``SENTRY_DSN`` is unset (no import, no raise).
2. When ``SENTRY_DSN`` IS set, every supplied tag (``user_id``,
   ``render_kind``, ``render_id``, ``duration_elapsed_s``, plus any
   extras) reaches ``sentry_sdk.push_scope().set_tag`` BEFORE
   ``capture_exception`` is invoked.
3. Tag values that are ``None`` are dropped (Sentry would coerce to
   the literal string ``"None"`` which makes filtering ugly).
4. A broken ``sentry_sdk`` (e.g. fails to import or raises inside
   capture) does NOT propagate — the worker keeps going.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.queue.client import _sentry_capture, report_render_exception


@pytest.fixture
def fake_sentry(monkeypatch):
    """Install a fake ``sentry_sdk`` module so the shim's lazy import
    finds it without us pulling in the real dep.

    Returns the scope mock so each test can assert on
    ``set_tag`` calls + the recorded exception.
    """
    scope = MagicMock()
    push_scope_cm = MagicMock()
    push_scope_cm.__enter__ = MagicMock(return_value=scope)
    push_scope_cm.__exit__ = MagicMock(return_value=False)

    capture_exception = MagicMock()
    fake = SimpleNamespace(
        push_scope=MagicMock(return_value=push_scope_cm),
        capture_exception=capture_exception,
    )
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.test/1")
    return SimpleNamespace(
        scope=scope, capture_exception=capture_exception, sdk=fake
    )


def test_noop_when_dsn_unset(monkeypatch):
    """Without ``SENTRY_DSN`` we never even import sentry_sdk."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    # If the shim tried to import a non-existent module, that would
    # raise — make sure it doesn't.
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    # Must not raise.
    _sentry_capture(RuntimeError("nope"), user_id=1)


def test_report_render_exception_sets_all_core_tags(fake_sentry):
    err = RuntimeError("ffmpeg exit 1")
    report_render_exception(
        err,
        user_id=42,
        render_kind="project",
        render_id=7,
        duration_elapsed_s=18.3,
        failure_stage="ffmpeg",
    )

    # Every tag we passed should have landed on the scope before
    # capture_exception was called.
    tag_calls = {
        c.args[0]: c.args[1] for c in fake_sentry.scope.set_tag.call_args_list
    }
    assert tag_calls["user_id"] == "42"
    assert tag_calls["render_kind"] == "project"
    assert tag_calls["render_id"] == "7"
    assert tag_calls["duration_elapsed_s"] == "18.3"
    assert tag_calls["failure_stage"] == "ffmpeg"

    # And the exception itself was forwarded.
    assert fake_sentry.capture_exception.called
    assert fake_sentry.capture_exception.call_args.args[0] is err


def test_none_tag_values_are_dropped(fake_sentry):
    """``None`` tag values get filtered out so the Sentry UI doesn't
    show the literal string ``"None"`` as a filterable value."""
    report_render_exception(
        RuntimeError("x"),
        user_id=None,
        render_kind="session",
        render_id=99,
        duration_elapsed_s=None,
    )
    tag_keys = {
        c.args[0] for c in fake_sentry.scope.set_tag.call_args_list
    }
    assert "render_kind" in tag_keys
    assert "render_id" in tag_keys
    assert "user_id" not in tag_keys
    assert "duration_elapsed_s" not in tag_keys


# ---------------------------------------------------------------------------
# Breadcrumbs (P3 polish) — add_render_breadcrumb mirrors the same
# defensive contract as report_render_exception.
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_sentry_breadcrumb(monkeypatch):
    """Install a fake sentry_sdk that only exposes ``add_breadcrumb``."""
    add_breadcrumb = MagicMock()
    fake = SimpleNamespace(add_breadcrumb=add_breadcrumb)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.test/1")
    return SimpleNamespace(add_breadcrumb=add_breadcrumb)


def test_breadcrumb_noop_when_dsn_unset(monkeypatch):
    """Without ``SENTRY_DSN`` we never even try to import the SDK."""
    from src.queue.client import add_render_breadcrumb

    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    # Must not raise.
    add_render_breadcrumb(category="render.cancel", message="x")


def test_breadcrumb_forwards_category_message_data(fake_sentry_breadcrumb):
    """The cancel/retry trail relies on category + structured ``data``
    landing in Sentry so the operator can trace what the user did
    before the eventual exception."""
    from src.queue.client import add_render_breadcrumb

    add_render_breadcrumb(
        category="render.cancel",
        message="user cancelled project render",
        data={"user_id": 42, "render_id": 7, "previous_status": "rendering"},
    )
    assert fake_sentry_breadcrumb.add_breadcrumb.called
    call = fake_sentry_breadcrumb.add_breadcrumb.call_args
    assert call.kwargs["category"] == "render.cancel"
    assert call.kwargs["message"] == "user cancelled project render"
    assert call.kwargs["data"]["user_id"] == 42
    assert call.kwargs["data"]["render_id"] == 7
    assert call.kwargs["data"]["previous_status"] == "rendering"
    assert call.kwargs["level"] == "info"


def test_breadcrumb_drops_none_fields(fake_sentry_breadcrumb):
    """Same hygiene as the exception path — Sentry's UI surfaces
    ``"None"`` literally otherwise."""
    from src.queue.client import add_render_breadcrumb

    add_render_breadcrumb(
        category="render.cancel",
        message="x",
        data={"user_id": 1, "job_id": None, "render_kind": "session"},
    )
    forwarded = fake_sentry_breadcrumb.add_breadcrumb.call_args.kwargs[
        "data"
    ]
    assert "user_id" in forwarded
    assert "render_kind" in forwarded
    assert "job_id" not in forwarded


def test_breadcrumb_swallows_sdk_errors(monkeypatch):
    """If the SDK itself blows up, breadcrumbs must not break the
    cancel request that triggered them."""
    from src.queue.client import add_render_breadcrumb

    monkeypatch.setenv("SENTRY_DSN", "https://x@sentry.test/1")
    bad = SimpleNamespace(
        add_breadcrumb=MagicMock(side_effect=RuntimeError("sdk broken"))
    )
    monkeypatch.setitem(sys.modules, "sentry_sdk", bad)
    # Must not raise.
    add_render_breadcrumb(
        category="render.cancel",
        message="x",
        data={"user_id": 1},
    )


def test_sentry_capture_swallows_internal_errors(monkeypatch):
    """If sentry_sdk itself raises mid-capture, the shim must swallow
    so the worker isn't broken by its observability layer."""
    monkeypatch.setenv("SENTRY_DSN", "https://x@sentry.test/1")
    bad = SimpleNamespace(
        push_scope=MagicMock(side_effect=RuntimeError("sentry is on fire")),
        capture_exception=MagicMock(),
    )
    monkeypatch.setitem(sys.modules, "sentry_sdk", bad)
    # Must not raise.
    report_render_exception(
        RuntimeError("real failure"),
        user_id=1,
        render_kind="session",
        render_id=1,
        duration_elapsed_s=1.0,
    )
