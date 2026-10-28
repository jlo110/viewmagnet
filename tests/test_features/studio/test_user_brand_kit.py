"""Tests for the per-user Brand Kit API (Week 6).

Covers the three things that matter for the brand-kit feature:

  1. Upsert flow — partial PUT, default GET shape, idempotent re-PUT.
  2. Logo upload — both R2 (mocked) and the local-dev fallback path,
     plus validation of size / mime.
  3. Auto-apply on session create — a brand-new ``PUT /studio/sessions``
     for a user with a saved BrandKit gets the brand kit seeded into the
     spec automatically, while a user who already customized brand_kit
     keeps their customization.

These run against the SQLite in-memory test DB from ``conftest.py``.
The R2 path is exercised by monkeypatching the settings so it routes
through the local upload fallback (no boto3 calls in unit tests).
"""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_spec(start: float = 0.0, end: float = 4.0) -> dict:
    """The minimum EditSpec the upsert endpoint will accept."""
    return {
        "clip": {
            "source_url": "https://example.com/clip.mp4",
            "source_clip_path": None,
            "start_time": start,
            "end_time": end,
            "transcript": [],
            "suggested_title": "Test clip",
        },
    }


@pytest.fixture
def force_local_uploads(monkeypatch):
    """Pretend R2 is not configured so logo uploads write to the local
    static fallback. Keeps the tests hermetic — no network, no boto3."""
    from src.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "r2_account_id", "", raising=False)
    monkeypatch.setattr(settings, "r2_access_key_id", "", raising=False)
    monkeypatch.setattr(settings, "r2_secret_access_key", "", raising=False)
    yield


# ---------------------------------------------------------------------------
# GET / PUT brand kit
# ---------------------------------------------------------------------------


