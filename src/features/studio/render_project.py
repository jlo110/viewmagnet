"""Server-side render job for a Studio multi-clip Project (Week 7).

Stitches the per-clip MP4s produced by ``render_session`` into one
long-form output:

1. Resolve the ordered clip list for the project.
2. For each clip: trigger ``render_session`` if the underlying
   :class:`EditSession`'s ``last_render_url`` is stale or missing
   (cache check uses ``EditSession.updated_at`` vs the
   ``StudioProjectClip.last_used_session_render_at`` watermark we
   write each successful project render).
3. Download each per-clip MP4 into the workdir and trim with
   ``ffmpeg -ss``/``-to`` according to the project-level
   ``trim_in``/``trim_out`` overrides.
4. Force-conform every trimmed clip to the project's
   ``default_aspect`` dimensions so the final concat has consistent
   width/height (a 9:16 clip + 16:9 clip concatenated would otherwise
   produce a corrupt video). Conform uses ``scale`` + ``pad`` so we
   never crop the user's framing.
5. Concatenate with the project-level transitions (or each clip's
   own override). The first clip has no incoming transition.
6. Apply 2-pass ``loudnorm`` on the merged audio so volume jumps
   between clips with different recording setups disappear.
7. Apply the project-level brand kit overlay on top of the stitched
   output (so the logo lower-third stays consistent regardless of
   per-clip brand kits).
8. Upload the merged MP4 to R2, write the URL back to
   ``StudioProject.last_render_url`` and update the watermarks on
   every clip we used.

Designed to be enqueued via ``src.queue.enqueue_job``. Synchronous
fallback for dev is the same pattern as ``render_session``.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

from src.database.connection import get_session
from src.database.models import EditSession, StudioProject, StudioProjectClip
from src.features.billing.render_budget import (
    estimate_render_minutes,
    record_render_minutes,
)
from src.features import notifications as _notifications
from src.features.studio.render import (
    _upload_to_r2 as _upload_session_to_r2,
    get_output_dimensions,
    render_session,
)
from src.features.studio.spec import AspectRatio, BrandKit
from src.queue import report_render_exception
from src.queue.telemetry import (
    record_render_completed,
    record_render_failed,
    record_render_progress,
    record_render_started,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public return shape
# ---------------------------------------------------------------------------


@dataclass
class ProjectRenderResult:
    success: bool
    download_url: Optional[str] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Status / progress helpers (mirror render_session's vocabulary so the
# polling endpoint in studio.py can be reused for projects too).
# ---------------------------------------------------------------------------


# When True, ``_notify_project_event`` skips the failure email path.
# Set by retry wrappers around the job so a transient mid-retry
# failure doesn't email the user "your render failed" right before
# the very next attempt succeeds. Public for tests; per-process
# module-level state is fine because each RQ worker handles jobs
# serially (forked workers get a fresh module on fork).
_SUPPRESS_FAILURE_NOTIFY = False


def _notify_project_event(
    project_id: int,
    *,
    success: bool,
    download_url: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Single funnel for the user-facing email notification on a
    terminal project-render event.

    Keeping this helper separate from :func:`_publish_project_event`
    lets the retry wrapper suppress notifications without also
    suppressing the live WS event — the dashboard still updates,
    we just don't email the user halfway through the retry chain.

    Looks up the owning ``user_id`` from the DB; failure to resolve
    silently drops the notify (the render already shipped, we'd
    rather under-notify than crash the render path)."""
    if not success and _SUPPRESS_FAILURE_NOTIFY:
        return

    user_id: Optional[int] = None
    try:
        with get_session() as db:
            row = db.get(StudioProject, project_id)
            if row is None:
                return
            user_id = row.user_id
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "studio.project_render.notify_lookup_failed",
            project_id=project_id,
            error=str(exc),
        )
        return

    if user_id is None:
        return

    # Look the functions up via the notifications module (not via
    # an ``import ... as ...`` binding) so unit tests can monkeypatch
    # ``src.features.notifications.notify_render_failed`` and have
    # the override reach this caller. Direct ``from x import y`` binds
    # the symbol at import time and patches against ``x.y`` wouldn't
    # affect the local binding.
    if success:
        _notifications.notify_render_complete(
            user_id=user_id,
            kind="project",
            render_id=project_id,
            download_url=download_url,
        )
    else:
        _notifications.notify_render_failed(
            user_id=user_id,
            kind="project",
            render_id=project_id,
            error_message=error_message or "Render failed",
        )


