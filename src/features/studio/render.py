"""Server-side render job for the Studio editor.

This module is what RQ workers (or the synchronous fallback) invoke when
a user clicks **Render** in the Studio. It loads the persisted ``EditSpec``,
runs ffmpeg with the user's chosen aspect ratio + cropped subject + B-roll
overlays + styled captions burned in, uploads the result to R2, and updates
the ``EditSession`` row so the frontend can pick up the new download URL.

Designed for **idempotent restart**: a half-finished render is detectable
by ``last_render_status == "rendering"`` and can be re-enqueued safely
because the output filename is derived from the session id + a content
hash, not random.

Week-2 pipeline:

    source clip → ffmpeg crop (aspect ratio)
                → per-B-roll scale/crop + overlay window
                → ffmpeg ASS burn-in
                → R2 upload

Progress writes (5/20/30/50 → 50..95 derived from ffmpeg `frame=` → 100)
get persisted to ``render_progress`` so the frontend polling endpoint can
surface a live progress bar.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

import structlog

from src.config import get_settings
from src.database.connection import get_session
from src.database.models import EditSession
from src.features.studio.ass_renderer import write_ass_file
from src.features.studio.spec import (
    AspectRatio,
    BRollClip,
    CameraCut,
    EditSpec,
    TransitionType,
)
from src.features.studio.layout import LayoutRegions, Rect, regions_for
from src.features.studio.transition_catalog import get_transition
from src.queue import report_render_exception
from src.queue.telemetry import (
    record_render_completed,
    record_render_failed,
    record_render_progress,
    record_render_started,
)

logger = structlog.get_logger(__name__)

# Output framerate. Must match the Remotion <Player> FPS in
# frontend/client/src/pages/dashboard/Studio.tsx so timing math agrees.
_OUTPUT_FPS = 30


# ---------------------------------------------------------------------------
# Aspect-ratio → output dimensions
# ---------------------------------------------------------------------------

_OUTPUT_DIMENSIONS: dict[AspectRatio, Tuple[int, int]] = {
    AspectRatio.PORTRAIT_9_16: (1080, 1920),
    AspectRatio.SQUARE_1_1: (1080, 1080),
    AspectRatio.LANDSCAPE_4_5: (1080, 1350),
    AspectRatio.LANDSCAPE_16_9: (1920, 1080),
}


def get_output_dimensions(aspect: AspectRatio) -> Tuple[int, int]:
    """Public helper so other code (frontend preview sizing, tests) agrees."""
    return _OUTPUT_DIMENSIONS[aspect]


# ---------------------------------------------------------------------------
# Public job entry point
# ---------------------------------------------------------------------------


@dataclass
class RenderResult:
    success: bool
    output_path: Optional[str] = None
    download_url: Optional[str] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None


def render_session(session_id: int) -> RenderResult:
    """Render the EditSession identified by ``session_id``.

    Called by RQ (``enqueue_job("src.features.studio.render:render_session", id)``)
    or directly inline when the queue is in synchronous fallback mode.

    Updates the session row's ``last_render_status`` + ``render_progress`` as
    it progresses so the frontend's status-polling endpoint always has fresh
    state to return.
    """
    # Bind the render's identifying context for the whole job duration
    # so every log line emitted from inside the job carries
    # ``user_id``, ``render_kind``, and ``render_id`` without each call
    # site repeating itself. structlog.contextvars are thread-local
    # and Sentry / log aggregator filters can key off them.
    try:
        from structlog.contextvars import bind_contextvars, unbind_contextvars

        user_id: Optional[int] = None
        with get_session() as session:
            row = session.get(EditSession, session_id)
            if row is not None:
                user_id = row.user_id
        bind_contextvars(
            render_kind="session", render_id=session_id, user_id=user_id
        )
    except Exception:  # noqa: BLE001
        # structlog contextvars optional — never block the render.
        unbind_contextvars = lambda *_args, **_kw: None  # noqa: E731

    started = datetime.utcnow()
    _set_status(session_id, "rendering")
    _set_progress(session_id, 1, "Starting render")

    # Telemetry: worker has officially started work on this render.
    # Fires once per job pickup (including retries), giving the funnel
    # a measurable "queued → started" latency.
    record_render_started(
        user_id=user_id,
        render_kind="session",
        render_id=session_id,
    )

    try:
        spec = _load_spec(session_id)
        if spec is None:
            return _fail(session_id, "session not found")

        # Camera lane uses cached multi-subject tracking. If the spec has no
        # ``camera.tracks`` we skip the load entirely so the static-crop
        # render stays fast.
        tracking = _load_tracking(session_id) if spec.camera.tracks else None

        with tempfile.TemporaryDirectory(prefix="studio_") as workdir:
            _set_progress(session_id, 5, "Downloading source video")
            local_input = _ensure_source(spec, workdir)
            if local_input is None:
                return _fail(session_id, "could not obtain source video")

            broll_paths: List[str] = []
            if spec.broll.enabled and spec.broll.clips:
                _set_progress(session_id, 20, f"Downloading {len(spec.broll.clips)} B-roll clips")
                broll_paths = _download_broll(spec.broll.clips, workdir)

            _set_progress(session_id, 30, "Preparing captions")
            output_path = _ffmpeg_render(
                spec=spec,
                input_path=local_input,
                broll_paths=broll_paths,
                workdir=workdir,
                session_id=session_id,
                tracking=tracking,
            )

            _set_progress(session_id, 96, "Uploading to storage")
            download_url = _upload_to_r2(output_path, session_id)

            elapsed = (datetime.utcnow() - started).total_seconds()
            _mark_done(session_id, download_url, elapsed)

            logger.warning(
                "studio.render.done",
                session_id=session_id,
                seconds=round(elapsed, 1),
                url=download_url,
            )
            return RenderResult(
                success=True,
                output_path=output_path,
                download_url=download_url,
                duration_seconds=elapsed,
            )

    except subprocess.CalledProcessError as exc:
        err = exc.stderr.decode("utf-8", errors="replace")[-500:] if exc.stderr else str(exc)
        logger.exception("studio.render.ffmpeg_failed", session_id=session_id, error=err)
        report_render_exception(
            exc,
            user_id=user_id,
            render_kind="session",
            render_id=session_id,
            duration_elapsed_s=round(
                (datetime.utcnow() - started).total_seconds(), 2
            ),
            failure_stage="ffmpeg",
        )
        return _fail(session_id, f"ffmpeg failed: {err}")
    except Exception as exc:  # pragma: no cover — top-level safety net
        logger.exception("studio.render.failed", session_id=session_id)
        report_render_exception(
            exc,
            user_id=user_id,
            render_kind="session",
            render_id=session_id,
            duration_elapsed_s=round(
                (datetime.utcnow() - started).total_seconds(), 2
            ),
            failure_stage="unhandled",
        )
        return _fail(session_id, str(exc))
    finally:
        try:
            unbind_contextvars("render_kind", "render_id", "user_id")
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _load_spec(session_id: int) -> Optional[EditSpec]:
    with get_session() as session:
        row = session.get(EditSession, session_id)
        if row is None:
            return None
        try:
            data = json.loads(row.spec or "{}")
            return EditSpec.model_validate(data).normalize()
        except Exception as exc:
            logger.error("studio.render.spec_parse_failed", session_id=session_id, error=str(exc))
            return None


def _load_tracking(session_id: int) -> Optional[dict]:
    """Load cached multi-subject tracking JSON for the Camera lane.

    Returns ``None`` if no payload is cached or it's stale relative to the
    session's current clip times (tracking job must run first).
    """
    with get_session() as session:
        row = session.get(EditSession, session_id)
        if row is None or not row.tracking_json:
            return None
        if row.tracking_start_time != row.source_start_time:
            return None
        if row.tracking_end_time != row.source_end_time:
            return None
        try:
            return json.loads(row.tracking_json)
        except json.JSONDecodeError:
            return None


def _publish_session_event(
    session_id: int,
    status: str,
    *,
    percent: Optional[int] = None,
    message: Optional[str] = None,
    download_url: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Fire a Redis pub/sub event for the session's owner (Week 8).

    Wraps :func:`src.queue.progress.publish_progress`. Looks up the
    owning ``user_id`` first; failure to resolve the user simply
    drops the event (the DB update already happened, so we never
    block a render on the live-events path).
    """
    try:
        from src.queue.progress import publish_progress

        with get_session() as session:
            row = session.get(EditSession, session_id)
            if row is None:
                return
            user_id = row.user_id
        publish_progress(
            user_id=user_id,
            kind="session",
            render_id=session_id,
            status=status,  # type: ignore[arg-type]
            percent=percent,
            message=message,
            download_url=download_url,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "studio.render.publish_failed",
            session_id=session_id,
            error=str(exc),
        )