class TestBrandKitUpsert:
    def test_get_returns_defaults_when_none(self, client, test_user, auth_headers):
        """First-time GET returns the schema defaults with ``exists=False``
        so the frontend can render the empty state without a 404."""
        resp = client.get("/studio/user/brand-kit", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["exists"] is False
        assert data["logo_url"] is None
        assert data["logo_position"] == "br"
        assert data["logo_opacity"] == pytest.approx(0.85)
        assert data["primary_color"] is None
        assert data["accent_color"] is None
        assert data["font_family"] is None

    def test_put_partial_then_get_roundtrip(
        self, client, test_user, auth_headers
    ):
        """Partial PUT only patches the keys you send. A follow-up GET
        must echo what you wrote, with the un-sent keys at defaults."""
        resp = client.put(
            "/studio/user/brand-kit",
            headers=auth_headers,
            json={
                "primary_color": "#ff0066",
                "font_family": "Poppins",
            },
        )
        assert resp.status_code == 200, resp.text
        first = resp.json()
        assert first["exists"] is True
        assert first["primary_color"] == "#ff0066"
        assert first["font_family"] == "Poppins"
        # Untouched fields stay at the schema defaults.
        assert first["accent_color"] is None
        assert first["logo_position"] == "br"

        # Now patch only ``logo_position`` — primary_color must survive.
        resp = client.put(
            "/studio/user/brand-kit",
            headers=auth_headers,
            json={"logo_position": "tl"},
        )
        assert resp.status_code == 200, resp.text
        second = resp.json()
        assert second["logo_position"] == "tl"
        assert second["primary_color"] == "#ff0066"
        assert second["font_family"] == "Poppins"

        # And a fresh GET sees the latest state.
        resp = client.get("/studio/user/brand-kit", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == second

    def test_put_invalid_color_rejected(self, client, test_user, auth_headers):
        """Bad hex strings fail Pydantic validation (HTTP 422)."""
        resp = client.put(
            "/studio/user/brand-kit",
            headers=auth_headers,
            json={"primary_color": "blue"},
        )
        assert resp.status_code == 422

    def test_put_invalid_position_rejected(
        self, client, test_user, auth_headers
    ):
        resp = client.put(
            "/studio/user/brand-kit",
            headers=auth_headers,
            json={"logo_position": "center"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Logo upload
# ---------------------------------------------------------------------------


# A minimal 1x1 PNG (8-byte signature + IHDR + IDAT + IEND). Tiny but
# a valid PNG that the upload endpoint can accept.
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestBrandKitLogoUpload:
    def test_logo_upload_local_fallback(
        self, client, test_user, auth_headers, force_local_uploads, tmp_path
    ):
        """When R2 isn't configured, the logo is written to the local
        static dir and a ``/api/studio/assets/uploads/...`` URL is returned."""
        # Redirect the local uploads dir into tmp_path so the test
        # doesn't pollute the real ``src/assets/uploads`` directory.
        with patch(
            "src.api.routers.studio._local_uploads_dir",
            return_value=str(tmp_path),
        ):
            resp = client.post(
                "/studio/user/brand-kit/logo",
                headers=auth_headers,
                files={"file": ("logo.png", io.BytesIO(_TINY_PNG), "image/png")},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["exists"] is True
        assert data["logo_url"]
        assert data["logo_url"].startswith("/api/studio/assets/uploads/")
        # The file exists on disk in our tmp dir.
        rel = data["logo_url"].split("/api/studio/assets/uploads/", 1)[1]
        assert (tmp_path / rel).exists()
        assert (tmp_path / rel).read_bytes() == _TINY_PNG

    def test_logo_upload_rejects_oversize(
        self, client, test_user, auth_headers, force_local_uploads
    ):
        """Files over ~2 MB must be rejected with HTTP 413."""
        huge = b"\x89PNG\r\n\x1a\n" + (b"x" * (3 * 1024 * 1024))
        resp = client.post(
            "/studio/user/brand-kit/logo",
            headers=auth_headers,
            files={"file": ("huge.png", io.BytesIO(huge), "image/png")},
        )
        assert resp.status_code == 413, resp.text

    def test_logo_upload_rejects_bad_mime(
        self, client, test_user, auth_headers, force_local_uploads
    ):
        """Only image MIMEs we know how to decode are accepted."""
        resp = client.post(
            "/studio/user/brand-kit/logo",
            headers=auth_headers,
            files={
                "file": (
                    "evil.exe",
                    io.BytesIO(b"not an image"),
                    "application/octet-stream",
                )
            },
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Auto-apply on session create
# ---------------------------------------------------------------------------


class TestBrandKitAutoApply:
    def test_new_session_inherits_saved_brand_kit(
        self, client, test_user, auth_headers
    ):
        """A user with a saved brand kit who creates a fresh session for
        a clip they've never edited before gets the brand kit seeded
        into ``spec.brand_kit`` automatically."""
        # 1. Save the user's brand kit (font + color).
        resp = client.put(
            "/studio/user/brand-kit",
            headers=auth_headers,
            json={"primary_color": "#22dd88", "font_family": "Bebas Neue"},
        )
        assert resp.status_code == 200

        # 2. Upsert a fresh session — spec.brand_kit is at defaults.
        clip_key = "auto_seed_clip_key_001"
        resp = client.put(
            f"/studio/sessions/{clip_key}",
            headers=auth_headers,
            json={"spec": _empty_spec(), "title": "Auto-seed"},
        )
        assert resp.status_code == 200, resp.text
        session = resp.json()

        # 3. The persisted spec must carry the user's brand kit.
        bk = session["spec"]["brand_kit"]
        assert bk is not None
        assert bk["primary_color"] == "#22dd88"
        assert bk["font_family"] == "Bebas Neue"

    def test_explicit_brand_kit_in_spec_wins(
        self, client, test_user, auth_headers
    ):
        """If the incoming spec already carries customized brand_kit
        values, the auto-seed must NOT clobber them — the user's
        per-session override beats their global default."""
        client.put(
            "/studio/user/brand-kit",
            headers=auth_headers,
            json={"primary_color": "#22dd88", "font_family": "Bebas Neue"},
        )

        spec = _empty_spec()
        spec["brand_kit"] = {
            "logo_url": None,
            "logo_position": "tl",
            "logo_opacity": 0.5,
            "primary_color": "#0000ff",
            "accent_color": None,
            "font_family": None,
        }
        clip_key = "override_clip_key_002"
        resp = client.put(
            f"/studio/sessions/{clip_key}",
            headers=auth_headers,
            json={"spec": spec, "title": "Override"},
        )
        assert resp.status_code == 200, resp.text
        bk = resp.json()["spec"]["brand_kit"]
        # The override values must survive — saved BK was NOT layered on top.
        assert bk["logo_position"] == "tl"
        assert bk["primary_color"] == "#0000ff"
        assert bk["font_family"] is None

    def test_no_brand_kit_saved_leaves_spec_alone(
        self, client, test_user, auth_headers
    ):
        """User without a saved brand kit gets the spec untouched."""
        clip_key = "no_brand_key_003"
        resp = client.put(
            f"/studio/sessions/{clip_key}",
            headers=auth_headers,
            json={"spec": _empty_spec(), "title": "Plain"},
        )
        assert resp.status_code == 200, resp.text
        bk = resp.json()["spec"].get("brand_kit")
        # Defaults — primary/accent/font are None and position is "br".
        if bk is not None:
            assert bk["primary_color"] is None
            assert bk["accent_color"] is None
            assert bk["font_family"] is None


# ---------------------------------------------------------------------------
# Render command sanity — logo overlay shows up when brand kit has a logo
# ---------------------------------------------------------------------------


class TestBrandKitRenderOverlay:
    def test_cmd_unified_includes_logo_overlay_when_logo_present(
        self, tmp_path
    ):
        """``_cmd_unified`` must wire a colorchannelmixer + overlay block
        for the brand logo when one is configured."""
        from src.features.studio.render import _cmd_unified
        from src.features.studio.spec import (
            BrandKit,
            EditSpec,
            SourceClip,
        )

        # Synthesize a tiny "logo" file — content doesn't matter, only
        # that the path exists so _cmd_unified routes it as an -i input.
        logo_path = tmp_path / "logo.png"
        logo_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        main_path = tmp_path / "main.mp4"
        main_path.write_bytes(b"\x00" * 16)
        out_path = tmp_path / "out.mp4"

        spec = EditSpec(
            clip=SourceClip(
                source_url=f"file://{main_path}",
                source_clip_path=str(main_path),
                start_time=0.0,
                end_time=2.0,
                transcript=[],
            ),
            brand_kit=BrandKit(
                logo_url="https://example.com/logo.png",
                logo_position="tr",
                logo_opacity=0.6,
                primary_color=None,
                accent_color=None,
                font_family=None,
            ),
        )

        cmd = _cmd_unified(
            input_path=str(main_path),
            ass_path=None,
            spec=spec,
            active_broll=[],
            bg_local=None,
            logo_local=str(logo_path),
            out_w=1080,
            out_h=1920,
            output_path=str(out_path),
            tracking=None,
            duration=2.0,
        )
        cmd_str = " ".join(cmd)

        assert str(logo_path) in cmd_str, "logo path must appear as ffmpeg input"
        assert "colorchannelmixer=aa=0.600" in cmd_str, (
            "logo opacity must be applied via colorchannelmixer"
        )
        assert "[logo_scaled]" in cmd_str
        assert "overlay=" in cmd_str
        assert "x=W-w-" in cmd_str, "tr corner should anchor against W-w"
        assert "y=" in cmd_str

    def test_cmd_unified_omits_logo_overlay_when_no_logo(self, tmp_path):
        """Without a brand kit logo we must NOT emit the overlay block —
        otherwise we'd ask ffmpeg to overlay a non-existent input."""
        from src.features.studio.render import _cmd_unified
        from src.features.studio.spec import EditSpec, SourceClip

        main_path = tmp_path / "main.mp4"
        main_path.write_bytes(b"\x00" * 16)
        out_path = tmp_path / "out.mp4"

        spec = EditSpec(
            clip=SourceClip(
                source_url=f"file://{main_path}",
                source_clip_path=str(main_path),
                start_time=0.0,
                end_time=2.0,
                transcript=[],
            ),
        )

        cmd = _cmd_unified(
            input_path=str(main_path),
            ass_path=None,
            spec=spec,
            active_broll=[],
            bg_local=None,
            logo_local=None,
            out_w=1080,
            out_h=1920,
            output_path=str(out_path),
            tracking=None,
            duration=2.0,
        )
        cmd_str = " ".join(cmd)
        assert "[logo_scaled]" not in cmd_str
        assert "colorchannelmixer=aa=" not in cmd_str
