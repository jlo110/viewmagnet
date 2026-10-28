"""Tests for the multi-media-type B-roll search additions:

  - PexelsClient.search_images   → returns StockClip(media_type='image')
  - TenorClient.search_gifs      → returns StockClip(media_type='gif')
  - BRollFinder.search_images / search_gifs dispatch helpers

These tests stub the underlying ``httpx.Client.get`` so they don't hit
any real APIs and don't require ``PEXELS_API_KEY`` / ``TENOR_API_KEY``
to be configured in the test environment.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.features.broll_finder import (
    BRollFinder,
    GiphyClient,
    PexelsClient,
    StockClip,
    TenorClient,
)


# ---------------------------------------------------------------------------
# PexelsClient.search_images
# ---------------------------------------------------------------------------


def _pexels_image_response(n: int = 2) -> dict:
    photos = []
    for i in range(n):
        photos.append({
            "id": 1000 + i,
            "width": 1920,
            "height": 1080,
            "url": f"https://www.pexels.com/photo/{1000+i}/",
            "photographer": "Test Photographer",
            "photographer_url": "https://www.pexels.com/@test",
            "alt": f"Photo {i} caption",
            "src": {
                "original": f"https://images.pexels.com/photos/{1000+i}/orig.jpg",
                "large": f"https://images.pexels.com/photos/{1000+i}/large.jpg",
                "medium": f"https://images.pexels.com/photos/{1000+i}/med.jpg",
                "small": f"https://images.pexels.com/photos/{1000+i}/small.jpg",
                "tiny": f"https://images.pexels.com/photos/{1000+i}/tiny.jpg",
            },
        })
    return {"page": 1, "per_page": n, "photos": photos, "total_results": n}


def test_pexels_search_images_maps_response_to_stockclips():
    client = PexelsClient(api_key="test-key")
    fake_response = MagicMock()
    fake_response.json.return_value = _pexels_image_response(3)
    fake_response.raise_for_status = MagicMock()

    with patch.object(client.client, "get", return_value=fake_response) as get_mock:
        clips = client.search_images("forest", per_page=3)

    assert get_mock.called
    # URL should hit the photo endpoint, not the video one.
    called_url = get_mock.call_args[0][0]
    assert called_url.startswith("/v1/search")
    assert "query=forest" in called_url

    assert len(clips) == 3
    for c in clips:
        assert isinstance(c, StockClip)
        assert c.media_type == "image"
        assert c.source == "pexels"
        assert c.duration == 0  # images are static
        # download_url should prefer ``large`` (or ``original``)
        assert c.download_url.endswith(("/large.jpg", "/orig.jpg"))
        # thumbnail should prefer the smaller variant
        assert "small.jpg" in c.thumbnail_url or "tiny.jpg" in c.thumbnail_url


def test_pexels_search_images_returns_empty_when_no_api_key(monkeypatch):
    # ``api_key=None`` falls back to ``os.getenv`` — unset both candidate
    # vars so the dev .env doesn't leak a real key into the test.
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    client = PexelsClient(api_key=None)
    assert client.api_key is None
    assert client.search_images("anything") == []


def test_pexels_search_images_skips_photos_with_no_src():
    client = PexelsClient(api_key="test-key")
    bad_payload = {
        "photos": [
            {"id": 1, "src": {}, "alt": "no src"},
            {"id": 2, "src": {"large": "https://x/large.jpg"}, "alt": "ok"},
        ],
    }
    fake_response = MagicMock()
    fake_response.json.return_value = bad_payload
    fake_response.raise_for_status = MagicMock()
    with patch.object(client.client, "get", return_value=fake_response):
        clips = client.search_images("x", per_page=2)
    assert len(clips) == 1
    assert clips[0].id == "2"


# ---------------------------------------------------------------------------
# TenorClient.search_gifs
# ---------------------------------------------------------------------------


def _tenor_response(n: int = 2) -> dict:
    results = []
    for i in range(n):
        results.append({
            "id": f"tenor-{i}",
            "title": f"Cool clip {i}",
            "content_description": f"Cool clip {i} description",
            "itemurl": f"https://tenor.com/view/cool-{i}",
            "media_formats": {
                "mp4": {
                    "url": f"https://media.tenor.com/{i}/clip.mp4",
                    "duration": 2.5,
                    "dims": [480, 270],
                    "size": 123456,
                },
                "tinymp4": {
                    "url": f"https://media.tenor.com/{i}/tiny.mp4",
                    "duration": 2.5,
                    "dims": [220, 124],
                },
                "tinygif": {
                    "url": f"https://media.tenor.com/{i}/tiny.gif",
                    "dims": [220, 124],
                },
            },
        })
    return {"results": results, "next": ""}


def test_tenor_search_gifs_maps_response_to_stockclips():
    client = TenorClient(api_key="test-key", client_key="viewmagnet-test")
    fake_response = MagicMock()
    fake_response.json.return_value = _tenor_response(2)
    fake_response.raise_for_status = MagicMock()

    with patch.object(client.client, "get", return_value=fake_response) as get_mock:
        clips = client.search_gifs("minecraft parkour", limit=12)

    assert get_mock.called
    called_url = get_mock.call_args[0][0]
    assert "/v2/search" in called_url
    assert "q=minecraft" in called_url
    assert "client_key=viewmagnet-test" in called_url
    # We restrict media_filter to keep payloads small.
    assert "media_filter" in called_url

    assert len(clips) == 2
    for c in clips:
        assert c.media_type == "gif"
        assert c.source == "tenor"
        # download_url MUST be the MP4 — that's the entire point of using
        # Tenor over Giphy for B-roll compatibility.
        assert c.download_url.endswith(".mp4")
        assert c.duration == 2  # floored from 2.5


def test_tenor_search_gifs_returns_empty_when_no_api_key(monkeypatch):
    monkeypatch.delenv("TENOR_API_KEY", raising=False)
    client = TenorClient(api_key=None)
    assert client.api_key is None
    assert client.search_gifs("anything") == []


def test_tenor_search_gifs_skips_results_with_no_mp4():
    client = TenorClient(api_key="test-key")
    bad_payload = {
        "results": [
            # No mp4 OR tinymp4 → should be skipped, not crash.
            {"id": "a", "media_formats": {"gif": {"url": "https://x/a.gif"}}},
            # Has mp4 → kept.
            {
                "id": "b",
                "media_formats": {
                    "mp4": {"url": "https://x/b.mp4", "dims": [640, 360]},
                },
            },
        ],
    }
    fake_response = MagicMock()
    fake_response.json.return_value = bad_payload
    fake_response.raise_for_status = MagicMock()
    with patch.object(client.client, "get", return_value=fake_response):
        clips = client.search_gifs("x", limit=5)
    assert [c.id for c in clips] == ["b"]


# ---------------------------------------------------------------------------
# BRollFinder dispatch helpers
# ---------------------------------------------------------------------------


def test_brollfinder_search_images_delegates_to_pexels():
    finder = BRollFinder()
    fake = [StockClip(
        id="1", source="pexels", title="t", description="",
        duration=0, width=1, height=1,
        preview_url="", download_url="", thumbnail_url="",
        user="", user_url="", media_type="image",
    )]
    with patch.object(finder.pexels, "search_images", return_value=fake) as m:
        out = finder.search_images("river", max_results=8)
    m.assert_called_once_with("river", per_page=8)
    assert out == fake


def test_brollfinder_search_gifs_delegates_to_tenor_when_pinned():
    finder = BRollFinder()
    fake = [StockClip(
        id="1", source="tenor", title="t", description="",
        duration=2, width=1, height=1,
        preview_url="", download_url="https://x.mp4", thumbnail_url="",
        user="", user_url="", media_type="gif",
    )]
    with patch.object(finder.tenor, "search_gifs", return_value=fake) as m:
        # ``source='tenor'`` pins the provider — skips Giphy entirely.
        out = finder.search_gifs("dance", max_results=6, source="tenor")
    m.assert_called_once_with("dance", limit=6)
    assert out == fake


def test_brollfinder_search_images_ignores_unknown_source():
    finder = BRollFinder()
    # Unknown image source ⇒ empty (don't accidentally hit Pexels).
    assert finder.search_images("river", source="unsplash") == []


def test_brollfinder_search_gifs_ignores_unknown_source():
    finder = BRollFinder()
    assert finder.search_gifs("dance", source="unsplash") == []


# ---------------------------------------------------------------------------
# GiphyClient.search_gifs
# ---------------------------------------------------------------------------


def _giphy_response(n: int = 2) -> dict:
    data = []
    for i in range(n):
        data.append({
            "id": f"giphy-{i}",
            "title": f"Cool clip {i}",
            "url": f"https://giphy.com/gifs/cool-{i}",
            "username": f"user{i}",
            "user": {
                "display_name": f"User {i}",
                "username": f"user{i}",
                "profile_url": f"https://giphy.com/user{i}",
            },
            "images": {
                "original": {
                    "mp4": f"https://media.giphy.com/{i}/giphy.mp4",
                    "url": f"https://media.giphy.com/{i}/giphy.gif",
                    "width": "480",
                    "height": "270",
                    "frames": "60",
                    "mp4_size": "123456",
                },
                "original_still": {
                    "url": f"https://media.giphy.com/{i}/still.jpg",
                },
                "preview_gif": {
                    "url": f"https://media.giphy.com/{i}/preview.gif",
                },
                "looping": {
                    "mp4": f"https://media.giphy.com/{i}/loop.mp4",
                },
            },
        })
    return {"data": data, "pagination": {"count": n}}


def test_giphy_search_gifs_maps_response_to_stockclips():
    client = GiphyClient(api_key="test-key")
    fake_response = MagicMock()
    fake_response.json.return_value = _giphy_response(3)
    fake_response.raise_for_status = MagicMock()

    with patch.object(client.client, "get", return_value=fake_response) as get_mock:
        clips = client.search_gifs("minecraft", limit=12)

    assert get_mock.called
    called_url = get_mock.call_args[0][0]
    assert "/v1/gifs/search" in called_url
    assert "q=minecraft" in called_url
    assert "api_key=test-key" in called_url
    # Rating gate is set explicitly so creator-tool results stay reasonable.
    assert "rating=pg-13" in called_url

    assert len(clips) == 3
    for c in clips:
        assert c.media_type == "gif"
        assert c.source == "giphy"
        # ``download_url`` MUST be the MP4 — drop-in B-roll compatibility.
        assert c.download_url.endswith(".mp4")
        # We pick ``original.mp4`` first; the fixture's ``looping`` variant
        # lives at /loop.mp4 so a fall-through would be detectable here.
        assert "loop.mp4" not in c.download_url
        assert c.width == 480
        assert c.height == 270
        # 60 frames @ 25fps ≈ 2.4s ⇒ int → 2
        assert c.duration == 2


def test_giphy_search_gifs_returns_empty_when_no_api_key(monkeypatch):
    monkeypatch.delenv("GIPHY_API_KEY", raising=False)
    client = GiphyClient(api_key=None)
    assert client.api_key is None
    assert client.search_gifs("anything") == []


def test_giphy_search_gifs_falls_back_through_mp4_variants():
    """When ``original.mp4`` is missing, the picker should walk down the
    preference list and grab the next available MP4 variant."""
    client = GiphyClient(api_key="test-key")
    payload = {
        "data": [
            {
                "id": "1",
                "images": {
                    # ``original`` lacks mp4 → should fall through.
                    "original": {"url": "x.gif", "width": "200", "height": "150"},
                    "looping": {"mp4": "https://x/loop.mp4"},
                },
            },
            {
                "id": "2",
                "images": {
                    # Only ``preview.mp4`` available — last-resort.
                    "preview": {"mp4": "https://x/preview.mp4"},
                },
            },
            {
                # No MP4 anywhere → skipped, not crashed.
                "id": "3",
                "images": {"original": {"url": "y.gif"}},
            },
        ],
    }
    fake_response = MagicMock()
    fake_response.json.return_value = payload
    fake_response.raise_for_status = MagicMock()
    with patch.object(client.client, "get", return_value=fake_response):
        clips = client.search_gifs("x", limit=5)
    assert [c.id for c in clips] == ["1", "2"]
    assert clips[0].download_url.endswith("loop.mp4")
    assert clips[1].download_url.endswith("preview.mp4")


# ---------------------------------------------------------------------------
# BRollFinder.search_gifs provider precedence
# ---------------------------------------------------------------------------


def _stock(source: str, oid: str = "1") -> StockClip:
    return StockClip(
        id=oid, source=source, title="t", description="",
        duration=2, width=1, height=1,
        preview_url="", download_url=f"https://x/{oid}.mp4",
        thumbnail_url="", user="", user_url="", media_type="gif",
    )


def test_brollfinder_search_gifs_prefers_giphy_when_both_keys_set():
    finder = BRollFinder()
    finder.giphy.api_key = "g-key"
    finder.tenor.api_key = "t-key"
    with patch.object(finder.giphy, "search_gifs", return_value=[_stock("giphy", "g1")]) as g, \
         patch.object(finder.tenor, "search_gifs", return_value=[_stock("tenor", "t1")]) as t:
        out = finder.search_gifs("dance", max_results=5)
    g.assert_called_once_with("dance", limit=5)
    t.assert_not_called()
    assert [c.source for c in out] == ["giphy"]


def test_brollfinder_search_gifs_falls_back_to_tenor_when_giphy_empty():
    finder = BRollFinder()
    finder.giphy.api_key = "g-key"
    finder.tenor.api_key = "t-key"
    with patch.object(finder.giphy, "search_gifs", return_value=[]) as g, \
         patch.object(finder.tenor, "search_gifs", return_value=[_stock("tenor", "t1")]) as t:
        out = finder.search_gifs("obscure", max_results=5)
    g.assert_called_once()
    t.assert_called_once_with("obscure", limit=5)
    assert [c.source for c in out] == ["tenor"]


def test_brollfinder_search_gifs_uses_only_tenor_when_giphy_unconfigured():
    finder = BRollFinder()
    finder.giphy.api_key = None
    finder.tenor.api_key = "t-key"
    with patch.object(finder.giphy, "search_gifs") as g, \
         patch.object(finder.tenor, "search_gifs", return_value=[_stock("tenor", "t1")]) as t:
        out = finder.search_gifs("anything", max_results=5)
    g.assert_not_called()
    t.assert_called_once()
    assert [c.source for c in out] == ["tenor"]


def test_brollfinder_search_gifs_pinned_source_skips_fallback():
    finder = BRollFinder()
    finder.giphy.api_key = "g-key"
    finder.tenor.api_key = "t-key"
    # source='tenor' must NOT fall through to Giphy even if Tenor returns []
    with patch.object(finder.giphy, "search_gifs") as g, \
         patch.object(finder.tenor, "search_gifs", return_value=[]) as t:
        out = finder.search_gifs("x", max_results=5, source="tenor")
    g.assert_not_called()
    t.assert_called_once()
    assert out == []