def _set_status(session_id: int, status: str) -> None:
    with get_session() as session:
        row = session.get(EditSession, session_id)
        if row is None:
            return
        row.last_render_status = status
        row.last_render_error = None
        session.commit()
    _publish_session_event(session_id, status)


def _set_progress(session_id: int, percent: int, message: str) -> None:
    """Persist a coarse progress update. Safe to call frequently — the
    polling endpoint just reads the latest value."""
    percent = max(0, min(100, int(percent)))
    user_id: Optional[int] = None
    with get_session() as session:
        row = session.get(EditSession, session_id)
        if row is None:
            return
        row.render_progress = percent
        row.render_progress_message = message[:200]
        user_id = row.user_id
        session.commit()
    _publish_session_event(
        session_id,
        "rendering",
        percent=percent,
        message=message[:200],
    )
    # Sampled telemetry — the helper drops most calls so log volume
    # stays manageable while we still capture the curve.
    record_render_progress(
        user_id=user_id,
        render_kind="session",
        render_id=session_id,
        percent=float(percent),
        message=message[:200],
    )


def _mark_done(session_id: int, download_url: str, elapsed: float) -> None:
    user_id_for_telemetry: Optional[int] = None
    with get_session() as session:
        row = session.get(EditSession, session_id)
        if row is None:
            return
        row.last_render_status = "done"
        row.last_render_url = download_url
        row.last_render_error = None
        row.last_rendered_at = datetime.utcnow()
        row.render_progress = 100
        row.render_progress_message = "Done"
        user_id_for_telemetry = row.user_id
        session.commit()
    _publish_session_event(
        session_id,
        "done",
        percent=100,
        message="Done",
        download_url=download_url,
    )

    # Charge the user's render-minute meter (Week 8). Computed from
    # the *output* duration (clip end_time - start_time), not the
    # ffmpeg wall clock — what counts toward the budget is what
    # the user actually got out the door. Fail-open: any accounting
    # error logs at warn but never re-raises into the render job.
    minutes_billed: Optional[float] = None
    try:
        from src.features.billing.render_budget import (
            estimate_render_minutes,
            record_render_minutes,
        )

        with get_session() as session:
            row = session.get(EditSession, session_id)
            if row is None:
                return
            user_id = row.user_id
            output_seconds = max(
                0.0,
                (row.source_end_time or 0.0) - (row.source_start_time or 0.0),
            )
        minutes = estimate_render_minutes(output_seconds)
        if minutes > 0:
            record_render_minutes(user_id, minutes)
            minutes_billed = minutes
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "studio.render.budget_record_failed",
            session_id=session_id,
            error=str(exc),
        )

    # Telemetry: render finished + output is reachable. Carries the
    # billed minutes so we can correlate "what the meter charged"
    # vs "what the user expected" without joining tables.
    record_render_completed(
        user_id=user_id_for_telemetry,
        render_kind="session",
        render_id=session_id,
        duration_seconds=round(elapsed, 2),
        output_url=download_url,
        minutes_billed=minutes_billed,
    )


def _fail(session_id: int, message: str) -> RenderResult:
    user_id_for_telemetry: Optional[int] = None
    with get_session() as session:
        row = session.get(EditSession, session_id)
        if row is not None:
            row.last_render_status = "failed"
            row.last_render_error = message[:2000]
            row.render_progress_message = f"Failed: {message[:160]}"
            user_id_for_telemetry = row.user_id
            session.commit()
    logger.warning("studio.render.failed", session_id=session_id, error=message)
    _publish_session_event(
        session_id,
        "failed",
        message=f"Failed: {message[:160]}",
        error=message[:2000],
    )
    record_render_failed(
        user_id=user_id_for_telemetry,
        render_kind="session",
        render_id=session_id,
        error=message[:2000],
    )
    return RenderResult(success=False, error=message)


# ---------------------------------------------------------------------------
# Source-video acquisition
# ---------------------------------------------------------------------------


def _ensure_source(spec: EditSpec, workdir: str) -> Optional[str]:
    """Make sure we have a local mp4 to feed ffmpeg.

    Order of preference:
    1. ``spec.clip.source_clip_path`` if it points to a readable local file or
       an R2 object we can download.
    2. ``spec.clip.source_url`` — if it's a YouTube URL, use yt-dlp; if it's
       an HTTP url, stream it down with ``requests``.
    """
    sp = spec.clip.source_clip_path
    if sp and os.path.exists(sp):
        return sp

    src = spec.clip.source_url
    local_path = os.path.join(workdir, "input.mp4")

    if any(host in src for host in ("youtube.com", "youtu.be")):
        try:
            import yt_dlp  # type: ignore
        except ImportError:
            logger.error("studio.render.yt_dlp_missing")
            return None
        ydl_opts = {
            "format": "best[ext=mp4][height<=1080]/best[ext=mp4]/best",
            "outtmpl": local_path,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([src])
        return local_path if os.path.exists(local_path) else None

    try:
        import httpx

        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            with client.stream("GET", src) as response:
                response.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=1 << 16):
                        f.write(chunk)
        return local_path
    except Exception as exc:
        logger.error("studio.render.download_failed", url=src, error=str(exc))
        return None


