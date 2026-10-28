"""Source-video normalization proxy for the Studio preview.

Browsers (especially Safari) refuse to render an HTML ``<video>`` element if
the source MP4 has its ``moov`` atom at the end of the file rather than at
the start — Safari demands the moov-first ("faststart") layout to start
decoding. Most user-uploaded clips (yt-dlp remuxes, ffmpeg defaults, mobile
exports) end up moov-last unless the encoder was explicitly told otherwise.

This module fixes that lazily, once per source URL:

1. ``get_normalized_source(url)`` hashes the URL, checks an on-disk cache.
2. Cache miss → download the file, run ``ffmpeg -movflags +faststart`` to
   relocate moov to byte 0 (no re-encode if codec is already h264/aac, which
   keeps it ~1s/min-of-video instead of 10s+).
3. Return the local cache path.

YouTube URLs (``youtube.com/watch?v=…``, ``youtu.be/…``) are not directly
streamable to a ``<video>`` element because the actual media is gated behind
DASH/HLS manifests with rotating tokens. We resolve them with ``yt_dlp``,
prefer the smallest ≤720p MP4 (faststart-compatible) the format list
offers, and then run the result through the same normalization pipeline.
This unlocks "Re-edit in Studio" from the Analyzer and "Preview clip" in
the Shorts→Studio handoff, both of which used to fail silently.

The HTTP endpoint that wraps this lives in ``src.api.routers.studio``
(``GET /studio/source-proxy``) and 307-redirects to a Starlette
``StaticFiles`` mount, which gives us proper HTTP Range support for free
(critical for `<video>` seeking).

Cache eviction is intentionally simple: oldest-first up to ``MAX_CACHE_BYTES``.
The same source URL maps to the same cache filename so concurrent requests
de-dupe naturally (the file appears atomically via os.replace).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


# Project-relative cache so docker/dev/prod all see the same path. Lives
# under /tmp by default to keep restarts clean and let the OS reclaim it.
CACHE_DIR = Path(
    os.environ.get(
        "STUDIO_SOURCE_CACHE_DIR",
        os.path.join(tempfile.gettempdir(), "smartvid_source_cache"),
    )
)

# Soft cap. Once the cache exceeds this size we evict the oldest files until
# we're back under the limit. 5 GiB is generous for a dev box and small
# enough to fit even modest VPS disks.
MAX_CACHE_BYTES = int(os.environ.get("STUDIO_SOURCE_CACHE_MAX_BYTES", str(5 * 1024 ** 3)))

# Max source size we'll bother normalizing. Anything bigger is almost
# certainly a misuse (full movies, etc) and just streamed direct.
MAX_INPUT_BYTES = int(os.environ.get("STUDIO_SOURCE_MAX_INPUT_BYTES", str(2 * 1024 ** 3)))

# Per-URL locks so two concurrent requests for the same source don't both
# download + transcode — the second waits for the first to finish.
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lk = _LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _LOCKS[key] = lk
        return lk


def _cache_filename(url: str) -> str:
    """Stable filename for a given source URL — sha256 prefix + .mp4.
    16 hex chars (=64 bits) is plenty to avoid collisions in a per-user
    cache and keeps the filename short enough to log comfortably."""
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"{h}.mp4"


def cache_path_for(url: str) -> Path:
    """Public helper so callers (e.g. the HTTP endpoint) can predict the
    cache filename without triggering a download."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / _cache_filename(url)


def needs_normalization(local_path: str) -> bool:
    """True when the MP4's moov atom isn't at the start (i.e. not faststart).

    Implementation note: probing this without ffprobe is awkward — we'd have
    to walk the atom tree ourselves. Cheaper to just ask ffprobe to read 1MB
    of the head and look at where the moov chunk lands. If ffprobe can
    successfully open the file from a 1MB head, we know moov is at the
    start. Otherwise it isn't.
    """
    try:
        with open(local_path, "rb") as f:
            head = f.read(1 << 20)  # 1 MiB
    except OSError:
        return True

    # The moov atom signature is the ASCII bytes ``moov`` preceded by a
    # 4-byte big-endian length. Scanning the first 1 MiB is enough — if
    # moov isn't in there, the file definitely isn't faststart.
    return b"moov" not in head


# Hosts whose URLs we route through yt_dlp rather than streaming directly.
# Kept narrow on purpose — every entry here adds a fetch path that has to
# work against a remote service we don't control. Add new providers only
# when we have a tested format-string preference.
_YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")


def is_youtube_url(url: str) -> bool:
    """True for any YouTube watch / share URL.

    Public so the HTTP layer can branch on it before calling
    :func:`get_normalized_source` (e.g. for surfacing a friendlier
    "resolving YouTube source…" loading state to the client).
    """
    if not url:
        return False
    lower = url.lower()
    return any(host in lower for host in _YT_HOSTS)


