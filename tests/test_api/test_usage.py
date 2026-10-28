"""Tests for ``/usage/renders`` (Week 8).

The endpoint backs the dashboard Quota card. The frontend treats
``unlimited`` as authoritative (Pro/Enterprise plans send
``minutes_limit`` = ``-1`` so the response stays JSON-safe).
"""
from __future__ import annotations


class TestRenderBudgetEndpoint:
    def test_fresh_free_user_sees_zero_used_thirty_cap(
        self, client, auth_headers
    ):
        response = client.get("/usage/renders", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        # Default user fixture is free → 30 min cap, no minutes used.
        assert body["plan"] == "free"
        assert body["minutes_used"] == 0.0
        assert body["minutes_limit"] == 30.0
        assert body["minutes_remaining"] == 30.0
        assert body["unlimited"] is False
        assert body["percent_used"] == 0.0

    def test_pro_user_sees_unlimited_marker(
        self, client, auth_headers, test_user, db_session
    ):
        """Promote the user to Pro and confirm the JSON-safe
        ``unlimited=true`` + ``minutes_limit=-1`` shape."""
        from src.database.models import User

        user = db_session.get(User, test_user["id"])
        user.plan = "pro"
        db_session.commit()

        response = client.get("/usage/renders", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["plan"] == "pro"
        assert body["unlimited"] is True
        # ``-1`` is the agreed sentinel for "infinity" — never raw inf.
        assert body["minutes_limit"] == -1.0
        assert body["minutes_remaining"] == -1.0

    def test_recorded_usage_reflects_in_response(
        self, client, auth_headers, test_user, db_session
    ):
        """Posting a non-zero ``record_render_minutes`` should bump
        ``minutes_used`` and ``percent_used`` in the next snapshot."""
        from src.features.billing.render_budget import record_render_minutes

        record_render_minutes(test_user["id"], 6.0)
        response = client.get("/usage/renders", headers=auth_headers)
        body = response.json()
        assert body["minutes_used"] == 6.0
        assert body["minutes_remaining"] == 24.0
        # 6/30 = 20%
        assert body["percent_used"] == 20.0