def _ensure_background_loop(spec: EditSpec, workdir: str) -> Optional[str]:
    """Download (or look up) the BackgroundLoop video for this spec, returning
    a local mp4 path the ffmpeg filter graph can mount with ``-stream_loop -1``.

    Resolution order:
      1. ``source == "catalog"`` → look up ``catalog_id`` in
         ``background_catalog.FEATURED_LOOPS``. For BUNDLED entries we use
         ``get_local_path`` to skip the network entirely. For the (legacy)
         R2-hosted entries we fall through to httpx like Pexels.
      2. ``source == "pexels"``  → download ``clip_url`` directly.

    Returns ``None`` when no background loop is configured, when the
    referenced catalog id is unknown, or when the download fails — the
    unified renderer then falls back to a solid black canvas behind the
    main video.
    """
    bg = spec.background_loop
    if bg is None:
        return None

    url: Optional[str] = None
    if bg.source == "catalog":
        if not bg.catalog_id:
            return None
        try:
            from src.features.studio.background_catalog import (
                get_featured,
                get_local_path,
            )

            # Bundled procedural asset → use the file already on disk.
            local_bundled = get_local_path(bg.catalog_id)
            if local_bundled:
                return local_bundled

            entry = get_featured(bg.catalog_id)
            url = entry.get("download_url") or None
        except KeyError:
            logger.warning("studio.render.bg_unknown_catalog_id", catalog_id=bg.catalog_id)
            return None
    elif bg.source == "pexels":
        url = bg.clip_url

    if not url:
        logger.warning("studio.render.bg_no_url", source=bg.source, catalog_id=bg.catalog_id)
        return None

    local = os.path.join(workdir, "bgloop.mp4")
    try:
        import httpx

        with httpx.Client(follow_redirects=True, timeout=60.0) as client, client.stream("GET", url) as response:
            response.raise_for_status()
            with open(local, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=1 << 16):
                    f.write(chunk)
        return local
    except Exception as exc:
        logger.warning("studio.render.bg_download_failed", url=url, error=str(exc))
        return None


def _bg_loop_input_args(local_path: str, spec: EditSpec) -> List[str]:
    """Build the ``-stream_loop -1 [-ss <offset>] -i <path>`` input args
    for a background loop. The unified filter graph (Phase 3) reads
    ``[bgloop_input_index:v]`` and composites it under the main video.

    Returns ``[]`` when ``local_path`` is empty so callers can splice the
    result unconditionally."""
    if not local_path or spec.background_loop is None:
        return []
    args: List[str] = ["-stream_loop", "-1"]
    offset = max(0.0, float(spec.background_loop.loop_start_offset_seconds))
    if offset > 0.01:
        args += ["-ss", f"{offset:.3f}"]
    args += ["-i", local_path]
    return args


def _download_brand_logo(spec: EditSpec, workdir: str) -> Optional[str]:
    """Fetch the user's brand logo into ``workdir`` so ffmpeg can overlay it.

    Mirrors ``_download_broll`` — if the URL points at a local static
    upload (``/api/studio/assets/uploads/...``), we resolve to the
    on-disk file directly so the renderer doesn't bounce through the
    proxy / dev server. Returns ``None`` when there's no logo or the
    fetch fails (a missing logo should NEVER kill a render — captions /
    main video still work fine, the brand is just absent).
    """
    bk = spec.brand_kit
    if not bk or not bk.logo_url:
        return None

    url = bk.logo_url

    # Short-circuit: local static upload mounted at /studio/assets/uploads.
    # The frontend prepends "/api" for the Vite dev proxy but older saves
    # may lack the prefix — match the inner suffix so both work.
    local_marker = "/studio/assets/uploads/"
    if local_marker in url:
        tail = url.rsplit(local_marker, 1)[1]
        # ``_local_uploads_dir`` lives in the API router; computed here to
        # avoid an import cycle with the FastAPI routers module.
        local_root = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "assets", "uploads"
            )
        )
        candidate = os.path.normpath(os.path.join(local_root, tail))
        # Defense-in-depth: refuse path traversal.
        if candidate.startswith(local_root) and os.path.isfile(candidate):
            return candidate

    # Remote fetch.
    try:
        import httpx

        ext = os.path.splitext(url.split("?", 1)[0])[1].lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
            ext = ".png"
        local = os.path.join(workdir, f"brand_logo{ext}")
        with httpx.Client(follow_redirects=True, timeout=20.0) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(local, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=1 << 16):
                        f.write(chunk)
        return local
    except Exception as exc:
        logger.warning(
            "studio.render.brand_logo_download_failed",
            url=url,
            error=str(exc),
        )
        return None


def _download_broll(clips: List[BRollClip], workdir: str) -> List[str]:
    """Download each B-roll clip to a numbered file in ``workdir``.

    On failure we return ``""`` for that slot — the caller skips empty slots
    when wiring inputs, so a single dead Pexels URL doesn't tank the render.
    """
    import httpx

    from src.features.studio.broll_library import (
        FEATURED_BROLL,
        get_local_path as _broll_local_path,
    )

    paths: List[str] = []
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        for i, clip in enumerate(clips):
            # Short-circuit for bundled quick-pick assets. The library URL
            # is "/api/studio/assets/broll/<id>.mp4" in the frontend (Vite
            # strips the /api/ prefix) but older saves may have just
            # "/studio/assets/broll/<id>.mp4" — match the inner suffix so
            # both work and we never hit the network for our own files.
            url = clip.clip_url or ""
            asset_id: Optional[str] = None
            marker = "/studio/assets/broll/"
            if marker in url:
                tail = url.rsplit(marker, 1)[1]
                asset_id = tail.split(".", 1)[0] if "." in tail else tail
            if asset_id and asset_id in FEATURED_BROLL:
                local_bundled = _broll_local_path(asset_id)
                if local_bundled:
                    paths.append(local_bundled)
                    continue

            local = os.path.join(workdir, f"broll_{i}.mp4")
            try:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with open(local, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=1 << 16):
                            f.write(chunk)
                paths.append(local)
            except Exception as exc:
                logger.warning(
                    "studio.render.broll_download_failed",
                    index=i,
                    url=url,
                    error=str(exc),
                )
                paths.append("")
    return paths


# ---------------------------------------------------------------------------
# ffmpeg pipeline
# ---------------------------------------------------------------------------