def _ytdlp_auth_opts() -> dict:
    """Env-driven yt_dlp options to get past YouTube's datacenter-IP bot
    check (the reason resolving fails on hosts like Railway).

    YouTube serves "Sign in to confirm you're not a bot" / 403 to most
    cloud IPs. The reliable workarounds are authenticated cookies and/or
    routing through a residential proxy:

    * ``YTDLP_PROXY``        — e.g. ``http://user:pass@host:port`` (residential
                               or rotating proxy). Routes the whole fetch.
    * ``YTDLP_COOKIES_FILE`` — path to a Netscape-format cookies.txt exported
                               from a logged-in YouTube session.
    * ``YTDLP_COOKIES``      — the raw cookies.txt *contents* (handy on PaaS
                               where you can only set env vars, not files).
                               Written to a temp file at call time.
    * ``YTDLP_PLAYER_CLIENT``— comma-separated yt_dlp player clients to try
                               (default ``android,web``); some clients dodge
                               the bot wall better than others.

    Returns an opts dict (possibly empty) to merge into the base config.
    """
    opts: dict = {}

    proxy = os.environ.get("YTDLP_PROXY", "").strip()
    if proxy:
        opts["proxy"] = proxy

    cookies_file = os.environ.get("YTDLP_COOKIES_FILE", "").strip()
    if not cookies_file:
        raw_cookies = os.environ.get("YTDLP_COOKIES", "")
        if raw_cookies.strip():
            # Persist once to a stable temp path so repeated calls reuse it
            # (and yt_dlp can update it in place if it refreshes cookies).
            cookies_file = str(Path(tempfile.gettempdir()) / "smartvid_yt_cookies.txt")
            try:
                with open(cookies_file, "w", encoding="utf-8") as fh:
                    fh.write(raw_cookies)
            except OSError as exc:  # pragma: no cover - disk edge case
                logger.warning("source_proxy.cookies_write_failed", error=str(exc))
                cookies_file = ""
    if cookies_file and os.path.exists(cookies_file):
        opts["cookiefile"] = cookies_file

    player_client = os.environ.get("YTDLP_PLAYER_CLIENT", "android,web").strip()
    if player_client:
        opts["extractor_args"] = {
            "youtube": {"player_client": [c.strip() for c in player_client.split(",") if c.strip()]}
        }

    return opts


def _ytdlp_download(url: str, dest_dir: Path) -> Path:
    """Resolve a YouTube URL to a local MP4 via ``yt_dlp`` and return the path.

    Format preference is *intentionally* "smallest h264 MP4 ≤720p":

    * ``mp4`` so we avoid VP9/AV1 outputs that ffmpeg would have to
      re-encode for Safari.
    * ≤720p because the Studio preview is a 720-tall surface — bigger
      streams just waste bandwidth + cache.
    * ``best`` as a last fallback so we never 100% fail to resolve.

    Raises ``RuntimeError`` if yt_dlp isn't importable (so the caller
    can surface the missing-dependency message instead of a generic
    500) or if the download produced no playable file.
    """
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guarded
        raise RuntimeError("yt_dlp is required to proxy YouTube URLs") from exc

    out_template = str(dest_dir / "yt.%(ext)s")
    ydl_opts = {
        # Prefer compact h264 MP4 for native Safari playback. Falls
        # back through progressively-less-ideal options before yielding
        # to plain ``best`` so we don't 404 on niche videos.
        "format": (
            "best[ext=mp4][vcodec^=avc1][height<=720]/"
            "best[ext=mp4][height<=720]/"
            "best[height<=720]/best"
        ),
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        # Respect the cap: yt_dlp can hit Content-Length before
        # download starts and bail.
        "max_filesize": MAX_INPUT_BYTES,
        # We never want multiple bitrates merged into one file — that
        # path requires ffmpeg post-processing we'd just have to undo.
        "noplaylist": True,
        # Don't pull subtitles; we have our own transcription
        # pipeline and they bloat the working dir.
        "writesubtitles": False,
        "writeautomaticsub": False,
    }
    # Layer in cookies / proxy / player-client when configured so YouTube
    # resolution can work from a blocked datacenter IP.
    ydl_opts.update(_ytdlp_auth_opts())

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
    except Exception as exc:  # noqa: BLE001 - normalize to a clear message
        msg = str(exc)
        if "Sign in to confirm" in msg or "not a bot" in msg or "403" in msg:
            raise RuntimeError(
                "YouTube blocked this server from downloading the video "
                "(datacenter IPs are rate-limited). Set YTDLP_COOKIES / "
                "YTDLP_COOKIES_FILE or YTDLP_PROXY to enable server-side "
                "YouTube playback, or upload the footage directly."
            ) from exc
        raise RuntimeError(f"yt_dlp failed to resolve the YouTube source: {msg[:300]}") from exc

    # ``extract_info`` (above) wrote the merged file to ``dest_dir`` using the
    # pinned ``yt.%(ext)s`` template, so we glob for the result rather than
    # relying on yt_dlp's version-dependent return shape.
    # Pick whichever file yt_dlp landed on. We always prefer ``.mp4``
    # so the rest of the pipeline can ``-c copy`` faststart it.
    candidates: list[Path] = []
    for p in dest_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() == ".mp4":
            return p
        candidates.append(p)
    if not candidates:
        raise RuntimeError("yt_dlp produced no output file")
    # Non-mp4 fallback — return it and let _ffmpeg_faststart's transcode
    # path handle the conversion to Safari-friendly h264+aac.
    return candidates[0]


