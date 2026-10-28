"""Tests for ``POST /scripts/to-project`` — Week 9 Connected Tools.

The endpoint scaffolds a multi-clip Studio Project from a generated
script. The integration is high-leverage but easy to subtly break:

  * Each script section MUST become a placeholder clip (no skipped
    sections; ordering preserved).
  * Placeholder source URLs MUST use the ``placeholder://`` scheme so
    the frontend ``isPlaceholderSource`` detection short-circuits the
    ``<video>`` element instead of trying to fetch.
  * The script text MUST land in ``EditSpec.notes`` so it shows up in
    the editor sidebar as a teleprompter — without this the whole
    "structure preserved" promise of the handoff is broken.
  * Clip keys MUST be unique per (user, source_url+position) to satisfy
    the EditSession ``uq_edit_session_user_clip`` constraint, even when
    sections share the same name.
"""
from __future__ import annotations

import json

import pytest


def _post_script_to_project(client, auth_headers, **overrides):
    payload = {
        "title": "From-script project",
        "sections": [
            {"name": "Hook", "content": "Punchy opening line", "duration_seconds": 8},
            {
                "name": "Problem",
                "content": "Here's the thing most people get wrong...",
                "duration_seconds": 45,
            },
            {"name": "CTA", "content": "Subscribe for part 2!", "duration_seconds": 10},
        ],
        "default_aspect": "9:16",
    }
    payload.update(overrides)
    return client.post("/scripts/to-project", json=payload, headers=auth_headers)


