"""Audio-waveform peak extraction for the Studio timeline.

The browser timeline renders an audio waveform behind the source-video lane.
Instead of streaming the full source video into the browser and decoding the
audio client-side (slow, bandwidth-heavy), we extract a compact peak array
on the server and ship just ~8 KB of JSON per clip.

A "peak" here is the max absolute sample amplitude within a fixed-size time
bin, normalized to [0,1]. With 2000 bins on a 15s clip that's a peak every
7.5 ms — finer than a screen pixel for any timeline width we care about.
"""
from __future__ import annotations

import array
import os
import shutil
import subprocess
import tempfile
from typing import List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)


# Sample rate we extract at. 8 kHz is more than enough for peak detection
# (we're not playing the audio back), and keeps the PCM stream small —
# 15 s of audio is ~240 KB of int16 samples, ffmpeg streams it in <200ms.
_PEAK_SR = 8000


_FFMPEG_FULL_CANDIDATES = (
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
    "/opt/ffmpeg-full/bin/ffmpeg",
)


def _ffmpeg_bin() -> str:
    """Mirror src.features.studio.render._ffmpeg_bin so both jobs use the
    same ffmpeg binary."""
    explicit = os.environ.get("FFMPEG_BIN")
    if explicit and os.path.exists(explicit):
        return explicit
    for cand in _FFMPEG_FULL_CANDIDATES:
        if os.path.exists(cand):
            return cand
    return shutil.which("ffmpeg") or "ffmpeg"


def _acquire_source(source_url: str, source_clip_path: Optional[str], workdir: str) -> Optional[str]:
    """Return a local mp4 path. Same logic as render._ensure_source but kept
    here as a small dependency so peaks.py can stand alone."""
    if source_clip_path and os.path.exists(source_clip_path):
        return source_clip_path

    local_path = os.path.join(workdir, "peaks_source.mp4")

    if any(host in source_url for host in ("youtube.com", "youtu.be")):
        try:
            import yt_dlp  # type: ignore
        except ImportError:
            logger.error("studio.peaks.yt_dlp_missing")
            return None
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": local_path,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([source_url])
        return local_path if os.path.exists(local_path) else None

    try:
        import httpx

        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            with client.stream("GET", source_url) as response:
                response.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=1 << 16):
                        f.write(chunk)
        return local_path
    except Exception as exc:
        logger.error("studio.peaks.download_failed", url=source_url, error=str(exc))
        return None


def compute_peaks(
    source_url: str,
    source_clip_path: Optional[str],
    start: float,
    end: float,
    bins: int = 2000,
) -> Tuple[List[float], float]:
    """Extract ``bins`` peak amplitudes from the audio between ``start`` and
    ``end`` seconds of the source.

    Returns ``(peaks, duration)`` where ``peaks`` is length-``bins`` of floats
    in [0,1] and ``duration`` is ``end - start`` (so callers don't have to
    recompute it).

    Falls back to a zero array (silent waveform) if the source has no audio
    track or ffmpeg fails — the timeline still works, just without the
    waveform. We never raise: the waveform is best-effort, not critical.
    """
    duration = max(0.01, end - start)
    bins = max(1, min(bins, 20000))

    if not source_url:
        return [0.0] * bins, duration

    with tempfile.TemporaryDirectory(prefix="studio_peaks_") as workdir:
        local_path = _acquire_source(source_url, source_clip_path, workdir)
        if local_path is None:
            return [0.0] * bins, duration

        cmd = [
            _ffmpeg_bin(),
            "-nostdin",
            "-hide_banner",
            "-loglevel", "error",
            "-ss", f"{start:.3f}",
            "-to", f"{end:.3f}",
            "-i", local_path,
            "-vn",
            "-ac", "1",
            "-ar", str(_PEAK_SR),
            "-map", "0:a?",
            "-f", "s16le",
            "-",
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            tail = (exc.stderr or b"").decode("utf-8", errors="replace")[-300:]
            logger.warning("studio.peaks.ffmpeg_failed", error=tail, url=source_url)
            return [0.0] * bins, duration

        raw = result.stdout
        if not raw:
            # Source had no audio track. Empty waveform is fine.
            return [0.0] * bins, duration

        samples = array.array("h")
        samples.frombytes(raw)
        return _bucket_peaks(samples, bins), duration


def _bucket_peaks(samples: "array.array[int]", bins: int) -> List[float]:
    """Reduce an int16 PCM sample array to ``bins`` peak floats in [0,1].

    For each bin we take the **max absolute** sample — this preserves
    transient loud moments (great for visually finding word boundaries) in
    a way mean/RMS would smooth out.
    """
    n = len(samples)
    if n == 0:
        return [0.0] * bins
    out: List[float] = [0.0] * bins
    # Integer step lets us index without floats; any leftover samples are
    # folded into the last bin to keep the total covered.
    step = n / bins
    for i in range(bins):
        lo = int(i * step)
        hi = int((i + 1) * step) if i < bins - 1 else n
        if hi <= lo:
            continue
        peak = 0
        for j in range(lo, hi):
            v = samples[j]
            av = -v if v < 0 else v
            if av > peak:
                peak = av
        out[i] = peak / 32768.0
    return out