def _stream_download(url: str, dest: Path) -> int:
    """Download ``url`` to ``dest``. Returns bytes written. Raises on error."""
    import httpx

    written = 0
    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            length_hdr = response.headers.get("Content-Length")
            if length_hdr and int(length_hdr) > MAX_INPUT_BYTES:
                raise ValueError(
                    f"source exceeds MAX_INPUT_BYTES "
                    f"({int(length_hdr) / 1024 / 1024:.0f} MB > "
                    f"{MAX_INPUT_BYTES / 1024 / 1024:.0f} MB)"
                )
            with open(dest, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=1 << 16):
                    f.write(chunk)
                    written += len(chunk)
                    if written > MAX_INPUT_BYTES:
                        raise ValueError(
                            f"source exceeded MAX_INPUT_BYTES mid-stream "
                            f"({written / 1024 / 1024:.0f} MB)"
                        )
    return written


def _ffmpeg_faststart(input_path: Path, output_path: Path) -> None:
    """Rewrite the file with the moov atom at the front. Uses ``-c copy`` so
    we don't re-encode — this is just byte rearrangement. ~1-2 seconds for
    a 30s clip, even slower for huge files (proportional to file size, not
    duration)."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        # If ``-c copy`` fails (rare — e.g. weird codec), fall back to
        # transcoding to a known-good h264+aac. Slower but guaranteed to
        # produce a Safari-playable output.
        logger.warning(
            "source_proxy.copy_failed_falling_back_to_transcode",
            stderr=result.stderr[:500],
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(input_path),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg faststart failed: {result.stderr[:500]}"
            )


def _evict_oldest_if_needed() -> None:
    """Trim the cache back under ``MAX_CACHE_BYTES`` by deleting LRU files.
    Cheap to run on every cache write since cache directory is typically
    < a few hundred files."""
    try:
        files = sorted(
            (p for p in CACHE_DIR.iterdir() if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        total = sum(p.stat().st_size for p in files)
        while total > MAX_CACHE_BYTES and files:
            victim = files.pop(0)
            try:
                size = victim.stat().st_size
                victim.unlink()
                total -= size
                logger.info("source_proxy.evicted", path=str(victim))
            except OSError:
                continue
    except FileNotFoundError:
        return


def get_normalized_source(url: str) -> Path:
    """Return a local cache path containing a Safari-friendly faststart MP4
    for ``url``. Downloads + rewrites on cache miss; returns cached path on
    cache hit. Safe under concurrent calls for the same URL.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = cache_path_for(url)
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path

    lock = _lock_for(url)
    with lock:
        # Re-check under the lock — another thread may have finished while
        # we were waiting.
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path

        with tempfile.TemporaryDirectory(prefix="source_proxy_") as workdir:
            workdir_p = Path(workdir)
            # YouTube URLs need yt_dlp to resolve the actual MP4 behind
            # the watch page; everything else is a direct http(s) media
            # URL we can stream byte-for-byte.
            if is_youtube_url(url):
                logger.info("source_proxy.ytdlp_start", url=_redact(url))
                raw = _ytdlp_download(url, workdir_p)
            else:
                raw = workdir_p / "raw.mp4"
                logger.info("source_proxy.download_start", url=_redact(url))
                _stream_download(url, raw)

            if not needs_normalization(str(raw)):
                # Already faststart — just move (or copy) into the cache.
                logger.info("source_proxy.already_faststart", url=_redact(url))
                shutil.copy2(raw, cache_path)
            else:
                logger.info(
                    "source_proxy.normalizing",
                    url=_redact(url),
                    bytes=raw.stat().st_size,
                )
                staged = workdir_p / "out.mp4"
                _ffmpeg_faststart(raw, staged)
                # Atomic move so other threads/processes never see a half-
                # written file.
                os.replace(staged, cache_path)

        _evict_oldest_if_needed()
        return cache_path


_URL_TAIL = re.compile(r"[?#].*$")


def _redact(url: str) -> str:
    """Strip query strings so we don't log presigned URL credentials."""
    return _URL_TAIL.sub("", url)


def is_proxyable(url: Optional[str]) -> bool:
    """True when ``url`` is a remote ``http(s)://`` source we should run
    through the proxy. Local paths, blob/data URIs, and our own backend
    paths are returned to the caller untouched."""
    if not url:
        return False
    if not url.startswith(("http://", "https://")):
        return False
    return True
