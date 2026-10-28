"""Unit tests for ``src.features.studio.source_proxy``.

The HTTP endpoint is exercised by the dashboard integration tests; here
we only verify the pure logic — URL classification, the YouTube
download routing, and the cache filename derivation. The actual
download / ffmpeg paths are mocked so the test suite stays hermetic.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from src.features.studio import source_proxy as sp


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", True),
        ("https://youtu.be/dQw4w9WgXcQ", True),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", True),
        ("https://r2.example.com/clip.mp4", False),
        ("https://pexels.com/video/foo.mp4", False),
        ("", False),
        (None, False),
    ],
)
def test_is_youtube_url(url, expected):
    assert sp.is_youtube_url(url) is expected


def test_cache_filename_is_stable_per_url(tmp_path, monkeypatch):
    """Same URL should always hash to the same cache filename so two
    concurrent requests dedupe via the per-URL lock."""
    monkeypatch.setattr(sp, "CACHE_DIR", tmp_path)
    name_a = sp.cache_path_for("https://example.com/a.mp4").name
    name_b = sp.cache_path_for("https://example.com/a.mp4").name
    assert name_a == name_b
    assert name_a.endswith(".mp4")


def test_cache_filename_differs_per_url(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "CACHE_DIR", tmp_path)
    assert (
        sp.cache_path_for("https://example.com/a.mp4").name
        != sp.cache_path_for("https://example.com/b.mp4").name
    )


def test_get_normalized_source_routes_youtube_through_ytdlp(tmp_path, monkeypatch):
    """YouTube URLs must go through ``_ytdlp_download``; other URLs
    must go through ``_stream_download``. This is the bug-prevention
    test for the 'Re-edit in Studio' flow — if we accidentally try
    to httpx-stream a watch page we get an HTML body, not a video."""
    monkeypatch.setattr(sp, "CACHE_DIR", tmp_path)

    def fake_ytdlp(url: str, dest_dir: Path) -> Path:
        out = dest_dir / "yt.mp4"
        out.write_bytes(b"moov" + b"\x00" * (1 << 16))  # appears faststart
        return out

    def fail_stream(url: str, dest: Path) -> int:
        raise AssertionError("_stream_download must not be called for YT URLs")

    monkeypatch.setattr(sp, "_ytdlp_download", fake_ytdlp)
    monkeypatch.setattr(sp, "_stream_download", fail_stream)
    monkeypatch.setattr(sp, "needs_normalization", lambda _p: False)

    result = sp.get_normalized_source("https://youtu.be/abc12345678")
    assert result.exists()
    assert result.read_bytes().startswith(b"moov")


def test_get_normalized_source_routes_direct_url_through_httpx(tmp_path, monkeypatch):
    """Direct MP4 URLs must NOT go through yt_dlp — that would
    needlessly invoke a heavy binary and break offline test runs."""
    monkeypatch.setattr(sp, "CACHE_DIR", tmp_path)

    def fail_ytdlp(url: str, dest_dir: Path) -> Path:
        raise AssertionError("_ytdlp_download must not be called for direct URLs")

    def fake_stream(url: str, dest: Path) -> int:
        dest.write_bytes(b"moov" + b"\x00" * (1 << 16))
        return dest.stat().st_size

    monkeypatch.setattr(sp, "_ytdlp_download", fail_ytdlp)
    monkeypatch.setattr(sp, "_stream_download", fake_stream)
    monkeypatch.setattr(sp, "needs_normalization", lambda _p: False)

    result = sp.get_normalized_source("https://cdn.example.com/clip.mp4")
    assert result.exists()


def test_get_normalized_source_uses_cache_on_second_call(tmp_path, monkeypatch):
    """Once a URL is normalized, a second call must return the cached
    file without re-downloading. The per-URL lock guarantees the
    second caller waits, not duplicates the work."""
    monkeypatch.setattr(sp, "CACHE_DIR", tmp_path)

    call_count = {"stream": 0}

    def counting_stream(url: str, dest: Path) -> int:
        call_count["stream"] += 1
        dest.write_bytes(b"moov" + b"\x00" * (1 << 16))
        return dest.stat().st_size

    monkeypatch.setattr(sp, "_stream_download", counting_stream)
    monkeypatch.setattr(sp, "needs_normalization", lambda _p: False)

    url = "https://cdn.example.com/clip.mp4"
    first = sp.get_normalized_source(url)
    second = sp.get_normalized_source(url)
    assert first == second
    assert call_count["stream"] == 1


def test_ytdlp_download_raises_when_missing(monkeypatch, tmp_path):
    """If yt_dlp isn't importable we want a clear error so the HTTP
    layer can return a useful 502 instead of a generic crash."""
    # Force the import inside ``_ytdlp_download`` to fail.
    with mock.patch.dict("sys.modules", {"yt_dlp": None}):
        with pytest.raises(RuntimeError, match="yt_dlp is required"):
            sp._ytdlp_download("https://youtu.be/x", tmp_path)


# ---------------------------------------------------------------------------
# _ytdlp_auth_opts — env-driven cookie / proxy / player-client injection
# ---------------------------------------------------------------------------

class TestYtdlpAuthOpts:
    def test_empty_by_default(self, monkeypatch):
        """No env vars → only the player_client default (android,web)."""
        for var in ("YTDLP_PROXY", "YTDLP_COOKIES_FILE", "YTDLP_COOKIES", "YTDLP_PLAYER_CLIENT"):
            monkeypatch.delenv(var, raising=False)
        opts = sp._ytdlp_auth_opts()
        assert "proxy" not in opts
        assert "cookiefile" not in opts
        # Default player client is applied
        assert "android" in opts.get("extractor_args", {}).get("youtube", {}).get("player_client", [])

    def test_proxy_injected(self, monkeypatch):
        monkeypatch.setenv("YTDLP_PROXY", "http://user:pass@proxy.example.com:8080")
        monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
        monkeypatch.delenv("YTDLP_COOKIES", raising=False)
        opts = sp._ytdlp_auth_opts()
        assert opts["proxy"] == "http://user:pass@proxy.example.com:8080"

    def test_cookies_file_injected(self, monkeypatch, tmp_path):
        cookie_file = tmp_path / "cookies.txt"
        cookie_file.write_text("# Netscape HTTP Cookie File\n")
        monkeypatch.setenv("YTDLP_COOKIES_FILE", str(cookie_file))
        monkeypatch.delenv("YTDLP_PROXY", raising=False)
        monkeypatch.delenv("YTDLP_COOKIES", raising=False)
        opts = sp._ytdlp_auth_opts()
        assert opts["cookiefile"] == str(cookie_file)

    def test_cookies_env_written_to_tempfile(self, monkeypatch, tmp_path):
        """YTDLP_COOKIES contents must be persisted to a temp file and
        the path injected as ``cookiefile``."""
        raw = "# Netscape HTTP Cookie File\nexample.com\tFALSE\t/\tFALSE\t0\tSID\tabc123\n"
        monkeypatch.setenv("YTDLP_COOKIES", raw)
        monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
        monkeypatch.delenv("YTDLP_PROXY", raising=False)
        import tempfile, os
        # Point the written file into tmp_path to keep the fs clean.
        monkeypatch.setattr(
            "src.features.studio.source_proxy.tempfile.gettempdir",
            lambda: str(tmp_path),
        )
        opts = sp._ytdlp_auth_opts()
        assert "cookiefile" in opts
        assert os.path.exists(opts["cookiefile"])
        assert "SID" in open(opts["cookiefile"]).read()

    def test_custom_player_client(self, monkeypatch):
        monkeypatch.setenv("YTDLP_PLAYER_CLIENT", "mweb,ios")
        monkeypatch.delenv("YTDLP_PROXY", raising=False)
        monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
        monkeypatch.delenv("YTDLP_COOKIES", raising=False)
        opts = sp._ytdlp_auth_opts()
        clients = opts["extractor_args"]["youtube"]["player_client"]
        assert "mweb" in clients
        assert "ios" in clients


# ---------------------------------------------------------------------------
# Bot-block error → clear actionable RuntimeError
# ---------------------------------------------------------------------------

def test_ytdlp_download_wraps_bot_block_error(tmp_path):
    """When yt_dlp raises a '403' / 'Sign in to confirm' error the wrapper
    must re-raise a RuntimeError with an actionable message, not the raw
    yt_dlp exception which leaks internals."""
    import yt_dlp  # skip if not installed

    class FakeYDL:
        def __init__(self, opts):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def extract_info(self, url, download):
            raise Exception("Sign in to confirm you're not a bot (403)")

    with mock.patch("yt_dlp.YoutubeDL", FakeYDL):
        with pytest.raises(RuntimeError, match="YouTube blocked this server"):
            sp._ytdlp_download("https://youtu.be/abc123", tmp_path)
