"""Worker-queue surge detection (Week 8 P3 polish).

When the render queue backs up — bursty user activity, a worker
restart catching up on backlog, a slow ffmpeg stage hogging the
runners — we want the frontend to *tell* the user instead of letting
them stare at a queued progress bar wondering whether we're alive.

The surge level is computed from current queue depth plus a rough
estimated wait. Levels:

  * ``normal``   — queue is empty or trivially short. UI shows
    nothing extra.
  * ``busy``     — queue is non-trivial but the user's render is
    likely to start within a few minutes. UI shows a small inline
    "queue is busier than usual" note next to the queue button.
  * ``slammed``  — queue is deep enough that the user should expect
    multi-minute waits before the worker even picks up their job.
    UI shows a full banner with the estimated wait so the user can
    decide whether to leave the page or keep waiting.

The thresholds are tuned to the current single-worker dev config
(one job at a time, ~3 min per project on average). They're soft
heuristics — being wrong by one bucket is fine; the goal is to
preempt the support ticket, not to be predictive ML.

This module is pure (no Redis call inside the threshold logic) so
it stays trivially testable. The caller probes
:func:`src.queue.client.get_queue_depth` and passes the snapshot in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

SurgeLevel = Literal["normal", "busy", "slammed"]


# Average wall-clock time a single render takes once the worker
# picks it up. Used to convert "N jobs ahead" into "Y seconds of
# expected wait". Conservative — the per-render p50 we see in
# practice is ~90s but a long project can push past 5 minutes, so
# using the higher number means the surge banner under-promises
# rather than over-promises.
AVG_RENDER_SECONDS = 180

# Bucket thresholds. Picked so a single-worker dev environment shows
# "busy" the moment a second job is queued (you'd really know if you
# clicked Render twice) and "slammed" when there are enough jobs
# ahead that the estimated wait crosses ~5 minutes.
_BUSY_QUEUE_DEPTH = 2
_SLAMMED_QUEUE_DEPTH = 5

_BUSY_WAIT_SECONDS = 60
_SLAMMED_WAIT_SECONDS = 300


@dataclass(frozen=True)
class SurgeSnapshot:
    """Caller-facing summary of how busy the worker queue is.

    ``estimated_wait_seconds`` is the *added* wait this user can
    expect on top of their own render time — i.e. the time until
    the worker starts on their job. It's deliberately rounded to
    10s buckets so a few percent jitter in the snapshot doesn't
    cause the UI banner to flicker between "3 min" and "3 min 4s".
    """

    level: SurgeLevel
    queue_depth: int
    started: int
    estimated_wait_seconds: int
    available: bool  # False when Redis isn't configured

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "queue_depth": self.queue_depth,
            "started": self.started,
            "estimated_wait_seconds": self.estimated_wait_seconds,
            "available": self.available,
        }


def classify_depth(
    snapshot: Optional[dict[str, int]],
    *,
    avg_render_seconds: int = AVG_RENDER_SECONDS,
) -> SurgeSnapshot:
    """Bucket a raw queue-depth snapshot into a surge level.

    ``snapshot`` is the dict returned by
    :func:`src.queue.client.get_queue_depth`, or ``None`` when Redis
    isn't configured. ``None`` returns a ``normal`` / unavailable
    snapshot so callers can safely pipe it through without a
    surrounding ``if``.

    The level uses MAX(depth-bucket, wait-bucket) so either trigger
    on its own can escalate the banner — a queue of 1 with a 10-min
    long-running render still earns "slammed".
    """
    if not snapshot:
        return SurgeSnapshot(
            level="normal",
            queue_depth=0,
            started=0,
            estimated_wait_seconds=0,
            available=False,
        )

    queued = int(snapshot.get("queued") or 0)
    started = int(snapshot.get("started") or 0)
    # "Wait for me to start" ≈ (jobs ahead + jobs in flight) * avg
    # render time. We include ``started`` because a single-worker
    # setup means even a job currently rendering blocks ours.
    raw_wait = (queued + started) * avg_render_seconds
    estimated_wait = int(round(raw_wait / 10) * 10)

    depth_level: SurgeLevel = "normal"
    if queued >= _SLAMMED_QUEUE_DEPTH:
        depth_level = "slammed"
    elif queued >= _BUSY_QUEUE_DEPTH:
        depth_level = "busy"

    wait_level: SurgeLevel = "normal"
    if estimated_wait >= _SLAMMED_WAIT_SECONDS:
        wait_level = "slammed"
    elif estimated_wait >= _BUSY_WAIT_SECONDS:
        wait_level = "busy"

    # Combine — pick the more severe of the two buckets so a small
    # queue with a long-running encode still escalates correctly.
    rank = {"normal": 0, "busy": 1, "slammed": 2}
    level: SurgeLevel = (
        depth_level if rank[depth_level] >= rank[wait_level] else wait_level
    )

    return SurgeSnapshot(
        level=level,
        queue_depth=queued,
        started=started,
        estimated_wait_seconds=estimated_wait,
        available=True,
    )