def _ffmpeg_render(
    *,
    spec: EditSpec,
    input_path: str,
    broll_paths: List[str],
    workdir: str,
    session_id: int,
    tracking: Optional[dict] = None,
) -> str:
    """Run a single ffmpeg invocation that produces the final styled MP4.

    Filter graph:
        1. trim to ``clip.start_time``..``clip.end_time`` (via -ss/-to)
        2. crop+scale main video to the target aspect ratio
        3. for each B-roll: scale to cover the canvas, overlay during
           ``[clip.start, clip.end]`` window
        4. burn ASS subtitles (when ``captions.enabled``)
        5. encode H.264 + AAC at sensible web defaults

    When there are no B-roll clips, we use the simpler -vf form which lets
    ffmpeg skip the filter_complex overhead. Anything more than zero B-roll
    upgrades to -filter_complex.
    """
    out_w, out_h = get_output_dimensions(spec.aspect_ratio)
    duration = max(0.01, spec.clip.end_time - spec.clip.start_time)
    output_path = os.path.join(workdir, f"render_{session_id}.mp4")

    # Build the ASS subtitle file once. Pass the MAIN region rect (Week 6
    # split / PiP layouts) so captions stay inside the main video instead
    # of straying into the background-loop area. Brand kit colors/font
    # ride along so user branding flows through to the burned-in caps.
    ass_path: Optional[str] = None
    if spec.captions.enabled and spec.clip.transcript:
        ass_path = os.path.join(workdir, "captions.ass")
        regions_for_ass = regions_for(spec.layout, out_w, out_h)
        write_ass_file(
            captions=spec.captions,
            words=spec.clip.transcript,
            video_width=out_w,
            video_height=out_h,
            out_path=ass_path,
            main_region_y=regions_for_ass.main.y,
            main_region_h=regions_for_ass.main.h,
            brand_kit=spec.brand_kit,
        )

    # Active B-roll clips (downloaded successfully). We filter out empty paths
    # so a single failed download doesn't take down the whole render.
    active_broll = [
        (i, spec.broll.clips[i], broll_paths[i])
        for i in range(len(broll_paths))
        if broll_paths[i]
    ]

    # Background loop (Week 6) — single download attempt before render; the
    # filter graph mounts it as a looped input or falls through to a solid
    # background when unavailable.
    bg_local = _ensure_background_loop(spec, workdir)

    # Brand kit logo (Week 6 polish) — fetched once, overlaid as the final
    # step in ``_cmd_unified``. ``None`` if the user has no logo / fetch
    # fails — never blocks the render.
    logo_local = _download_brand_logo(spec, workdir)

    cmd = _cmd_unified(
        input_path=input_path,
        ass_path=ass_path,
        spec=spec,
        active_broll=active_broll,
        bg_local=bg_local,
        logo_local=logo_local,
        out_w=out_w,
        out_h=out_h,
        output_path=output_path,
        tracking=tracking,
        duration=duration,
    )

    logger.warning(
        "studio.render.ffmpeg_start",
        session_id=session_id,
        out=f"{out_w}x{out_h}",
        captions=spec.captions.enabled,
        style=spec.captions.style.value,
        broll_count=len(active_broll),
    )

    # Stream progress from ffmpeg so we can update render_progress live.
    # Using -progress pipe:1 gives clean key=value lines on stdout while
    # stderr still carries log output for debugging.
    cmd = cmd + ["-progress", "pipe:1", "-nostats"]

    total_frames = max(1, int(duration * _OUTPUT_FPS))
    _set_progress(session_id, 50, "Encoding video")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    last_pct = 50
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("frame="):
                continue
            try:
                frame = int(line.split("=", 1)[1])
            except ValueError:
                continue
            # Map ffmpeg frame count to the 50..95 band so the polling UI
            # has room to show "uploading" at 96..99 afterwards.
            pct = 50 + int(min(45, (frame / total_frames) * 45))
            if pct > last_pct + 1:  # avoid hammering the DB
                _set_progress(session_id, pct, f"Encoding {pct}%")
                last_pct = pct
        stderr_tail = proc.stderr.read() if proc.stderr else ""
    finally:
        proc.wait()

    if proc.returncode != 0:
        # Mirror subprocess.run(check=True) behavior so the outer handler
        # picks this up and tags the session as "failed".
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, stderr=stderr_tail.encode("utf-8", errors="replace")
        )

    return output_path


