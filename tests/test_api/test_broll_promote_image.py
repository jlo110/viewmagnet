"""Unit tests for the image → MP4 promotion helper used by
``POST /broll/promote-image``.

We test ``_promote_image_sync`` directly (synchronous worker) so we don't
need to spin up the FastAPI app + auth fixtures. The endpoint itself is
a thin ``asyncio.to_thread`` wrapper around it.
"""
from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

import pytest

from src.api.routers import broll as broll_router


@pytest.fixture
def tmp_cache_dir(tmp_path, monkeypatch):
    """Redirect the module-level cache dir to a pytest tmp_path so tests
    don't pollute the real ``src/assets/image-cache`` directory."""
    cache = tmp_path / "image-cache"
    cache.mkdir()
    monkeypatch.setattr(broll_router, "_IMAGE_CACHE_DIR", str(cache))
    return cache


def test_cache_key_is_stable_and_url_sensitive():
    a = broll_router._cache_key_for("https://x/a.jpg", 4.0)
    b = broll_router._cache_key_for("https://x/a.jpg", 4.0)
    c = broll_router._cache_key_for("https://x/b.jpg", 4.0)
    d = broll_router._cache_key_for("https://x/a.jpg", 6.0)
    assert a == b, "same inputs must hash to same key"
    assert a != c, "different URL must hash differently"
    assert a != d, "different duration must hash differently"
    assert len(a) == 16


def test_promote_image_returns_cached_when_mp4_exists(tmp_cache_dir):
    """If the MP4 already exists in the cache, we skip the download +
    ffmpeg encode entirely and return cached=True."""
    url = "https://example.com/photo.jpg"
    duration = 4.0
    key = broll_router._cache_key_for(url, duration)
    mp4_path = tmp_cache_dir / f"{key}.mp4"
    mp4_path.write_bytes(b"\x00" * 2048)  # >1KB so the size guard passes

    with patch.object(broll_router, "_download_image") as dl_mock, \
         patch.object(broll_router, "_encode_still_to_mp4") as enc_mock:
        out = broll_router._promote_image_sync(url, duration)

    dl_mock.assert_not_called()
    enc_mock.assert_not_called()
    assert out["cached"] is True
    assert out["download_url"].endswith(f"/{key}.mp4")
    assert out["duration_seconds"] == duration


def test_promote_image_downloads_and_encodes_on_first_use(tmp_cache_dir):
    url = "https://example.com/photo.jpg"
    duration = 5.0
    key = broll_router._cache_key_for(url, duration)
    expected_mp4 = tmp_cache_dir / f"{key}.mp4"

    def fake_download(dl_url, dest_path):
        # Simulate a successful image download — drop a placeholder src file.
        with open(dest_path, "wb") as f:
            f.write(b"PNG\x00\x00\x00fake")
        return dest_path

    def fake_encode(image_path, mp4_path, duration_seconds):
        # ``_encode_still_to_mp4`` would shell out to ffmpeg; here we just
        # write a non-empty file so the function looks like it succeeded.
        with open(mp4_path, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42")

    with patch.object(broll_router, "_download_image", side_effect=fake_download) as dl_mock, \
         patch.object(broll_router, "_encode_still_to_mp4", side_effect=fake_encode) as enc_mock:
        out = broll_router._promote_image_sync(url, duration)

    dl_mock.assert_called_once()
    enc_mock.assert_called_once()
    assert expected_mp4.exists()
    # Source image must be cleaned up after a successful encode.
    assert not (tmp_cache_dir / f"{key}.src").exists()
    assert out["cached"] is False
    assert out["download_url"].endswith(f"/{key}.mp4")


def test_promote_image_cleans_up_source_on_encode_failure(tmp_cache_dir):
    """If the ffmpeg encode raises, we still wipe the .src file so the
    cache dir doesn't accumulate orphan downloads."""
    url = "https://example.com/broken.jpg"
    duration = 4.0
    key = broll_router._cache_key_for(url, duration)

    def fake_download(dl_url, dest_path):
        with open(dest_path, "wb") as f:
            f.write(b"corrupt")
        return dest_path

    from fastapi import HTTPException

    with patch.object(broll_router, "_download_image", side_effect=fake_download), \
         patch.object(broll_router, "_encode_still_to_mp4",
                       side_effect=HTTPException(status_code=500, detail="boom")):
        with pytest.raises(HTTPException):
            broll_router._promote_image_sync(url, duration)

    assert not (tmp_cache_dir / f"{key}.src").exists()
    assert not (tmp_cache_dir / f"{key}.mp4").exists()


def test_configured_stock_sources_branches_by_media_type(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "x")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.delenv("GIPHY_API_KEY", raising=False)
    monkeypatch.delenv("TENOR_API_KEY", raising=False)
    assert broll_router._configured_stock_sources("video") == ["pexels"]
    assert broll_router._configured_stock_sources("image") == ["pexels"]
    assert broll_router._configured_stock_sources("gif") == []

    monkeypatch.setenv("TENOR_API_KEY", "y")
    assert broll_router._configured_stock_sources("gif") == ["tenor"]

    # Giphy should be listed first when both GIF providers are configured
    # — mirrors the BRollFinder.search_gifs preference order.
    monkeypatch.setenv("GIPHY_API_KEY", "z")
    assert broll_router._configured_stock_sources("gif") == ["giphy", "tenor"]

    monkeypatch.delenv("TENOR_API_KEY")
    assert broll_router._configured_stock_sources("gif") == ["giphy"]

    monkeypatch.delenv("PEXELS_API_KEY")
    assert broll_router._configured_stock_sources("video") == []
    assert broll_router._configured_stock_sources("image") == []
