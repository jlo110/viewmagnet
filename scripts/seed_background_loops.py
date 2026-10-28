"""Seed the featured background-loop catalog (Week 6).

For each entry in ``src.features.studio.background_catalog.FEATURED_LOOPS``
that doesn't yet have a ``download_url`` filled in, this script:

  1. Resolves a source video — either an explicit ``SOURCES[id]`` URL
     mapping defined below (curated by hand) or a Pexels search.
  2. Downloads the source mp4.
  3. Transcodes to web-friendly 720p H.264 + AAC + ``+faststart`` so the
     browser <video> element + ffmpeg ``-stream_loop`` both start playback
     instantly.
  4. Uploads the result to R2 under ``studio/backgrounds/{id}.mp4``.
  5. Prints the resulting public URL so the developer can paste it into
     ``FEATURED_LOOPS[id]['download_url']``.

Idempotent: re-runs skip entries that already have a non-empty
``download_url`` unless you pass ``--force``.

Run:

    PEXELS_API_KEY=... python scripts/seed_background_loops.py

Outputs a JSON snippet at the end you can copy into ``background_catalog.py``.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

import structlog

# Allow running from anywhere — add the repo root to sys.path.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.config import get_settings  # noqa: E402
from src.features.studio.background_catalog import FEATURED_LOOPS  # noqa: E402

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Hand-curated source mappings
# ---------------------------------------------------------------------------
# Per-id direct download URL OR Pexels search query. The script prefers the
# URL when present (faster, deterministic), falling back to the query
# otherwise (handy when we don't have a stable upstream URL).
#
# All ids here MUST match a key in ``FEATURED_LOOPS``. Add new entries
# alongside additions to that dict.

SOURCES: Dict[str, Dict[str, str]] = {
    "minecraft_parkour": {"query": "minecraft parkour gameplay loop"},
    "subway_surfers": {"query": "subway surfers gameplay"},
    "satisfying_soap": {"query": "soap cutting satisfying"},
    "satisfying_paint": {"query": "paint mixing colorful"},
    "lofi_rain": {"query": "rainy window cafe lofi"},
    "abstract_gradient": {"query": "abstract gradient motion background"},
    "nature_forest": {"query": "forest sunlight beams"},
    "nature_waves": {"query": "ocean waves loop"},
    "city_timelapse": {"query": "city timelapse night"},
    "particles_dark": {"query": "dark particles abstract background"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ffmpeg_bin() -> str:
    """Reuse the same resolver as the render job."""
    for cand in (
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
        "/opt/ffmpeg-full/bin/ffmpeg",
    ):
        if os.path.exists(cand):
            return cand
    return shutil.which("ffmpeg") or "ffmpeg"


def _resolve_source_url(entry_id: str) -> Optional[str]:
    """Resolve an entry to a downloadable Pexels mp4 URL."""
    src = SOURCES.get(entry_id)
    if not src:
        logger.warning("seed.no_source", id=entry_id)
        return None
    if "url" in src:
        return src["url"]
    query = src.get("query")
    if not query:
        return None
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        logger.warning("seed.no_pexels_key", id=entry_id)
        return None

    from src.features.broll_finder import PexelsClient

    client = PexelsClient(api_key=api_key)
    # Pick the longest result whose duration >= 10s — longer = fewer
    # visible loop seams.
    clips = client.search_videos(query=query, per_page=40)
    candidates = [c for c in clips if c.duration >= 10 and c.download_url]
    if not candidates:
        logger.warning("seed.no_candidates", id=entry_id, query=query)
        return None
    candidates.sort(key=lambda c: c.duration, reverse=True)
    return candidates[0].download_url


def _download(url: str, dest: str) -> None:
    import httpx

    with httpx.Client(follow_redirects=True, timeout=120.0) as client, client.stream("GET", url) as response:
        response.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in response.iter_bytes(1 << 16):
                f.write(chunk)


def _transcode_for_loop(src: str, dst: str) -> None:
    """720p H.264 + AAC + ``+faststart``; capped at 60s so we don't ship
    megabytes-large featured loops."""
    cmd = [
        _ffmpeg_bin(),
        "-y",
        "-i", src,
        "-t", "60",
        "-vf", "scale=-2:720:flags=lanczos",
        "-r", "30",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "96k",
        "-ac", "1",
        "-movflags", "+faststart",
        dst,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _upload(local: str, entry_id: str) -> str:
    settings = get_settings()
    if not (settings.r2_account_id and settings.r2_access_key_id and settings.r2_secret_access_key):
        logger.warning("seed.r2_not_configured")
        return f"file://{local}"

    from src.video_analysis.storage import R2Storage

    storage = R2Storage(
        account_id=settings.r2_account_id,
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key,
        bucket_name=settings.r2_bucket_name or "viewmagnet-videos",
    )

    key = f"studio/backgrounds/{entry_id}.mp4"
    with open(local, "rb") as f:
        storage.client.upload_fileobj(
            f, storage.bucket_name, key,
            ExtraArgs={"ContentType": "video/mp4", "CacheControl": "public, max-age=2592000"},
        )

    public_base = (settings.r2_public_url or "").rstrip("/")
    if public_base and not public_base.startswith("http://localhost"):
        return f"{public_base}/{key}"
    return storage.client.generate_presigned_url(
        "get_object",
        Params={"Bucket": storage.bucket_name, "Key": key},
        ExpiresIn=60 * 60 * 24 * 365,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-seed entries that already have a download_url")
    parser.add_argument("--only", nargs="*", default=None, help="only seed these ids")
    args = parser.parse_args()

    results: Dict[str, str] = {}
    failures: List[Tuple[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="seed_loops_") as workdir:
        for entry_id, entry in FEATURED_LOOPS.items():
            if args.only and entry_id not in args.only:
                continue
            if entry.get("download_url") and not args.force:
                print(f"skip {entry_id}: already seeded")
                continue
            try:
                src_url = _resolve_source_url(entry_id)
                if not src_url:
                    failures.append((entry_id, "no source resolved"))
                    continue
                print(f"[{entry_id}] downloading {src_url[:80]}...")
                src_path = os.path.join(workdir, f"{entry_id}.src.mp4")
                _download(src_url, src_path)

                print(f"[{entry_id}] transcoding...")
                dst_path = os.path.join(workdir, f"{entry_id}.mp4")
                _transcode_for_loop(src_path, dst_path)

                print(f"[{entry_id}] uploading to R2...")
                url = _upload(dst_path, entry_id)
                results[entry_id] = url
                print(f"[{entry_id}] -> {url}")
            except Exception as exc:
                failures.append((entry_id, str(exc)))
                print(f"FAIL {entry_id}: {exc}", file=sys.stderr)

    if results:
        print("\n--- Paste into background_catalog.py FEATURED_LOOPS ---")
        print(json.dumps(results, indent=2))

    if failures:
        print("\n--- Failures ---", file=sys.stderr)
        for entry_id, err in failures:
            print(f"  {entry_id}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