def _cmd_unified(
    *,
    input_path: str,
    ass_path: Optional[str],
    spec: EditSpec,
    active_broll: List[Tuple[int, BRollClip, str]],
    bg_local: Optional[str],
    logo_local: Optional[str] = None,
    out_w: int,
    out_h: int,
    output_path: str,
    tracking: Optional[dict] = None,
    duration: float,
) -> List[str]:
    """Single ffmpeg command that handles every Week-6 combination.

    Pipeline (always via ``-filter_complex``):

        1. Solid color canvas sized to the output (``color=c=black:s=...``).
        2. (Optional) Background loop scaled+positioned into ``regions.bg``.
        3. Main video cropped (aspect / camera) + auto-zoomed + scaled to
           ``regions.main`` dimensions, then overlaid at ``regions.main`` xy.
        4. Each B-roll scaled to ``regions.main`` dims + transition recipe
           applied + overlaid on top of the main region (so B-rolls stay
           inside the main video frame, not over the background).
        5. Captions burned in over the final canvas.
        6. Audio: source + (optional) per-transition SFX stingers + (optional)
           background-loop audio mixed via ``amix``.

    The previous ``_cmd_simple`` / ``_cmd_with_broll`` split was deleted in
    Week 6 because every interesting feature (bg loops, split layouts,
    per-boundary transitions, SFX mix) now needs ``filter_complex`` anyway.
    Keeping two code paths was strictly a liability — drift between them
    has bitten us twice already (Week 5 fixes had to land twice).
    """
    regions: LayoutRegions = regions_for(spec.layout, out_w, out_h)
    main_rect: Rect = regions.main
    bg_rect: Optional[Rect] = regions.bg

    # --- Build inputs --------------------------------------------------
    inputs: List[str] = [
        "-ss", f"{spec.clip.start_time:.3f}",
        "-to", f"{spec.clip.end_time:.3f}",
        "-i", input_path,
    ]
    next_input_idx = 1  # index of the next -i we add

    broll_input_indices: List[int] = []
    for _, _, path in active_broll:
        inputs.extend(["-i", path])
        broll_input_indices.append(next_input_idx)
        next_input_idx += 1

    bg_input_idx: Optional[int] = None
    if bg_local:
        inputs.extend(_bg_loop_input_args(bg_local, spec))
        bg_input_idx = next_input_idx
        next_input_idx += 1

    # Brand kit logo (Week 6 polish). Added as a normal image input so the
    # overlay step can pick it up after captions. Image inputs don't need
    # special looping flags — they decode as a single still frame which
    # overlay repeats automatically.
    logo_input_idx: Optional[int] = None
    if logo_local:
        inputs.extend(["-i", logo_local])
        logo_input_idx = next_input_idx
        next_input_idx += 1

    # --- Build filter_complex segments ---------------------------------
    parts: List[str] = []

    # 1. Solid canvas sized to the final output. ``d=`` (duration) bounds
    #    the color source so the encoder doesn't see infinite frames.
    parts.append(
        f"color=c=black:s={out_w}x{out_h}:r={_OUTPUT_FPS}:d={duration:.3f}[canvas]"
    )
    last_canvas = "canvas"

    # 2. Background loop layer (optional). The ``trim=duration`` is *critical*
    #    because the input was opened with ``-stream_loop -1`` (infinite
    #    repeats) — without it, overlay's default ``eof_action=repeat`` keeps
    #    the filter graph alive forever and ffmpeg never reaches EOF.
    if bg_input_idx is not None and bg_rect is not None:
        parts.append(
            f"[{bg_input_idx}:v]"
            f"scale={bg_rect.w}:{bg_rect.h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={bg_rect.w}:{bg_rect.h},"
            f"setpts=PTS-STARTPTS,trim=duration={duration:.3f}[bg_scaled]"
        )
        parts.append(
            f"[{last_canvas}][bg_scaled]overlay=x={bg_rect.x}:y={bg_rect.y}:shortest=0:eof_action=pass[bg_done]"
        )
        last_canvas = "bg_done"
    elif bg_input_idx is not None and bg_rect is None:
        # Background configured but layout=single — overlay full-canvas so
        # the user sees their background as the underlay (the main video
        # covers it unless the main has alpha, but the auto-zoom punch-out
        # may create letterboxing during the punch — bg fills it nicely).
        parts.append(
            f"[{bg_input_idx}:v]"
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={out_w}:{out_h},"
            f"setpts=PTS-STARTPTS,trim=duration={duration:.3f}[bg_scaled]"
        )
        parts.append(
            f"[{last_canvas}][bg_scaled]overlay=x=0:y=0:shortest=0:eof_action=pass[bg_done]"
        )
        last_canvas = "bg_done"

    # 3. Main video: crop → scale to main_rect → optional auto-zoom →
    #    overlay onto canvas at main_rect xy. Auto-zoom math is keyed to
    #    main_rect's dimensions so the center-crop math stays accurate.
    crop = _crop_filter_for_aspect(spec, main_rect.w, main_rect.h, tracking=tracking)
    zoom_filter = _build_auto_zoom_filter(spec, main_rect.w, main_rect.h)
    zoom_segment = f",{zoom_filter}" if zoom_filter else ""
    parts.append(
        f"[0:v]{crop},scale={main_rect.w}:{main_rect.h}:flags=lanczos{zoom_segment},"
        f"setpts=PTS-STARTPTS[main_scaled]"
    )
    parts.append(
        f"[{last_canvas}][main_scaled]overlay=x={main_rect.x}:y={main_rect.y}[main_done]"
    )
    last_canvas = "main_done"

    # 4. B-roll overlays — sized to the MAIN region, positioned at main_rect
    #    xy. Per-boundary transitions (Week 6 Phase 4) look up the IN edge's
    #    type for the clip's animation (the catalog recipes are self-
    #    contained "in + out" units, so we use the IN edge's type for the
    #    visible recipe). The OUT edge's type still drives a different SFX
    #    stinger at clip.end via ``_collect_all_boundaries`` below.
    for clip_pos, (_orig_i, clip, _path) in enumerate(active_broll):
        i_ff = broll_input_indices[clip_pos]
        win = max(0.01, clip.end - clip.start)
        in_type, in_dur, _in_sfx = _resolve_boundary_tx(spec, _broll_in_id(clip))
        _out_type, out_dur, _out_sfx = _resolve_boundary_tx(spec, _broll_out_id(clip))
        # Pick the longer of the two edge durations so a long "out" still
        # has time to play even when the "in" is a quick cut.
        tx_dur = max(in_dur, out_dur)
        tdef = get_transition(in_type.value)
        ctx = _broll_tx_ctx(clip, main_rect.w, main_rect.h, tx_dur)
        subgraph = (
            f"[{i_ff}:v]"
            f"scale={main_rect.w}:{main_rect.h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={main_rect.w}:{main_rect.h},"
            f"setpts=PTS-STARTPTS,"
            f"trim=duration={win:.3f}"
        )
        if tx_dur > 0.01:
            subgraph += tdef.broll_filter_extension(ctx)
        parts.append(subgraph + f"[bv{clip_pos}]")

        if clip.opacity < 0.999:
            parts.append(
                f"[bv{clip_pos}]format=yuva420p,"
                f"colorchannelmixer=aa={clip.opacity:.3f}[bvop{clip_pos}]"
            )
            bv = f"bvop{clip_pos}"
        else:
            bv = f"bv{clip_pos}"

        x_expr_local = tdef.overlay_x_expr(ctx) if tx_dur > 0.01 else "0"
        y_expr_local = tdef.overlay_y_expr(ctx) if tx_dur > 0.01 else "0"
        # The overlay-x/y expressions returned by the catalog are LOCAL to
        # the main region (centered on x=0 inside a main_w-wide area). We
        # need to shift them into canvas-absolute coordinates by adding
        # main_rect.x / main_rect.y so the overlay lands on top of the
        # main video, not at the canvas origin.
        if x_expr_local == "0":
            x_abs = str(main_rect.x)
        else:
            # x_expr_local is wrapped in single-quotes (catalog convention)
            # so we have to splice without breaking the quoting. ffmpeg
            # accepts arithmetic inside the quoted expression.
            inner = x_expr_local.strip("'")
            x_abs = f"'({inner})+{main_rect.x}'"
        if y_expr_local == "0":
            y_abs = str(main_rect.y)
        else:
            inner = y_expr_local.strip("'")
            y_abs = f"'({inner})+{main_rect.y}'"

        out_label = f"c{clip_pos}"
        parts.append(
            f"[{last_canvas}][{bv}]overlay="
            f"enable='between(t,{clip.start:.3f},{clip.end:.3f})'"
            f":x={x_abs}:y={y_abs}:format=auto"
            f"[{out_label}]"
        )
        last_canvas = out_label

    # 5. Captions burned in over the final canvas. The ass file already
    #    has its own PlayResX/Y matching the output dims, so it draws at
    #    full canvas resolution (captions span the entire frame, on top
    #    of both the main region and any background).
    if ass_path:
        parts.append(
            f"[{last_canvas}]subtitles=filename={_escape_ffmpeg_path(ass_path)}[withcaps]"
        )
        last_canvas = "withcaps"

    # 6. Brand kit logo overlay (Week 6 polish). Draws ABOVE captions so
    #    branding is always the topmost layer — matches how the Remotion
    #    preview composites it. Logo is scaled to ~12% of the output
    #    width (preserving aspect via -1 height) and faded to the user's
    #    chosen opacity via colorchannelmixer. Position picks one of four
    #    corner anchors with a 24px margin (scaled to output size).
    if logo_input_idx is not None and spec.brand_kit:
        bk = spec.brand_kit
        logo_target_w = max(80, int(out_w * 0.12))
        margin = max(16, int(out_w * 0.022))
        opacity = max(0.05, min(1.0, float(bk.logo_opacity)))
        position = bk.logo_position or "br"
        # ``W`` and ``H`` are overlay-evaluated as the underlay width/height,
        # ``w`` and ``h`` are the overlay (logo) width/height.
        pos_xy = {
            "tl": (f"{margin}", f"{margin}"),
            "tr": (f"W-w-{margin}", f"{margin}"),
            "bl": (f"{margin}", f"H-h-{margin}"),
            "br": (f"W-w-{margin}", f"H-h-{margin}"),
        }[position]
        parts.append(
            f"[{logo_input_idx}:v]"
            f"scale={logo_target_w}:-1:flags=lanczos,"
            f"format=rgba,colorchannelmixer=aa={opacity:.3f}[logo_scaled]"
        )
        parts.append(
            f"[{last_canvas}][logo_scaled]overlay="
            f"x={pos_xy[0]}:y={pos_xy[1]}:format=auto:shortest=0:eof_action=pass[vout]"
        )
        v_map = "[vout]"
    elif ass_path:
        v_map = "[withcaps]"
    else:
        v_map = f"[{last_canvas}]"

    # 7. Audio: source + per-boundary SFX. Each boundary uses its own
    #    transition's stinger (Week 6 Phase 4) so a fade-in + zoom-out clip
    #    can play different sounds at each edge.
    sfx_base_idx = next_input_idx  # SFX inputs follow main + brolls + bg + logo
    sfx_inputs, sfx_filters, sfx_audio_label = _build_sfx_mix(
        spec,
        base_input_index=sfx_base_idx,
    )
    if sfx_filters:
        parts.extend(sfx_filters)
    audio_map = sfx_audio_label or "0:a?"

    filter_complex = ";".join(parts)

    return [
        _ffmpeg_bin(),
        "-y",
        *inputs,
        *sfx_inputs,
        "-filter_complex", filter_complex,
        "-map", v_map,
        "-map", audio_map,
        "-r", str(_OUTPUT_FPS),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]


