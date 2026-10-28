"""Phase 8.1: capture YouTube "Most Replayed" heatmaps (public retention proxy).

True retention curves are owner-private (YouTube Analytics); the watch page's
"Most Replayed" heatmap is the public shape proxy — ~100 normalized points per
video showing where viewers rewatch vs bail. Extracted via yt-dlp's info JSON
(no API quota; unofficial endpoint — the data is what the player UI renders).

Timing (verified 2026-06-12 by probing videos of known age): heatmaps are
absent at 3 days and present on everything >= 13 days, so eligibility starts
at HEATMAP_MIN_AGE_DAYS with one retry after the 30d checkpoint. A row is
written either way (``has_heatmap`` False = exhausted probe) so videos are
never re-fetched forever.

Pure helpers (`eligible_attempt`, `heatmap_features`) are separated from the
fetch/DB so they're unit-testable without network.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import List, Optional

import structlog

logger = structlog.get_logger(__name__)

HEATMAP_MIN_AGE_DAYS = 13       # first probe (verified present by this age)
HEATMAP_RETRY_AGE_DAYS = 31     # second (final) probe for late appearers
MAX_ATTEMPTS = 2
FETCH_SLEEP_SECONDS = 1.0       # politeness between watch-page fetches


def eligible_attempt(age_days: float, attempts: int) -> bool:
    """Should we probe this video now, given its age and prior attempts?"""
    if attempts >= MAX_ATTEMPTS:
        return False
    if attempts == 0:
        return age_days >= HEATMAP_MIN_AGE_DAYS
    return age_days >= HEATMAP_RETRY_AGE_DAYS


def heatmap_features(points: List[dict]) -> Optional[dict]:
    """Summarize a heatmap's shape into model-ready features.

    - ``intro_retention``: mean value over the first 10% (post-hook survival;
      the first bucket is ~always 1.0 by normalization, so skip it)
    - ``tail_retention``: mean value over the last 25% (did the payoff hold)
    - ``dropoff_slope``: (mean of first quarter - mean of last quarter)
    - ``rewatch_peaks``: count of interior local maxima above 1.5x the median
      (moments people scrub back to — chapter/highlight candidates)
    """
    if not points or len(points) < 10:
        return None
    vals = [float(p.get("value", 0.0)) for p in points]
    n = len(vals)
    interior = vals[1:]  # bucket 0 is the normalization peak by construction
    intro = interior[: max(1, n // 10)]
    tail = vals[-max(1, n // 4):]
    q1 = vals[1 : max(2, n // 4)]
    med = sorted(interior)[len(interior) // 2]
    peaks = sum(
        1
        for i in range(2, n - 1)
        if vals[i] > vals[i - 1] and vals[i] > vals[i + 1] and vals[i] > 1.5 * med
    )
    return {
        "intro_retention": round(sum(intro) / len(intro), 4),
        "tail_retention": round(sum(tail) / len(tail), 4),
        "dropoff_slope": round(sum(q1) / len(q1) - sum(tail) / len(tail), 4),
        "rewatch_peaks": peaks,
    }


TRANSCRIPT_MAX_MS = 60_000  # opening transcript window (the hook + setup)


def parse_json3_transcript(data: dict, max_ms: int = TRANSCRIPT_MAX_MS) -> Optional[str]:
    """Flatten a YouTube ``json3`` caption payload into the opening transcript.

    Keeps segments that *start* within ``max_ms``. Pure — unit-testable.
    """
    events = data.get("events") or []
    parts: List[str] = []
    for ev in events:
        if ev.get("tStartMs", 0) > max_ms:
            break
        for seg in ev.get("segs") or []:
            t = (seg.get("utf8") or "").replace("\n", " ").strip()
            if t:
                parts.append(t)
    text = " ".join(parts).strip()
    return text or None


def _pick_caption_track(info: dict) -> tuple:
    """Choose the best English caption track: manual subs beat auto-captions.

    Returns (json3_url, lang, source) or (None, None, None).
    """
    for source, key in (("manual", "subtitles"), ("auto", "automatic_captions")):
        tracks = info.get(key) or {}
        for lang in ("en", "en-orig", "en-US", "en-GB"):
            for fmt in tracks.get(lang) or []:
                if fmt.get("ext") == "json3" and fmt.get("url"):
                    return fmt["url"], lang, source
    return None, None, None


def fetch_video_extras(video_id: str) -> dict:
    """One yt-dlp probe → heatmap points + opening transcript (both optional).

    The watch-page fetch we already pay for the heatmap also carries the
    caption-track URLs (manual subs + auto-captions, zero API quota) — the
    transcript rides along nearly free.
    """
    import requests
    import yt_dlp

    opts = {"quiet": True, "skip_download": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

    hm = info.get("heatmap")
    points = (
        [
            {
                "start_time": round(float(p["start_time"]), 2),
                "end_time": round(float(p["end_time"]), 2),
                "value": round(float(p["value"]), 5),
            }
            for p in hm
        ]
        if hm
        else None
    )

    transcript = lang = source = None
    url, lang, source = _pick_caption_track(info)
    if url:
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                transcript = parse_json3_transcript(r.json())
        except Exception as e:  # captions are a bonus — never fail the probe
            logger.debug("transcript.fetch_failed", video_id=video_id, error=str(e)[:100])
    if transcript is None:
        lang = source = None

    return {
        "heatmap": points,
        "transcript": transcript,
        "transcript_lang": lang,
        "transcript_source": source,
    }


def capture_heatmaps(session, max_videos: int = 60) -> dict:
    """Probe eligible tracked videos and store their heatmaps (or the miss).

    Eligible = past HEATMAP_MIN_AGE_DAYS with no exhausted probe. Bounded per
    run and throttled — these are watch-page fetches, not API calls.
    """
    from sqlalchemy import select

    from src.database.models import TrackedVideo, VideoHeatmap

    now = datetime.utcnow()
    existing = {
        r[0]: (r[1], r[2])
        for r in session.execute(
            select(VideoHeatmap.video_id, VideoHeatmap.attempts, VideoHeatmap.has_heatmap)
        ).all()
    }
    candidates = session.execute(
        select(TrackedVideo.video_id, TrackedVideo.published_at)
        .where(TrackedVideo.published_at.isnot(None))
        .order_by(TrackedVideo.published_at)
    ).all()

    todo = []
    for vid, pub in candidates:
        attempts, has = existing.get(vid, (0, False))
        if has:  # already captured — terminal, never re-probe
            continue
        age_days = (now - pub).total_seconds() / 86400
        if eligible_attempt(age_days, attempts):
            todo.append(vid)
        if len(todo) >= max_videos:
            break

    captured = missed = errors = transcripts = 0
    for vid in todo:
        try:
            extras = fetch_video_extras(vid)
        except Exception as e:
            errors += 1
            logger.debug("heatmap.fetch_failed", video_id=vid, error=str(e)[:120])
            extras = {"heatmap": None, "transcript": None}

        points = extras.get("heatmap")
        row = session.query(VideoHeatmap).filter_by(video_id=vid).one_or_none()
        if row is None:
            row = VideoHeatmap(video_id=vid, attempts=0)
            session.add(row)
        row.attempts += 1
        if points:
            row.has_heatmap = True
            row.points = json.dumps(points)
            row.n_points = len(points)
            row.video_duration_seconds = int(points[-1]["end_time"]) if points else None
            captured += 1
        else:
            missed += 1
        # Opening transcript rides along on the same probe (8.6 follow-up):
        # stored even when the heatmap is absent — captions exist much earlier.
        if extras.get("transcript") and not row.opening_transcript:
            row.opening_transcript = extras["transcript"][:8000]
            row.transcript_lang = extras.get("transcript_lang")
            row.transcript_source = extras.get("transcript_source")
            transcripts += 1
        session.flush()
        time.sleep(FETCH_SLEEP_SECONDS)

    session.commit()
    return {
        "captured": captured,
        "missed": missed,
        "errors": errors,
        "eligible": len(todo),
        "transcripts": transcripts,
    }
