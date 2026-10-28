"""Multi-subject tracking precompute job for the Studio Camera lane.

Runs the (slow) ``SubjectTracker`` ML pipeline against the session's source
clip and persists a compact JSON payload onto the ``EditSession`` row. The
``GET /studio/sessions/{key}/tracking`` endpoint reads this cache; the
in-browser CameraLane/Preview/BBoxOverlay consume it.

This is the RQ entry point — enqueue via:

    enqueue_job("src.features.studio.tracking:compute_tracking", session_id, 4)

Designed for **idempotent re-run**: the job clears `tracking_*` cache fields
at the top, sets status="computing", and only writes the final payload on
success. A failure leaves status="failed" + an error message in the
progress field so the frontend can surface it.

Why a separate module from render.py? Tracking is needed *before* the user
clicks Render (Camera lane needs subjects to show in the UI), so we want to
kick it off as soon as the session opens. Reusing the source-acquisition
pattern from ``peaks.py`` keeps the dependency surface small.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from src.database.connection import get_session
from src.database.models import EditSession

logger = structlog.get_logger(__name__)


# Reuse the source-acquisition logic from peaks.py — they need the same
# raw mp4 and we don't want to duplicate the yt-dlp + httpx branching.
def _acquire_source(source_url: str, source_clip_path: Optional[str], workdir: str) -> Optional[str]:
    """Local mp4 path for the source video; downloads if needed."""
    if source_clip_path and os.path.exists(source_clip_path):
        return source_clip_path

    local_path = os.path.join(workdir, "tracking_source.mp4")

    if any(host in source_url for host in ("youtube.com", "youtu.be")):
        try:
            import yt_dlp  # type: ignore
        except ImportError:
            logger.error("studio.tracking.yt_dlp_missing")
            return None
        ydl_opts = {
            # Tracking needs visual frames, so we want video (not bestaudio).
            "format": "best[ext=mp4][height<=720]/best[ext=mp4]/best",
            "outtmpl": local_path,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([source_url])
        return local_path if os.path.exists(local_path) else None

    try:
        import httpx

        with httpx.Client(follow_redirects=True, timeout=120.0) as client:
            with client.stream("GET", source_url) as response:
                response.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=1 << 16):
                        f.write(chunk)
        return local_path
    except Exception as exc:
        logger.error("studio.tracking.download_failed", url=source_url, error=str(exc))
        return None


def _set_progress(session_id: int, percent: int, message: str) -> None:
    """Write a coarse progress update onto the session row.

    Mirrors ``render._set_progress`` exactly so the polling UI can reuse
    the same shape. Safe to call frequently.
    """
    percent = max(0, min(100, int(percent)))
    with get_session() as session:
        row = session.get(EditSession, session_id)
        if row is None:
            return
        row.tracking_progress = percent
        row.tracking_progress_message = message[:200]
        session.commit()


def _mark_status(session_id: int, status: str) -> None:
    with get_session() as session:
        row = session.get(EditSession, session_id)
        if row is None:
            return
        row.tracking_status = status
        session.commit()


def _persist_result(
    session_id: int,
    payload: Dict[str, Any],
    n_subjects: int,
    start_time: float,
    end_time: float,
) -> None:
    """Write the final tracking JSON + cache keys to the session row."""
    with get_session() as session:
        row = session.get(EditSession, session_id)
        if row is None:
            return
        row.tracking_json = json.dumps(payload, separators=(",", ":"))
        row.tracking_subjects_n = n_subjects
        row.tracking_start_time = start_time
        row.tracking_end_time = end_time
        row.tracking_status = "done"
        row.tracking_progress = 100
        row.tracking_progress_message = (
            f"Detected {len(payload.get('subjects', []))} subject(s)"
        )
        session.commit()


def _mark_failed(session_id: int, message: str) -> None:
    with get_session() as session:
        row = session.get(EditSession, session_id)
        if row is None:
            return
        row.tracking_status = "failed"
        row.tracking_progress_message = f"Failed: {message[:160]}"
        session.commit()


def compute_tracking(session_id: int, n_subjects: int = 4) -> Dict[str, Any]:
    """Run SubjectTracker on a session's source clip and cache the result.

    Returns the same payload that gets written to ``tracking_json`` (handy
    for tests that call this synchronously). On error returns
    ``{"error": str}`` and the session row is tagged ``tracking_status="failed"``.
    """
    started = datetime.utcnow()
    n_subjects = max(1, min(8, int(n_subjects)))

    # Load session metadata — what to track, start/end, source path.
    with get_session() as session:
        row = session.get(EditSession, session_id)
        if row is None:
            return {"error": "session not found"}
        source_url = row.source_video_url
        source_clip_path = row.source_clip_path
        start_time = row.source_start_time or 0.0
        end_time = row.source_end_time or (start_time + 0.01)

    _mark_status(session_id, "computing")
    _set_progress(session_id, 5, "Downloading source video")

    try:
        with tempfile.TemporaryDirectory(prefix="studio_tracking_") as workdir:
            local_path = _acquire_source(source_url, source_clip_path, workdir)
            if local_path is None:
                _mark_failed(session_id, "could not download source video")
                return {"error": "could not download source video"}

            _set_progress(session_id, 25, "Loading ML models")
            # Lazy import so unrelated code paths (and pure-python test runs)
            # don't pay the ultralytics/mediapipe load cost.
            from src.features.subject_tracker import (
                SubjectTracker,
                TrackingMode,
            )

            tracker = SubjectTracker(mode=TrackingMode.SPEAKER)

            _set_progress(session_id, 35, "Detecting subjects")
            # Track in CLIP-LOCAL coordinates (start=0). The
            # smoothed_crop_x arrays are indexed by segment-local frame so
            # the frontend's Remotion player can look up by `frame` directly.
            result = tracker.track_video_segment_multi(
                video_path=local_path,
                start_time=start_time,
                end_time=end_time,
                target_ratio=(9, 16),
                n_subjects=n_subjects,
            )

            _set_progress(session_id, 90, "Persisting results")
            payload = _result_to_payload(result, start_time)
            _persist_result(
                session_id=session_id,
                payload=payload,
                n_subjects=n_subjects,
                start_time=start_time,
                end_time=end_time,
            )

            elapsed = (datetime.utcnow() - started).total_seconds()
            logger.warning(
                "studio.tracking.done",
                session_id=session_id,
                seconds=round(elapsed, 1),
                subjects=len(payload.get("subjects", [])),
            )
            return payload

    except Exception as exc:
        logger.exception("studio.tracking.failed", session_id=session_id)
        _mark_failed(session_id, str(exc))
        return {"error": str(exc)}


def _result_to_payload(result: Any, segment_start_time: float) -> Dict[str, Any]:
    """Serialize a TrackingResult into the JSON shape the frontend consumes.

    Per-frame bboxes are kept SPARSE (only detection frames) to keep payload
    size manageable: with detection_interval=5 and 15s of 30fps video we
    ship ~90 samples per subject instead of 450.

    Timestamps in ``frames[i].t`` are clip-local seconds (matching the
    Remotion player's frame clock), not source-video time.
    """
    subjects: List[Dict[str, Any]] = []
    for track in getattr(result, "subject_tracks", []):
        sparse_frames: List[Dict[str, Any]] = []
        for ft in track.frames:
            box = ft.primary_subject
            if box is None:
                continue
            sparse_frames.append({
                "t": round(max(0.0, ft.timestamp - segment_start_time), 4),
                "x": int(box.x),
                "y": int(box.y),
                "w": int(box.width),
                "h": int(box.height),
                "conf": round(float(box.confidence), 3),
            })
        subjects.append({
            "id": int(track.id),
            "label": track.label,
            "color_hex": track.color_hex,
            "smoothed_crop_x": [int(v) for v in track.smoothed_crop_x],
            "frames": sparse_frames,
        })
    return {
        "fps": float(getattr(result, "fps", 30.0)),
        "frame_w": int(getattr(result, "frame_width", 1920)),
        "frame_h": int(getattr(result, "frame_height", 1080)),
        "subjects": subjects,
    }


def is_cache_valid(row: EditSession, n: int) -> bool:
    """The cached tracking payload matches when N + clip-times all line up.

    Normalizes ``None`` → 0.0 on both sides because ``compute_tracking`` writes
    the resolved float (after ``row.source_start_time or 0.0``) into
    ``tracking_start_time``, while the source row may legitimately keep a
    ``None`` for "not yet specified". Without this normalization the cache
    would invalidate every single time even though the job completed
    successfully — and the worker would burn cycles re-detecting forever.
    """
    if not row.tracking_json:
        return False
    if row.tracking_subjects_n != n:
        return False
    if (row.tracking_start_time or 0.0) != (row.source_start_time or 0.0):
        return False
    if (row.tracking_end_time or 0.0) != (row.source_end_time or 0.0):
        return False
    return True