def _broll_tx_ctx(clip: BRollClip, out_w: int, out_h: int, tx_dur: float) -> dict:
    """Build the context dict passed to a TransitionDef's recipe functions.

    Centralizes the shape expected by ``transition_catalog`` so anyone
    adding a new transition only writes ffmpeg expressions in terms of the
    keys defined here. Keeping the shape symmetric with the Remotion
    ``transitionRecipes.ts`` payload makes preview/render parity trivial.
    """
    return {
        "start": float(clip.start),
        "end": float(clip.end),
        "win": max(0.01, float(clip.end - clip.start)),
        "duration_s": float(tx_dur),
        "out_w": int(out_w),
        "out_h": int(out_h),
    }


# ---------------------------------------------------------------------------
# Week 5 — auto-zoom + transitions + SFX
# ---------------------------------------------------------------------------


def _build_auto_zoom_filter(
    spec: EditSpec, target_w: int, target_h: int
) -> Optional[str]:
    """Render ``spec.auto_zoom`` as an ffmpeg ``scale=…,crop=`` chain.

    Strategy: build a per-frame ``z(t)`` that's 1.0 everywhere except
    around each requested timestamp, where it smoothsteps up to
    ``max_scale``, holds briefly, then smoothsteps back to 1.0. The pulses
    don't overlap (auto-zoom endpoint enforces 3s spacing >> 1.0s pulse)
    so we can just sum them and add 1.0 to keep the expression bounded.

    Returns ``None`` when auto-zoom is disabled, has no timestamps, or
    has max_scale ≈ 1.0 (would be a no-op).
    """
    if not spec.auto_zoom.enabled or not spec.auto_zoom.timestamps:
        return None
    max_scale = max(1.0, min(2.0, float(spec.auto_zoom.max_scale)))
    if max_scale <= 1.001:
        return None
    timestamps = sorted({round(float(t), 3) for t in spec.auto_zoom.timestamps})
    if not timestamps:
        return None

    # Pulse shape: 200ms ramp-in, 400ms hold, 400ms ramp-out (1s total).
    EASE_IN, HOLD, EASE_OUT = 0.2, 0.4, 0.4
    bump = max_scale - 1.0
    pulses: List[str] = []
    for t in timestamps:
        t_in0 = max(0.0, t - EASE_IN)
        t_peak = t
        t_hold_end = t + HOLD
        t_end = t + HOLD + EASE_OUT
        # smoothstep(p) = 3p² - 2p³ keyed by relative position in the ramp.
        p_in = f"((t-{t_in0:.4f})/{EASE_IN:.4f})"
        ramp_in = f"({bump:.4f}*(3*{p_in}*{p_in}-2*{p_in}*{p_in}*{p_in}))"
        p_out = f"((t-{t_hold_end:.4f})/{EASE_OUT:.4f})"
        ramp_out = (
            f"({bump:.4f}*(1-(3*{p_out}*{p_out}-2*{p_out}*{p_out}*{p_out})))"
        )
        pulse = (
            f"if(lt(t,{t_peak:.4f}),"
            f"if(lt(t,{t_in0:.4f}),0,{ramp_in}),"
            f"if(lt(t,{t_hold_end:.4f}),{bump:.4f},"
            f"if(lt(t,{t_end:.4f}),{ramp_out},0)))"
        )
        pulses.append(pulse)

    sum_expr = "+".join(pulses) if pulses else "0"
    z_expr = f"(1+({sum_expr}))"

    # Scale up by z(t), then center-crop back to the target rectangle.
    # ``trunc(...)/2*2`` forces even pixel dimensions (libx264 requirement).
    new_w = f"trunc({target_w}*{z_expr}/2)*2"
    new_h = f"trunc({target_h}*{z_expr}/2)*2"
    return (
        f"scale=w='{new_w}':h='{new_h}':eval=frame:flags=lanczos,"
        f"crop={target_w}:{target_h}:(iw-{target_w})/2:(ih-{target_h})/2"
    )


# ---------------------------------------------------------------------------
# Per-boundary transition resolution (Week 6 Phase 4)
# ---------------------------------------------------------------------------
#
# Boundary ID scheme — stable across saves because BRollClip.id / CameraCut.id
# are persisted with the spec. The frontend BoundaryMarkers overlay generates
# matching IDs so click-to-edit lines up with these resolver lookups.
#
#   - ``broll_<clip.id>_in``   B-roll's leading edge (at ``clip.start``)
#   - ``broll_<clip.id>_out``  B-roll's trailing edge (at ``clip.end``)
#   - ``camera_cut_<cut.id>``  Camera cut's switch (at ``cut.start``)


def _broll_in_id(clip: BRollClip) -> str:
    return f"broll_{clip.id}_in"


def _broll_out_id(clip: BRollClip) -> str:
    return f"broll_{clip.id}_out"


def _camera_cut_id(cut: CameraCut) -> str:
    return f"camera_cut_{cut.id}"


def _resolve_boundary_tx(
    spec: EditSpec, boundary_id: str
) -> Tuple[TransitionType, float, bool]:
    """Look up the effective transition for a boundary.

    Precedence:
      1. Matching entry in ``spec.boundary_transitions``  → use that.
      2. ``spec.transitions.enabled``                     → fall back to global.
      3. Otherwise                                        → ``(CUT, 0, False)``.

    Returns ``(type, duration_seconds, sfx_enabled)``.
    """
    for inst in spec.boundary_transitions:
        if inst.boundary_id == boundary_id:
            return (
                inst.type,
                max(0.0, inst.duration_ms / 1000.0),
                bool(inst.sfx_enabled),
            )
    if spec.transitions.enabled:
        return (
            spec.transitions.type,
            max(0.0, spec.transitions.duration_ms / 1000.0),
            bool(spec.transitions.sfx_enabled),
        )
    return (TransitionType.CUT, 0.0, False)


def _collect_all_boundaries(
    spec: EditSpec,
) -> List[Tuple[float, TransitionType, bool]]:
    """Enumerate every boundary in clip-local time with its resolved
    transition. Used by the SFX mixer to schedule the right stinger at each
    moment (different per boundary in Week 6).

    Returns a sorted list of ``(time_seconds, type, sfx_enabled)``.
    Boundaries with ``type == CUT`` or ``sfx_enabled == False`` are still
    emitted so the caller can decide whether to drop them — keeps this
    function purely descriptive of the timeline rather than mixing in SFX
    policy.
    """
    out: List[Tuple[float, TransitionType, bool]] = []

    if spec.broll.enabled:
        for clip in spec.broll.clips:
            in_type, _in_dur, in_sfx = _resolve_boundary_tx(spec, _broll_in_id(clip))
            out.append((float(clip.start), in_type, in_sfx))
            if clip.end - clip.start > 0.5:
                out_type, _out_dur, out_sfx = _resolve_boundary_tx(
                    spec, _broll_out_id(clip)
                )
                out.append((float(clip.end), out_type, out_sfx))

    if spec.camera.tracks:
        cuts = sorted(spec.camera.tracks, key=lambda c: c.start)
        for i in range(len(cuts) - 1):
            a = cuts[i]
            b = cuts[i + 1]
            if int(a.subject_id) == int(b.subject_id):
                continue
            b_type, _b_dur, b_sfx = _resolve_boundary_tx(spec, _camera_cut_id(b))
            out.append((float(b.start), b_type, b_sfx))

    return sorted(out, key=lambda x: x[0])


