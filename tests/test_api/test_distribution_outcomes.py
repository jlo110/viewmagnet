"""Integration tests for the Week 10 outcomes endpoint
(``GET /distribution/outcomes``) and the Studio CTA-provenance
upsert path that feeds it.

These exercise the full FastAPI request → SQLAlchemy → response
shape so we catch wiring drift the unit-test layer wouldn't see
(e.g. forgetting to serialize ``cta_provenance`` from the row).
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest


def _add_published(
    db_session,
    user_id: int,
    *,
    source_video_url: str | None = None,
    platform: str = "youtube",
    posted_id: str = "abc",
):
    """Seed a DistributionJob + successful DistributionResult so the
    endpoint has something to roll up."""
    from src.database.models import DistributionJob, DistributionResult

    job = DistributionJob(
        user_id=user_id,
        title="A published clip",
        source_video_url=source_video_url,
        target_count=1,
        success_count=1,
        failure_count=0,
    )
    db_session.add(job)
    db_session.flush()
    result = DistributionResult(
        job_id=job.id,
        account_id=1,
        platform=platform,
        status="success",
        posted_id=posted_id,
        posted_url=f"https://{platform}.example/{posted_id}",
        completed_at=datetime.utcnow(),
    )
    db_session.add(result)
    db_session.commit()
    db_session.refresh(result)
    return job, result


def _add_snapshot(
    db_session,
    *,
    result_id: int,
    user_id: int,
    platform: str,
    window_key: str,
    views: int,
    likes: int = 0,
    comments: int = 0,
    avg_view_percentage: float | None = None,
):
    from src.database.models import PublishedMetricSnapshot

    snap = PublishedMetricSnapshot(
        distribution_result_id=result_id,
        user_id=user_id,
        platform=platform,
        window_key=window_key,
        published_at=datetime.utcnow(),
        sampled_at=datetime.utcnow(),
        views=views,
        likes=likes,
        comments=comments,
        avg_view_percentage=avg_view_percentage,
    )
    db_session.add(snap)
    db_session.commit()


class TestOutcomesEndpoint:
    """End-to-end behavior of ``GET /distribution/outcomes``."""

    def test_empty_response_when_user_has_not_published(
        self, client, auth_headers
    ):
        """Brand-new user → 200 + empty arrays (NOT 404). The
        frontend uses this shape to render the "publish your first
        video" empty state."""
        response = client.get(
            "/distribution/outcomes", headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body == {
            "outcomes": [],
            "recommendation_effectiveness": [],
        }

    def test_returns_outcomes_with_snapshots(
        self, client, auth_headers, db_session, test_user
    ):
        _, result = _add_published(db_session, test_user["id"])
        _add_snapshot(
            db_session,
            result_id=result.id,
            user_id=test_user["id"],
            platform="youtube",
            window_key="24h",
            views=1000,
            likes=120,
            comments=15,
            avg_view_percentage=72.5,
        )

        response = client.get(
            "/distribution/outcomes", headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["outcomes"]) == 1
        outcome = body["outcomes"][0]
        assert outcome["platform"] == "youtube"
        assert outcome["latest"]["window_key"] == "24h"
        assert outcome["latest"]["views"] == 1000
        # Snapshots keyed by window_key so the UI can render columns
        # without re-sorting.
        assert "24h" in outcome["snapshots"]

    def test_attribution_flows_through_to_response(
        self, client, auth_headers, db_session, test_user
    ):
        """An EditSession with cta_provenance for the same source URL
        should attach the provenance to the outcome row."""
        from src.database.models import EditSession

        source_url = "https://r2.example.com/rendered.mp4"
        session = EditSession(
            user_id=test_user["id"],
            clip_key="prov_session_xyz_abc",
            source_video_url=source_url,
            source_clip_index=0,
            spec="{}",
            cta_provenance=json.dumps(
                {"tool": "hook_lab", "from": "analyzer"}
            ),
        )
        db_session.add(session)
        db_session.commit()

        _add_published(
            db_session,
            test_user["id"],
            source_video_url=source_url,
            posted_id="cta_link",
        )

        response = client.get(
            "/distribution/outcomes", headers=auth_headers
        )
        assert response.status_code == 200
        outcome = response.json()["outcomes"][0]
        assert outcome["cta_provenance"] == {
            "tool": "hook_lab",
            "from": "analyzer",
        }

    def test_user_isolation(
        self, client, auth_headers, db_session, test_user
    ):
        """Another user's publishes must NOT leak through. Without
        this assertion a missing ``user_id`` filter would silently
        cross-pollute outcomes between accounts."""
        # Insert a publish for user 9999 (NOT the auth user).
        _add_published(db_session, 9999, posted_id="not_yours")
        # And one for the auth user we want to see.
        _add_published(
            db_session, test_user["id"], posted_id="yours"
        )

        response = client.get(
            "/distribution/outcomes", headers=auth_headers
        )
        body = response.json()
        urls = [o["posted_url"] for o in body["outcomes"]]
        assert any("yours" in u for u in urls if u)
        assert not any("not_yours" in u for u in urls if u)


class TestStudioCtaProvenancePersistence:
    """The PUT /studio/sessions/:clipKey endpoint should stamp the
    CTA on first save and respect first-attribution-wins on
    subsequent saves."""

    def _put_session(
        self,
        client,
        auth_headers,
        *,
        clip_key: str,
        cta_provenance: dict | None,
    ) -> dict:
        body = {
            "title": "T",
            "spec": {
                "clip": {
                    "source_url": "https://example.com/v.mp4",
                    "source_clip_path": None,
                    "start_time": 0,
                    "end_time": 10,
                    "suggested_title": "X",
                    "transcript": [],
                },
            },
        }
        if cta_provenance is not None:
            body["cta_provenance"] = cta_provenance
        response = client.put(
            f"/studio/sessions/{clip_key}",
            json=body,
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        return response.json()

    def test_first_save_with_cta_persists_provenance(
        self, client, auth_headers
    ):
        body = self._put_session(
            client,
            auth_headers,
            clip_key="cta_test_first_001",
            cta_provenance={
                "tool": "hook_lab",
                "from": "analyzer",
            },
        )
        assert body["cta_provenance"] == {
            "tool": "hook_lab",
            "from": "analyzer",
        }

    def test_subsequent_save_without_cta_keeps_first(
        self, client, auth_headers
    ):
        """A debounced autosave that doesn't include the CTA must
        not clobber the originally-attributed recommendation. This
        is the bug we'd see if an autosave 10 minutes after entry
        wiped the first attribution to ``None``."""
        self._put_session(
            client,
            auth_headers,
            clip_key="cta_test_keep_002",
            cta_provenance={"tool": "script_writer"},
        )
        # Second save — no CTA payload.
        body = self._put_session(
            client,
            auth_headers,
            clip_key="cta_test_keep_002",
            cta_provenance=None,
        )
        assert body["cta_provenance"] == {"tool": "script_writer"}

    def test_subsequent_save_with_different_cta_does_not_overwrite(
        self, client, auth_headers
    ):
        """First-attribution-wins: if a user re-opens the same clip
        via a different CTA later, the originally-attributed tool
        stays. Otherwise the post-publish rollup would conflate
        cohorts."""
        self._put_session(
            client,
            auth_headers,
            clip_key="cta_test_first_wins_003",
            cta_provenance={"tool": "hook_lab"},
        )
        body = self._put_session(
            client,
            auth_headers,
            clip_key="cta_test_first_wins_003",
            cta_provenance={"tool": "script_writer"},
        )
        assert body["cta_provenance"] == {"tool": "hook_lab"}

    def test_save_without_any_cta_is_unattributed(
        self, client, auth_headers
    ):
        body = self._put_session(
            client,
            auth_headers,
            clip_key="cta_test_none_004",
            cta_provenance=None,
        )
        assert body["cta_provenance"] is None