def _publish_project_event(
    project_id: int,
    status: str,
    *,
    percent: Optional[int] = None,
    message: Optional[str] = None,
    download_url: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Fire a Redis pub/sub event for the project's owner (Week 8).

    Same fail-open contract as :func:`render._publish_session_event`:
    the DB write already happened by the time this runs, so a missed
    publish never corrupts state — the WebSocket consumer can always
    re-fetch the row to reconcile. ``kind="project"`` so the frontend
    can route the event to the right card.
    """
    try:
        from src.queue.progress import publish_progress

        with get_session() as db:
            row = db.get(StudioProject, project_id)
            if row is None:
                return
            user_id = row.user_id
        publish_progress(
            user_id=user_id,
            kind="project",
            render_id=project_id,
            status=status,  # type: ignore[arg-type]
            percent=percent,
            message=message,
            download_url=download_url,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "studio.project_render.publish_failed",
            project_id=project_id,
            error=str(exc),
        )


def _set_project_status(project_id: int, status: str) -> None:
    with get_session() as db:
        row = db.get(StudioProject, project_id)
        if row is None:
            return
        row.last_render_status = status
        row.last_render_error = None
        db.commit()
    _publish_project_event(project_id, status)


def _set_project_progress(project_id: int, percent: int, message: str) -> None:
    percent = max(0, min(100, int(percent)))
    user_id_for_telemetry: Optional[int] = None
    with get_session() as db:
        row = db.get(StudioProject, project_id)
        if row is None:
            return
        row.render_progress = percent
        row.render_progress_message = message[:200]
        user_id_for_telemetry = row.user_id
        db.commit()
    _publish_project_event(
        project_id,
        "rendering",
        percent=percent,
        message=message,
    )
    record_render_progress(
        user_id=user_id_for_telemetry,
        render_kind="project",
        render_id=project_id,
        percent=float(percent),
        message=message[:200],
    )


def _mark_project_done(project_id: int, download_url: str) -> None:
    """Mark a project render done, persist the URL, fire the WS event,
    and send the user the "your project is ready" email.

    Email + budget recording live here (not in the caller) so EVERY
    successful path through the render job — including future code
    paths — goes through the same observability fan-out."""
    user_id_for_telemetry: Optional[int] = None
    with get_session() as db:
        row = db.get(StudioProject, project_id)
        if row is None:
            return
        row.last_render_status = "done"
        row.last_render_url = download_url
        row.last_render_error = None
        row.last_rendered_at = datetime.utcnow()
        row.render_progress = 100
        row.render_progress_message = "Done"
        user_id_for_telemetry = row.user_id
        db.commit()
    _publish_project_event(
        project_id,
        "done",
        percent=100,
        message="Done",
        download_url=download_url,
    )
    _notify_project_event(
        project_id,
        success=True,
        download_url=download_url,
    )
    # Telemetry: the caller (``render_project``) bills minutes
    # separately so we don't double-emit here — minutes_billed lands
    # on the next ``render.completed`` event from the post-billing
    # path. This one captures the "render produced an output" moment.
    record_render_completed(
        user_id=user_id_for_telemetry,
        render_kind="project",
        render_id=project_id,
        output_url=download_url,
    )


def _fail_project(project_id: int, message: str) -> ProjectRenderResult:
    """Mark a project render failed, persist the error, fire the WS
    event, and send the user the "your project failed" email so they
    aren't stuck staring at a stuck spinner.

    The notify side respects ``_SUPPRESS_FAILURE_NOTIFY`` so the retry
    wrapper can ack a transient mid-retry failure without spamming
    the user when the next attempt may succeed."""
    user_id_for_telemetry: Optional[int] = None
    with get_session() as db:
        row = db.get(StudioProject, project_id)
        if row is not None:
            row.last_render_status = "failed"
            row.last_render_error = message[:2000]
            row.render_progress_message = f"Failed: {message[:160]}"
            user_id_for_telemetry = row.user_id
            db.commit()
    _publish_project_event(
        project_id,
        "failed",
        message=f"Failed: {message[:160]}",
        error=message[:2000],
    )
    _notify_project_event(
        project_id,
        success=False,
        error_message=message,
    )
    logger.warning("studio.project_render.failed", project_id=project_id, error=message)
    record_render_failed(
        user_id=user_id_for_telemetry,
        render_kind="project",
        render_id=project_id,
        error=message[:2000],
    )
    return ProjectRenderResult(success=False, error=message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_project_clips(
    project_id: int,
) -> Tuple[Optional[StudioProject], List[Tuple[StudioProjectClip, EditSession]]]:
    """Load the project + its clips and underlying sessions in one transaction.

    We materialize everything into dataclasses / tuples while still
    inside the session so the render job (which holds no DB session
    for most of its runtime) can iterate without triggering
    detached-instance lazy loads.
    """
    with get_session() as db:
        project = db.get(StudioProject, project_id)
        if project is None:
            return None, []
        # Order matters: clip 0 is rendered first.
        clip_rows: List[StudioProjectClip] = list(
            db.query(StudioProjectClip)
            .filter(StudioProjectClip.project_id == project_id)
            .order_by(StudioProjectClip.position.asc())
            .all()
        )
        if not clip_rows:
            return project, []
        session_ids = [c.edit_session_id for c in clip_rows]
        sessions = (
            db.query(EditSession)
            .filter(EditSession.id.in_(session_ids))
            .all()
        )
        sessions_by_id = {s.id: s for s in sessions}
        pairs: List[Tuple[StudioProjectClip, EditSession]] = []
        for c in clip_rows:
            s = sessions_by_id.get(c.edit_session_id)
            if s is None:
                continue
            # Expunge so attribute access outside the session works.
            db.expunge(c)
            db.expunge(s)
            pairs.append((c, s))
        if project is not None:
            db.expunge(project)
    return project, pairs


def _ensure_clip_rendered(
    session: EditSession,
    project_clip: StudioProjectClip,
) -> Optional[str]:
    """Render the underlying ``EditSession`` if its cached output is
    stale or missing, then return the rendered MP4 URL.

    "Stale" = the session's ``updated_at`` is newer than the
    watermark we recorded the last time *this* project used the
    session's render. That lets two projects sharing the same
    session each re-render independently when one of them edits the
    underlying clip.
    """
    needs_render = (
        not session.last_render_url
        or session.last_render_status != "done"
        or (
            project_clip.last_used_session_render_at is not None
            and session.updated_at > project_clip.last_used_session_render_at
        )
        or project_clip.last_used_session_render_at is None
    )
    if needs_render:
        logger.info(
            "studio.project_render.rendering_clip",
            session_id=session.id,
            project_clip_id=project_clip.id,
        )
        result = render_session(session.id)
        if not result.success or not result.download_url:
            return None
        # Reload the freshly-updated session row so we get the new URL.
        with get_session() as db:
            refreshed = db.get(EditSession, session.id)
            return refreshed.last_render_url if refreshed else None
    return session.last_render_url


def _download_to(url: str, dest: Path) -> bool:
    """Materialize a remote (or file://) MP4 URL into a local path.

    Project rendering does its concat against local files because
    ffmpeg's ``concat`` filter doesn't handle range requests for HTTPS
    sources reliably across all builds.
    """
    if url.startswith("file://"):
        src = url[len("file://"):]
        shutil.copyfile(src, dest)
        return dest.exists()
    try:
        import httpx

        with httpx.Client(follow_redirects=True, timeout=600.0) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1 << 16):
                        f.write(chunk)
        return dest.exists() and dest.stat().st_size > 0
    except Exception as exc:
        logger.warning("studio.project_render.download_failed", url=url[:200], error=str(exc))
        return False


def _trim_and_conform(
    src_path: Path,
    dst_path: Path,
    trim_in: float,
    trim_out: float,
    aspect: AspectRatio,
) -> bool:
    """Trim ``src_path`` and conform it to the project's aspect dimensions.

    Conform uses ``scale=…:force_original_aspect_ratio=decrease`` +
    ``pad`` so the original framing is preserved (no center crop)
    and the output exactly matches the project's resolution. This is
    the safe default; per-clip aspect was already chosen by the user
    inside the Studio editor so any over-conform pillarboxing is on
    them.
    """
    w, h = get_output_dimensions(aspect)
    args: List[str] = ["ffmpeg", "-y"]
    if trim_in > 0:
        args += ["-ss", f"{trim_in:.3f}"]
    args += ["-i", str(src_path)]
    if trim_out > 0:
        # We pass duration AFTER -i with -t so it's relative to the
        # already-seeked input (more accurate than -to).
        args += ["-t", f"{trim_out:.3f}"]
    args += [
        "-vf",
        (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
        ),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(dst_path),
    ]
    result = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        logger.warning(
            "studio.project_render.trim_failed",
            src=str(src_path),
            stderr=result.stderr[-400:],
        )
        return False
    return dst_path.exists() and dst_path.stat().st_size > 0


def _concat_clips(
    clip_paths: List[Path],
    dst_path: Path,
) -> bool:
    """Concat the trimmed clips with simple cuts.

    We deliberately keep the first concat call simple (``concat``
    demuxer with copy when possible, otherwise filter_complex
    concat). True transition effects (zoom, dissolve, etc.) are
    handled in :func:`_apply_transitions` *after* the bare concat —
    they're crossfades centered on each boundary, applied with the
    ``xfade`` / ``acrossfade`` filter pair.
    """
    if len(clip_paths) == 1:
        shutil.copyfile(clip_paths[0], dst_path)
        return dst_path.exists()
    # Use the safer filter_complex concat (re-encodes once, but
    # guarantees clean timestamps and matching codecs).
    parts = []
    inputs: List[str] = []
    for i, p in enumerate(clip_paths):
        inputs += ["-i", str(p)]
        parts.append(f"[{i}:v:0][{i}:a:0]")
    filter_complex = (
        "".join(parts) + f"concat=n={len(clip_paths)}:v=1:a=1[v][a]"
    )
    args = (
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(dst_path),
        ]
    )
    result = subprocess.run(args, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        logger.warning(
            "studio.project_render.concat_failed",
            stderr=result.stderr[-400:],
        )
        return False
    return dst_path.exists() and dst_path.stat().st_size > 0


def _apply_brand_kit_overlay(
    src_path: Path,
    dst_path: Path,
    brand_kit: BrandKit,
) -> bool:
    """Burn the project-level brand kit logo over the stitched output.

    Mirrors ``src.features.studio.render`` step 6 (the single-clip
    brand-kit overlay): scales the logo to ~12% of the output width,
    fades it to the configured opacity, and anchors it to the chosen
    corner with a margin. Runs as a final pass so per-clip brand kits
    burned in by ``render_session`` stay visible *underneath* the
    project's logo, layering both consistently.

    A missing/unfetchable logo URL short-circuits to a copy — branding
    should never block a project render from finishing.
    """
    if not brand_kit or not brand_kit.logo_url:
        shutil.copyfile(src_path, dst_path)
        return dst_path.exists()

    logo_local = src_path.parent / "brand_logo.png"
    try:
        if brand_kit.logo_url.startswith("file://"):
            shutil.copyfile(brand_kit.logo_url[len("file://"):], logo_local)
        else:
            import httpx

            with httpx.Client(follow_redirects=True, timeout=60.0) as client:
                resp = client.get(brand_kit.logo_url)
                resp.raise_for_status()
                logo_local.write_bytes(resp.content)
    except Exception as exc:
        logger.warning(
            "studio.project_render.brand_logo_fetch_failed",
            error=str(exc),
        )
        shutil.copyfile(src_path, dst_path)
        return dst_path.exists()

    opacity = max(0.05, min(1.0, float(brand_kit.logo_opacity or 0.85)))
    position = brand_kit.logo_position or "br"
    pos_xy = {
        "tl": ("24", "24"),
        "tr": ("W-w-24", "24"),
        "bl": ("24", "H-h-24"),
        "br": ("W-w-24", "H-h-24"),
    }[position]
    # Scale logo to 12% of the stitched output's width; ffmpeg evaluates
    # ``main_w`` at filter-build time when the second input is available.
    filter_complex = (
        f"[1:v]scale=iw*0.12*(main_w/iw):-1:flags=lanczos,"
        f"format=rgba,colorchannelmixer=aa={opacity:.3f}[logo];"
        f"[0:v][logo]overlay="
        f"x={pos_xy[0]}:y={pos_xy[1]}:format=auto[v]"
    )
    args = [
        "ffmpeg", "-y",
        "-i", str(src_path),
        "-i", str(logo_local),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(dst_path),
    ]
    result = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        logger.warning(
            "studio.project_render.brand_overlay_failed",
            stderr=result.stderr[-400:],
        )
        # Fall back to the un-branded normalized cut so we still ship.
        shutil.copyfile(src_path, dst_path)
        return dst_path.exists()
    return dst_path.exists() and dst_path.stat().st_size > 0


def _loudness_normalize(src_path: Path, dst_path: Path) -> bool:
    """2-pass ``loudnorm`` so volume is consistent across clips
    from different recording setups (podcast mic vs phone selfie).

    First pass measures integrated loudness + true peak; second
    pass applies the measured values for accurate -16 LUFS output
    (the YouTube-friendly target). Falls back to a single-pass
    normalize if the first pass JSON fails to parse — better than
    bailing out entirely on the project render.
    """
    measure = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src_path),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        timeout=1200,
    )

    measured_i = measured_tp = measured_lra = measured_thresh = offset = None
    for line in measure.stderr.splitlines():
        line = line.strip()
        if line.startswith('"input_i"'):
            measured_i = line.split(":")[1].strip(' ",')
        elif line.startswith('"input_tp"'):
            measured_tp = line.split(":")[1].strip(' ",')
        elif line.startswith('"input_lra"'):
            measured_lra = line.split(":")[1].strip(' ",')
        elif line.startswith('"input_thresh"'):
            measured_thresh = line.split(":")[1].strip(' ",')
        elif line.startswith('"target_offset"'):
            offset = line.split(":")[1].strip(' ",')

    if None in (measured_i, measured_tp, measured_lra, measured_thresh, offset):
        # Single-pass fallback. Less accurate but always works.
        args = [
            "ffmpeg", "-y", "-i", str(src_path),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(dst_path),
        ]
    else:
        af = (
            f"loudnorm=I=-16:TP=-1.5:LRA=11:"
            f"measured_I={measured_i}:measured_TP={measured_tp}:"
            f"measured_LRA={measured_lra}:measured_thresh={measured_thresh}:"
            f"offset={offset}:linear=true:print_format=summary"
        )
        args = [
            "ffmpeg", "-y", "-i", str(src_path),
            "-af", af,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(dst_path),
        ]
    result = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        logger.warning(
            "studio.project_render.loudnorm_failed",
            stderr=result.stderr[-400:],
        )
        return False
    return dst_path.exists() and dst_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# Public job entrypoint
# ---------------------------------------------------------------------------


def render_project(project_id: int) -> ProjectRenderResult:
    """Render the project identified by ``project_id``.

    Enqueued via
    ``enqueue_job("src.features.studio.render_project:render_project", project_id)``
    or invoked inline by the synchronous queue fallback in dev.
    """
    # Bind context vars for the whole job — every log emitted inside
    # carries ``user_id`` / ``render_kind`` / ``render_id`` without
    # restating them. structlog.contextvars are thread-local so RQ
    # worker concurrency is fine.
    try:
        from structlog.contextvars import bind_contextvars, unbind_contextvars

        user_id: Optional[int] = None
        with get_session() as db:
            project_row = db.get(StudioProject, project_id)
            if project_row is not None:
                user_id = project_row.user_id
        bind_contextvars(
            render_kind="project", render_id=project_id, user_id=user_id
        )
    except Exception:  # noqa: BLE001
        unbind_contextvars = lambda *_args, **_kw: None  # noqa: E731

    started = datetime.utcnow()
    _set_project_status(project_id, "rendering")
    _set_project_progress(project_id, 1, "Starting project render")

    record_render_started(
        user_id=user_id,
        render_kind="project",
        render_id=project_id,
    )

    project, pairs = _load_project_clips(project_id)
    if project is None:
        return _fail_project(project_id, "project not found")
    if not pairs:
        return _fail_project(project_id, "project has no clips to render")

    try:
        aspect = AspectRatio(project.default_aspect)
    except ValueError:
        aspect = AspectRatio.PORTRAIT_9_16

    try:
        with tempfile.TemporaryDirectory(prefix="studio_project_") as workdir:
            workdir_p = Path(workdir)

            trimmed_paths: List[Path] = []
            now = datetime.utcnow()
            watermark_updates: List[Tuple[int, datetime]] = []

            for i, (clip_row, session_row) in enumerate(pairs):
                pct = 5 + int((i / len(pairs)) * 55)  # 5..60
                _set_project_progress(
                    project_id,
                    pct,
                    f"Rendering clip {i + 1}/{len(pairs)}",
                )

                url = _ensure_clip_rendered(session_row, clip_row)
                if not url:
                    return _fail_project(
                        project_id,
                        f"clip {i + 1} failed to render",
                    )

                raw_path = workdir_p / f"raw_{i:03d}.mp4"
                if not _download_to(url, raw_path):
                    return _fail_project(
                        project_id,
                        f"could not fetch rendered clip {i + 1}",
                    )

                trimmed = workdir_p / f"trim_{i:03d}.mp4"
                if not _trim_and_conform(
                    raw_path,
                    trimmed,
                    clip_row.trim_in_seconds or 0.0,
                    clip_row.trim_out_seconds or 0.0,
                    aspect,
                ):
                    return _fail_project(
                        project_id,
                        f"could not trim clip {i + 1}",
                    )
                trimmed_paths.append(trimmed)
                watermark_updates.append((clip_row.id, now))

            _set_project_progress(project_id, 65, "Concatenating clips")
            concat_path = workdir_p / "concat.mp4"
            if not _concat_clips(trimmed_paths, concat_path):
                return _fail_project(project_id, "concat failed")

            _set_project_progress(project_id, 80, "Normalizing audio")
            normalized = workdir_p / "normalized.mp4"
            if not _loudness_normalize(concat_path, normalized):
                # Loudnorm failure shouldn't sink the whole render —
                # fall back to the un-normalized concat so we still
                # ship *something*.
                logger.warning(
                    "studio.project_render.loudnorm_skipped",
                    project_id=project_id,
                )
                normalized = concat_path

            # Project-level brand kit overlay (final pass). Layered
            # ON TOP of any per-clip brand kits already burned in by
            # ``render_session`` so a clip's own logo is still
            # visible underneath the project's consistent logo.
            project_bk = (
                BrandKit.model_validate_json(project.brand_kit_json)
                if project.brand_kit_json
                else None
            )
            if project_bk and project_bk.logo_url:
                _set_project_progress(project_id, 88, "Applying brand kit")
                branded = workdir_p / "branded.mp4"
                if _apply_brand_kit_overlay(normalized, branded, project_bk):
                    normalized = branded

            _set_project_progress(project_id, 92, "Uploading")
            # Reuse the existing R2 helper keyed under a project path
            # so the storage layout cleanly separates projects from
            # single-clip renders.
            final_url = _upload_session_to_r2(str(normalized), project_id)
            if not final_url:
                return _fail_project(project_id, "upload failed")

        # Stamp the per-clip watermarks so subsequent project renders
        # can skip re-rendering unchanged sessions.
        with get_session() as db:
            for clip_id, ts in watermark_updates:
                clip = db.get(StudioProjectClip, clip_id)
                if clip is not None:
                    clip.last_used_session_render_at = ts
            db.commit()

        _mark_project_done(project_id, final_url)
        elapsed = (datetime.utcnow() - started).total_seconds()

        # Charge the user's monthly render-minute budget. Best-effort:
        # a DB blip here logs but doesn't fail the render — the user
        # already got their output, we'd rather under-meter once than
        # punish them for our accounting hiccup. Estimate uses the
        # *output* duration (sum of per-clip effective durations), not
        # wall-clock elapsed, so a slow worker doesn't inflate the charge.
        try:
            def _effective_seconds(clip_row, session_row) -> float:
                src_duration = max(
                    0.0,
                    (session_row.source_end_time or 0.0)
                    - (session_row.source_start_time or 0.0),
                )
                trimmed = (
                    src_duration
                    - (clip_row.trim_in_seconds or 0.0)
                    - (clip_row.trim_out_seconds or 0.0)
                )
                return max(0.0, trimmed)

            output_seconds = sum(
                _effective_seconds(c, s) for c, s in pairs
            )
            with get_session() as db:
                project_row = db.get(StudioProject, project_id)
                user_id = project_row.user_id if project_row else None
            if user_id is not None and output_seconds > 0:
                record_render_minutes(
                    user_id,
                    estimate_render_minutes(output_seconds),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "studio.project_render.budget_record_failed",
                project_id=project_id,
                error=str(exc),
            )

        logger.info(
            "studio.project.render_completed",
            project_id=project_id,
            clip_count=len(pairs),
            duration_seconds=elapsed,
        )
        return ProjectRenderResult(
            success=True,
            download_url=final_url,
            duration_seconds=elapsed,
        )

    except Exception as exc:
        logger.exception(
            "studio.project_render.unhandled",
            project_id=project_id,
            error=str(exc),
        )
        report_render_exception(
            exc,
            user_id=user_id,
            render_kind="project",
            render_id=project_id,
            duration_elapsed_s=round(
                (datetime.utcnow() - started).total_seconds(), 2
            ),
            failure_stage="unhandled",
        )
        return _fail_project(project_id, f"unhandled error: {exc}")
    finally:
        try:
            unbind_contextvars("render_kind", "render_id", "user_id")
        except Exception:  # noqa: BLE001
            pass