# ---------------------------------------------------------------------------
# Transition boundaries (B-roll + camera) + SFX mixing
# ---------------------------------------------------------------------------

# Where the SFX wav files live on disk. ``_SFX_DIR`` is computed at import
# time so render workers running in tempdirs can still find the assets.
# Three dirnames: render.py → studio/ → features/ → src/, then ``assets/sfx``.
_SFX_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets",
    "sfx",
)


def _sfx_path(tx_type: TransitionType) -> Optional[str]:
    """Resolve the SFX wav for a transition type via the catalog.

    Returns ``None`` when the type has no SFX assignment or the asset
    file is missing on disk — caller falls back to no SFX rather than
    failing the render."""
    name = get_transition(tx_type.value).sfx_file
    if not name:
        return None
    path = os.path.join(_SFX_DIR, name)
    return path if os.path.exists(path) else None


def _build_sfx_mix(
    spec: EditSpec,
    *,
    base_input_index: int = 1,
) -> Tuple[List[str], List[str], Optional[str]]:
    """Build ffmpeg inputs + filter_complex segments to mix per-boundary
    transition stingers over the source audio.

    Week 6 Phase 4: walks ``_collect_all_boundaries(spec)`` so each
    boundary uses its OWN transition type's SFX file (a fade-in + zoom-out
    clip plays a soft fade.wav at its leading edge and a punchy zoom.wav
    at its trailing edge).

    Returns ``(extra_inputs, filter_segments, audio_label)``:
      - ``extra_inputs`` is a flat list of ``-i path`` pairs to splice
        into the ffmpeg command after the main video + B-roll + bg inputs.
      - ``filter_segments`` is a list of filter-graph strings (no trailing
        ``;``) that delay each SFX to its boundary time and mix them with
        the source audio.
      - ``audio_label`` is the final ``-map`` argument (e.g. ``[aout]``)
        or ``None`` when nothing was mixed (caller falls back to ``0:a?``).

    Silently no-ops when no boundary has SFX enabled, or when every
    matching transition type lacks an on-disk asset.
    """
    boundaries = _collect_all_boundaries(spec)
    if not boundaries:
        return [], [], None

    # Resolve each boundary into (time, sfx_path) — drop boundaries that
    # don't have SFX enabled or whose transition type has no asset on
    # disk so the filter graph stays minimal.
    queued: List[Tuple[float, str]] = []
    for t_sec, tx_type, sfx_enabled in boundaries:
        if not sfx_enabled:
            continue
        if tx_type == TransitionType.CUT:
            continue
        path = _sfx_path(tx_type)
        if path is None:
            continue
        queued.append((t_sec, path))

    if not queued:
        return [], [], None

    # Dedupe near-duplicate boundaries (within 150ms) — but only when they
    # share the same SFX file. Different stingers within 150ms still play
    # because the user explicitly picked distinct types per boundary.
    deduped: List[Tuple[float, str]] = []
    for t_sec, path in queued:
        if deduped and deduped[-1][1] == path and (t_sec - deduped[-1][0]) <= 0.15:
            continue
        deduped.append((t_sec, path))
    # Hard cap so a runaway transcript can't blow up the filter graph.
    deduped = deduped[:24]

    inputs: List[str] = []
    for _, path in deduped:
        inputs.extend(["-i", path])

    sfx_labels: List[str] = []
    segments: List[str] = []
    for k, (t_sec, _path) in enumerate(deduped):
        delay_ms = max(0, int(round(t_sec * 1000)))
        in_idx = base_input_index + k
        out_label = f"sfx{k}"
        # adelay with two channels handles stereo; ffmpeg pads mono inputs
        # automatically. apad keeps the stream alive so amix doesn't end
        # the audio early when the SFX is shorter than the source.
        segments.append(
            f"[{in_idx}:a]adelay={delay_ms}|{delay_ms},apad[{out_label}]"
        )
        sfx_labels.append(f"[{out_label}]")

    mix_inputs = "[0:a]" + "".join(sfx_labels)
    segments.append(
        f"{mix_inputs}amix=inputs={len(sfx_labels) + 1}:duration=first:"
        f"dropout_transition=0:normalize=0[aout]"
    )

    return inputs, segments, "[aout]"


def _escape_ffmpeg_path(path: str) -> str:
    """Escape an absolute path for use inside an ffmpeg filter ``filename=`` arg.

    ffmpeg's option parser treats ``:`` and ``\\`` specially even inside
    ``filename=``. Cross-platform safe.
    """
    safe = path.replace("\\", "/")
    return safe.replace("\\", r"\\").replace(":", r"\:")


def _crop_filter_for_aspect(
    spec: EditSpec,
    target_w: int,
    target_h: int,
    *,
    tracking: Optional[dict] = None,
) -> str:
    """Return an ffmpeg ``crop=`` filter producing the correct aspect ratio.

    Three modes, in order of precedence:
      1. ``spec.camera.tracks`` non-empty AND tracking cached → piecewise
         per-subject crop curve. This is the Week-4 multi-cam path.
      2. ``spec.crop`` explicit → static rectangle from SubjectTracker.
      3. Otherwise → centered crop matching the output aspect.
    """
    if spec.camera.tracks and tracking is not None and tracking.get("subjects"):
        camera_filter = _build_camera_crop_filter(spec, tracking, target_w, target_h)
        if camera_filter is not None:
            return camera_filter
        # Fall through to the static modes if we couldn't build a sensible
        # filter (e.g. cuts reference a subject that no longer exists).

    if spec.crop is not None:
        return f"crop={spec.crop.width}:{spec.crop.height}:{spec.crop.x}:{spec.crop.y}"

    # Defer to ffmpeg's ``ih*<ratio>`` math so we don't need to probe the
    # source for dimensions at this layer — keeps the render job stateless.
    if target_h >= target_w:  # portrait or square
        ratio = target_w / target_h
        return f"crop='ih*{ratio:.6f}':ih:(iw-ih*{ratio:.6f})/2:0"
    # landscape: crop horizontally if source is taller than target
    ratio = target_h / target_w
    return f"crop=iw:'iw*{ratio:.6f}':0:(ih-iw*{ratio:.6f})/2"