class TestScriptToProjectCreation:
    def test_creates_project_with_one_clip_per_section(
        self, client, auth_headers
    ):
        response = _post_script_to_project(client, auth_headers)
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["title"] == "From-script project"
        assert data["default_aspect"] == "9:16"
        assert len(data["clips"]) == 3, "one project clip per script section"
        # Position must be 0-indexed and contiguous so the rail renders
        # in source order.
        assert [c["position"] for c in data["clips"]] == [0, 1, 2]

    def test_preserves_section_order_via_titles(self, client, auth_headers):
        response = _post_script_to_project(client, auth_headers)
        assert response.status_code == 201
        clips = response.json()["clips"]
        assert [c["title"] for c in clips] == ["Hook", "Problem", "CTA"]

    def test_clip_durations_match_section_estimates(
        self, client, auth_headers
    ):
        response = _post_script_to_project(client, auth_headers)
        assert response.status_code == 201
        clips = response.json()["clips"]
        durations = [
            round(c["source_end_time"] - c["source_start_time"]) for c in clips
        ]
        assert durations == [8, 45, 10]

    def test_each_clip_has_placeholder_source_url(
        self, client, auth_headers
    ):
        """Without the ``placeholder://`` scheme the frontend can't
        detect the empty-footage state and the editor renders a
        broken video element. This test is the lock-in."""
        response = _post_script_to_project(client, auth_headers)
        assert response.status_code == 201
        for clip in response.json()["clips"]:
            assert clip["source_url"].startswith("placeholder://"), (
                f"clip {clip['title']!r} source_url={clip['source_url']!r} "
                f"is not a placeholder; frontend can't render it"
            )

    def test_clip_keys_are_unique(self, client, auth_headers):
        """Same script run shouldn't crash on the unique
        ``(user_id, clip_key)`` index when sections share a name."""
        response = client.post(
            "/scripts/to-project",
            json={
                "title": "Dup-section project",
                "sections": [
                    {"name": "Section", "content": "A", "duration_seconds": 5},
                    {"name": "Section", "content": "B", "duration_seconds": 5},
                    {"name": "Section", "content": "C", "duration_seconds": 5},
                ],
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        clip_keys = [c["clip_key"] for c in response.json()["clips"]]
        assert len(clip_keys) == len(set(clip_keys)), (
            f"duplicate clip keys: {clip_keys}"
        )


class TestScriptToProjectSpecPayload:
    def test_section_content_lands_in_edit_session_notes(
        self, client, auth_headers, db_session
    ):
        """The teleprompter / creator-notes integration is the whole
        point of the handoff; without it the user has to re-type the
        script into the editor."""
        from src.database.models import EditSession

        response = _post_script_to_project(client, auth_headers)
        assert response.status_code == 201
        clips = response.json()["clips"]
        for clip, expected_content in zip(
            clips,
            ["Punchy opening line", "Here's the thing most people get wrong...", "Subscribe for part 2!"],
        ):
            session = (
                db_session.query(EditSession)
                .filter(EditSession.id == clip["edit_session_id"])
                .one()
            )
            spec = json.loads(session.spec)
            assert spec.get("notes") == expected_content, (
                f"clip {clip['title']!r}: expected notes={expected_content!r} "
                f"got {spec.get('notes')!r}"
            )

    def test_records_framework_provenance(
        self, client, auth_headers, db_session
    ):
        """When the script came from a framework the project clips
        should carry it through for downstream analytics + UX hints."""
        from src.database.models import EditSession

        response = _post_script_to_project(
            client, auth_headers, framework="hype_heit"
        )
        assert response.status_code == 201
        first = response.json()["clips"][0]
        session = (
            db_session.query(EditSession)
            .filter(EditSession.id == first["edit_session_id"])
            .one()
        )
        spec = json.loads(session.spec)
        assert spec.get("script_section_meta", {}).get("framework") == "hype_heit"


class TestScriptToProjectDescriptionSeed:
    """The Distribution Hub handoff relies on the project description
    being pre-filled with something useful — without it the publish
    caption starts blank every time and the whole "connected" promise
    falls apart for project renders."""

    def test_description_assembled_from_section_content(
        self, client, auth_headers
    ):
        response = _post_script_to_project(client, auth_headers)
        assert response.status_code == 201
        description = response.json().get("description") or ""
        # Each section's name and content should make it into the
        # description so the publish caption has structure (not just
        # one big paragraph).
        for name in ("Hook", "Problem", "CTA"):
            assert name in description, (
                f"section name {name!r} missing from description: {description!r}"
            )
        assert "Punchy opening line" in description
        assert "Subscribe for part 2!" in description

    def test_truncates_overly_long_sections(self, client, auth_headers):
        long_content = "A" * 1000
        response = client.post(
            "/scripts/to-project",
            json={
                "title": "Long sections",
                "sections": [
                    {"name": "Hook", "content": long_content, "duration_seconds": 30},
                ],
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        description = response.json().get("description") or ""
        # Per-section snippet caps at ~280 chars; we should see an
        # ellipsis indicator, not the full 1000-char string.
        assert "..." in description
        assert len(description) < 1000


class TestScriptToProjectValidation:
    def test_rejects_empty_section_list(self, client, auth_headers):
        response = client.post(
            "/scripts/to-project",
            json={"title": "Empty", "sections": []},
            headers=auth_headers,
        )
        assert response.status_code == 422  # Pydantic min_length=1

    def test_rejects_too_many_sections(self, client, auth_headers):
        sections = [
            {"name": f"S{i}", "content": "", "duration_seconds": 5}
            for i in range(25)
        ]
        response = client.post(
            "/scripts/to-project",
            json={"title": "Too many", "sections": sections},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "too many" in response.text.lower()

    def test_clamps_section_duration_to_safe_range(
        self, client, auth_headers, db_session
    ):
        """Out-of-range durations should fail validation, not silently
        truncate. Locks in the Pydantic ``ge``/``le`` bounds."""
        response = client.post(
            "/scripts/to-project",
            json={
                "title": "Bad dur",
                "sections": [
                    {"name": "Way too long", "content": "", "duration_seconds": 1_000_000}
                ],
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_requires_authentication(self, client):
        response = client.post(
            "/scripts/to-project",
            json={
                "title": "No auth",
                "sections": [{"name": "S", "content": "x", "duration_seconds": 5}],
            },
        )
        assert response.status_code in (401, 403)
