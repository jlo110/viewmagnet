"""Tests for the ``/impact/summary`` endpoint.

The endpoint must:

* Always return 200 (the UI uses the response shape to decide
  whether to render the locked / unlocked surfaces).
* Report ``ready=False`` until the user clears *both* readiness gates
  (``MIN_VIDEOS_FOR_IMPACT`` analyses **and** ``MIN_DAYS_FOR_IMPACT``
  days of history).
* Split analyses into "before" / "after" cohorts and surface the lift
  as ``change`` / ``change_percent`` per metric.

We rely on the dashboard test fixtures (``client``, ``test_user``,
``auth_headers``, ``db_session``) defined in ``tests/conftest.py``.
"""
from __future__ import annotations

from datetime import datetime, timedelta


class TestImpactSummary:
    def _seed_analyses(
        self,
        db_session,
        user_id: int,
        scores: list[float],
        days_ago_first: int = 0,
    ) -> None:
        """Insert ``len(scores)`` analyses for ``user_id`` spread evenly
        between ``days_ago_first`` days ago and now."""
        from src.database.models import UserVideoAnalysis

        n = len(scores)
        for i, score in enumerate(scores):
            offset_days = days_ago_first * (1 - i / max(n - 1, 1))
            db_session.add(
                UserVideoAnalysis(
                    user_id=user_id,
                    video_id=f"vid_{i}",
                    video_url=f"https://youtube.com/watch?v=vid_{i}",
                    title=f"Test {i}",
                    prediction_score=score,
                    prediction_tier="high" if score >= 70 else "medium",
                    title_score=score - 5,
                    thumbnail_score=score - 10,
                    analyzed_at=datetime.utcnow() - timedelta(days=offset_days),
                )
            )
        db_session.commit()

    def test_summary_for_user_with_no_history_is_not_ready(
        self, client, auth_headers
    ):
        """Empty history → ``ready=False`` and empty lists so the UI
        keeps the unlock card up."""
        response = client.get("/impact/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is False
        assert data["video_count"] == 0
        assert data["days_of_history"] == 0
        assert data["metrics"] == []
        assert data["videos"] == []
        assert data["trend"] == []

    def test_summary_below_video_threshold_is_not_ready(
        self, client, auth_headers, db_session, test_user
    ):
        """Even with 30+ days of history, fewer than ``MIN_VIDEOS_FOR_IMPACT``
        analyses keeps the user on the locked surface."""
        self._seed_analyses(
            db_session,
            test_user["id"],
            scores=[55.0, 60.0, 65.0],
            days_ago_first=45,
        )
        response = client.get("/impact/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is False
        assert data["video_count"] == 3

    def test_summary_below_days_threshold_is_not_ready(
        self, client, auth_headers, db_session, test_user
    ):
        """Even with 5+ videos, less than 30 days of history keeps the
        user locked — the cohort split would otherwise be meaningless."""
        self._seed_analyses(
            db_session,
            test_user["id"],
            scores=[55.0, 60.0, 65.0, 70.0, 75.0, 80.0],
            days_ago_first=5,
        )
        response = client.get("/impact/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is False

    def test_summary_when_unlocked_computes_lift(
        self, client, auth_headers, db_session, test_user
    ):
        """6 videos, 60 days of history — the user is unlocked and we
        should see real before/after metrics with positive lift on
        prediction_score (50 → 80)."""
        self._seed_analyses(
            db_session,
            test_user["id"],
            # First three at ~50, last three at ~80 → after-cohort lift
            scores=[50.0, 50.0, 50.0, 80.0, 80.0, 80.0],
            days_ago_first=60,
        )
        response = client.get("/impact/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert data["video_count"] == 6

        # Find the prediction-score metric and verify the lift math.
        scores = [m for m in data["metrics"] if m["name"] == "Prediction Score"]
        assert scores, "expected a Prediction Score metric"
        m = scores[0]
        assert m["before"] == 50.0
        assert m["after"] == 80.0
        assert m["change"] == 30.0
        assert m["change_percent"] == 60.0

        # Trend should have one point per analysis.
        assert len(data["trend"]) == 6
        # And the videos table should likewise be fully populated.
        assert len(data["videos"]) == 6