def _build_camera_crop_filter(
    spec: EditSpec, tracking: dict, target_w: int, target_h: int
) -> Optional[str]:
    """Translate Camera lane cuts + cached tracking into a piecewise
    ``crop=W:H:'<x_expr>':y`` ffmpeg filter.

    Strategy: pre-compute the desired crop_x at low frequency (10 Hz) by
    walking the cuts and sampling each cut's subject's smoothed_crop_x;
    optionally smoothstep across ±100ms windows at cut boundaries for the
    ``ease_pan`` mode; then emit a single nested-if expression that lerps
    between adjacent samples. Doing the heavy logic in Python (instead of
    encoding everything as ffmpeg expressions) keeps the filter string
    bounded and easy to debug.
    """
    subjects = tracking.get("subjects") or []
    if not subjects:
        return None

    frame_w = int(tracking.get("frame_w", 1920))
    frame_h = int(tracking.get("frame_h", 1080))
    fps = float(tracking.get("fps", 30.0))
    if fps <= 0:
        fps = 30.0

    # Crop window matches the target aspect ratio while taking full height
    # of the source. For landscape targets we just defer to the centered
    # fallback — multi-cam pan only makes sense when cropping horizontally.
    if target_h < target_w:
        return None
    aspect = target_w / target_h
    crop_w = max(2, int(round(frame_h * aspect)))
    if crop_w > frame_w:
        # Source already at-or-narrower than target aspect → there's nothing
        # to pan. Let the static-crop fallback handle it.
        return None

    duration = max(0.01, spec.clip.end_time - spec.clip.start_time)
    cuts = sorted(spec.camera.tracks, key=lambda c: c.start)

    subj_map = {int(s["id"]): list(s.get("smoothed_crop_x") or []) for s in subjects}

    def _center_x() -> int:
        return (frame_w - crop_w) // 2

    def x_for_subject_at(sid: int, t: float) -> int:
        """Sample subject ``sid``'s smoothed center_x at clip-local time ``t``.

        ``smoothed_crop_x`` is indexed by source-video frame number within
        the cached segment. Tracking is computed in source-time so we use
        ``fps`` directly — no rescale needed.
        """
        series = subj_map.get(sid) or []
        if not series:
            return _center_x()
        idx = int(round(t * fps))
        idx = max(0, min(len(series) - 1, idx))
        cx = series[idx]
        # smoothed_crop_x is already crop-x (top-left), but clamp defensively.
        return max(0, min(frame_w - crop_w, int(cx)))

    def active_cut_at(t: float):
        for c in cuts:
            if c.start <= t < c.end:
                return c
        return None

    sample_hz = 10
    dt = 1.0 / sample_hz
    n_samples = max(2, int(duration * sample_hz) + 1)
    samples: List[List[float]] = []
    for i in range(n_samples):
        t = min(duration, i * dt)
        c = active_cut_at(t)
        if c is None:
            x = _center_x()
        else:
            x = x_for_subject_at(int(c.subject_id), t)
        samples.append([round(t, 4), int(x)])

    # Ease-pan: at each cut boundary, smoothstep-blend the previous & next
    # subject's curves across a ±100ms window so the camera glides rather
    # than snapping. Transitions.enabled with type=fade/swipe widens the
    # ease window so the visible cut feels deliberately animated rather
    # than a hidden auto-correction.
    ease_active = spec.camera.ease_pan
    fade_widen = (
        spec.transitions.enabled
        and spec.transitions.type != TransitionType.CUT
    )
    if ease_active or fade_widen:
        base_ease = 0.1
        widened = max(
            base_ease,
            (spec.transitions.duration_ms / 2000.0) if fade_widen else 0.0,
        )
        ease = widened if (fade_widen and not ease_active) else max(base_ease, widened)
        if len(cuts) >= 2 and ease > 0:
            for i in range(len(cuts) - 1):
                boundary = cuts[i].end
                prev_sid = int(cuts[i].subject_id)
                next_sid = int(cuts[i + 1].subject_id)
                if prev_sid == next_sid:
                    continue
                for s in samples:
                    ts = s[0]
                    if boundary - ease <= ts <= boundary + ease:
                        p = (ts - (boundary - ease)) / (2 * ease)
                        p = max(0.0, min(1.0, p))
                        w = 3 * p * p - 2 * p * p * p  # smoothstep
                        a = x_for_subject_at(prev_sid, ts)
                        b = x_for_subject_at(next_sid, ts)
                        s[1] = int(round(a + (b - a) * w))

    # Build a nested-if linear-interpolation expression for x(t).
    # Last sample first so the chain reads earliest-to-latest in t.
    if len(samples) == 1:
        x_expr = str(samples[0][1])
    else:
        x_expr = str(samples[-1][1])
        for i in range(len(samples) - 2, -1, -1):
            t0, x0 = samples[i]
            t1, x1 = samples[i + 1]
            dt_seg = t1 - t0
            if dt_seg <= 0 or x0 == x1:
                interp = str(int(x0))
            else:
                slope = (x1 - x0) / dt_seg
                interp = f"({x0}+({slope:.4f})*(t-{t0:.4f}))"
            x_expr = f"if(lt(t,{t1:.4f}),{interp},{x_expr})"

    return f"crop={crop_w}:{frame_h}:'{x_expr}':0"


_FFMPEG_FULL_CANDIDATES = (
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",  # macOS Apple Silicon
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",     # macOS Intel
    "/opt/ffmpeg-full/bin/ffmpeg",               # Linux custom prefix
)


def _ffmpeg_bin() -> str:
    """Resolve the ffmpeg binary.

    Prefers ``ffmpeg-full`` (the keg-only Homebrew formula that ships with
    ``libass`` so caption burn-in works) when available, falling back to the
    PATH ``ffmpeg`` for production Docker images and CI. Set the
    ``FFMPEG_BIN`` env var to override completely.
    """
    explicit = os.environ.get("FFMPEG_BIN")
    if explicit and os.path.exists(explicit):
        return explicit

    for cand in _FFMPEG_FULL_CANDIDATES:
        if os.path.exists(cand):
            return cand

    return shutil.which("ffmpeg") or "ffmpeg"


# ---------------------------------------------------------------------------
# R2 upload
# ---------------------------------------------------------------------------


def _upload_to_r2(local_path: str, session_id: int) -> str:
    """Upload the rendered MP4 to R2 and return a public URL.

    Gracefully degrades to a local file:// URL in dev when R2 isn't
    configured, so the Studio is usable on a fresh checkout without
    cloud creds.
    """
    settings = get_settings()
    if not (settings.r2_account_id and settings.r2_access_key_id and settings.r2_secret_access_key):
        logger.warning("studio.render.r2_not_configured", local=local_path)
        return f"file://{local_path}"

    try:
        from src.video_analysis.storage import R2Storage

        storage = R2Storage(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket_name=settings.r2_bucket_name or "viewmagnet-videos",
        )

        key = f"studio/{session_id}/{uuid.uuid4().hex}.mp4"
        with open(local_path, "rb") as f:
            storage.client.upload_fileobj(
                f,
                storage.bucket_name,
                key,
                ExtraArgs={"ContentType": "video/mp4"},
            )

        public_base = (settings.r2_public_url or "").rstrip("/")
        if public_base and not public_base.startswith("http://localhost"):
            return f"{public_base}/{key}"

        return storage.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": storage.bucket_name, "Key": key},
            ExpiresIn=60 * 60 * 24 * 7,  # 7 days
        )
    except Exception as exc:
        logger.exception("studio.render.r2_upload_failed", error=str(exc))
        # Fall back to a local path so the user still gets *something* clickable.
        return f"file://{local_path}"
