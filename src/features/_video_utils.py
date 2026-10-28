"""Shared video utilities (download, duration, frame extraction).

Replaces duplicated copies in ``loop_designer.py`` and ``pacing_analyzer.py``.

All helpers are sync (intended to run inside ``asyncio.to_thread`` from API
handlers). They shell out to ``ffmpeg`` / ``ffprobe`` / ``yt-dlp``.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class VideoUtilError(RuntimeError):
    """Raised when an external tool (ffmpeg/ffprobe/yt-dlp) fails."""


def get_video_duration(video_path: str) -> float:
    """Return the duration of a video file in seconds (uses ``ffprobe``)."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        raise VideoUtilError(f"ffprobe duration failed: {e}") from e


def extract_frame_at(video_path: str, timestamp: float, output_path: Optional[str] = None) -> str:
    """Extract a single frame at ``timestamp`` seconds. Returns the output path."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)
    if output_path is None:
        output_path = os.path.join(
            tempfile.gettempdir(),
            f"frame_{int(timestamp * 1000)}_{os.getpid()}.jpg",
        )
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss", f"{timestamp:.3f}",
                "-i", video_path,
                "-frames:v", "1",
                "-q:v", "2",
                output_path,
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
        return output_path
    except subprocess.CalledProcessError as e:
        raise VideoUtilError(f"ffmpeg frame extract failed: {e.stderr.decode()[:200]}") from e


def download_video(
    video_url: str,
    output_dir: Optional[str] = None,
    max_height: int = 720,
    timeout: int = 180,
) -> str:
    """Download a video with yt-dlp. Returns the local mp4 path."""
    if not output_dir:
        output_dir = tempfile.mkdtemp(prefix="vid_")
    output_template = os.path.join(output_dir, "video.%(ext)s")
    output_mp4 = os.path.join(output_dir, "video.mp4")
    
    try:
        subprocess.run(
            [
                "yt-dlp",
                "-f", f"best[height<={max_height}][ext=mp4]/best[height<={max_height}]/best",
                "--merge-output-format", "mp4",
                "-o", output_template,
                "--no-playlist",
                "--quiet",
                "--no-warnings",
                video_url,
            ],
            capture_output=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise VideoUtilError(f"yt-dlp download failed: {e.stderr.decode()[:200]}") from e
    except subprocess.TimeoutExpired as e:
        raise VideoUtilError("yt-dlp download timed out") from e
    
    # yt-dlp may produce video.mp4 directly or need merging.
    if os.path.exists(output_mp4):
        return output_mp4
    for fname in os.listdir(output_dir):
        if fname.startswith("video.") and fname.endswith((".mp4", ".webm", ".mkv")):
            return os.path.join(output_dir, fname)
    raise VideoUtilError(f"yt-dlp did not produce an output file in {output_dir}")
