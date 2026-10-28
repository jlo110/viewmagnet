"""Tests for the project-render budget pre-check (Week 8).

Mirrors the single-clip budget check (which already lives in
``test_studio_render_budget.py``) for the multi-clip Project render
endpoint. The free plan is capped at 30 render-minutes/UTC-month; a
project's projected minutes is the sum of per-clip effective
durations.

Each test exercises the structured 402 ``render_budget_exceeded``
payload the frontend's paywall handler keys off of.
"""
from __future__ import annotations

import pytest


def _seed_session(db_session, user_id: int, clip_key: str, duration_seconds: float):
    """Insert an EditSession with a known source window so the
    project's projected render minutes are deterministic."""
    from src.database.models import EditSession

    s = EditSession(
        user_id=user_id,
        clip_key=clip_key,
        source_video_url="https://example.com/v.mp4",
        source_clip_index=0,
        source_start_time=0.0,
        source_end_time=float(duration_seconds),
        title=f"Clip {clip_key}",
        spec="{}",
    )
    db_session.add(s)
    db_session.commit()
    return s.id


def _make_project_with_clips(client, db_session, auth_headers, user_id, durations):
    """Create a project and append clips of the requested durations
    (in seconds). Returns the project id."""
    resp = client.post(
        "/studio/projects",
        json={"title": "Budget test project", "default_aspect": "9:16"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]
    for i, dur in enumerate(durations):
        sid = _seed_session(db_session, user_id, f"clipkey_{project_id}_{i}", dur)
        r = client.post(
            f"/studio/projects/{project_id}/clips",
            json={"edit_session_id": sid},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
    return project_id


class TestProjectRenderBudget:
    def test_within_budget_starts_render(
        self, client, auth_headers, test_user, db_session
    ):
        # 2 × 30s clips = 1 minute projected; free's 30-min cap holds.
        project_id = _make_project_with_clips(
            client, db_session, auth_headers, test_user["id"], [30.0, 30.0]
        )
        r = client.post(
            f"/studio/projects/{project_id}/render", headers=auth_headers
        )
        # In sync-fallback mode the render itself may fail (no ffmpeg /
        # network / R2), but the budget check must pass — anything in
        # the 2xx-or-5xx-but-not-402 range is acceptable; 402 means
        # the gate fired which is wrong.
        assert r.status_code != 402

    def test_project_exceeding_budget_rejects_with_structured_402(
        self, client, auth_headers, test_user, db_session
    ):
        # 35 min projected vs 30-min free cap → must reject.
        project_id = _make_project_with_clips(
            client, db_session, auth_headers, test_user["id"], [35 * 60.0]
        )
        r = client.post(
            f"/studio/projects/{project_id}/render", headers=auth_headers
        )
        assert r.status_code == 402, r.text
        body = r.json()
        # ``install_error_handlers`` wraps the structured payload
        # the router raised inside ``error.details`` (and surfaces
        # the human ``message`` at the envelope top level).
        details = body["error"]["details"]
        assert details["error"] == "render_budget_exceeded"
        assert details["minutes_limit"] == pytest.approx(30.0)
        assert details["projected_minutes"] >= 30.0
        assert "minutes_remaining" in details

    def test_pro_plan_never_hits_budget_gate(
        self, client, auth_headers, test_user, db_session
    ):
        # Promote the user to Pro and confirm the gate doesn't fire
        # even on a huge projected window.
        from src.database.models import User

        user = db_session.get(User, test_user["id"])
        user.plan = "pro"
        db_session.commit()

        project_id = _make_project_with_clips(
            client, db_session, auth_headers, test_user["id"], [120 * 60.0]
        )
        r = client.post(
            f"/studio/projects/{project_id}/render", headers=auth_headers
        )
        assert r.status_code != 402, r.text

    def test_transition_overlap_reduces_projected_minutes(
        self, client, auth_headers, test_user, db_session
    ):
        """A user with just-enough budget left for the post-overlap
        output should not be falsely rejected by a project whose
        pre-overlap sum exceeds the cap. Two 60s clips with a 1s
        crossfade should render as 119s total (1.983 min), comfortably
        inside a 2-min remaining budget — even though the naive sum
        is exactly 2.0 min."""
        from src.database.models import StudioProject
        from src.features.billing.render_budget import record_render_minutes
        from src.features.studio.spec import TransitionType

        # Burn ~28 of the 30 free minutes so only ~2 min remain.
        record_render_minutes(test_user["id"], 28.0)

        project_id = _make_project_with_clips(
            client, db_session, auth_headers, test_user["id"], [60.0, 60.0]
        )
        # Configure the project with a 1000ms crossfade so the second
        # clip overlaps the first by a full second.
        project = db_session.get(StudioProject, project_id)
        project.default_transition_type = TransitionType.DISSOLVE.value
        project.default_transition_ms = 1000
        db_session.commit()

        r = client.post(
            f"/studio/projects/{project_id}/render", headers=auth_headers
        )
        # Pre-fix this would have been 402 (naive sum = 2.0 min and
        # remaining ~= 2.0 min triggers the > check in some snapshots).
        # Post-fix the projection is 1.983 min, well under the cap.
        assert r.status_code != 402, r.text
