"""Pydantic spec for a Studio multi-clip Project (Week 7).

A :class:`ProjectSpec` is the JSON shape exposed by the project API and
consumed by the project render job. It mirrors the
``StudioProject`` / ``StudioProjectClip`` database rows but adds two
things the DB doesn't carry directly:

* Resolved per-clip metadata (title, duration, status) pulled from the
  underlying ``EditSession`` so the frontend can render the clip rail
  without making N+1 follow-up requests.
* Computed ``total_duration_seconds`` (sum of per-clip durations minus
  transition overlaps) so the UI doesn't have to duplicate the math.

The rule of thumb: anything that's *only* present in the spec belongs
here. Anything that's persisted lives in :mod:`src.database.models`
and is denormalized into the spec on read.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from src.features.studio.spec import (
    AspectRatio,
    BrandKit,
    TransitionType,
)

PROJECT_SPEC_VERSION = 1


class ProjectClipSpec(BaseModel):
    """One ordered clip inside a project.

    All fields are present-tense: this is what the project currently
    looks like, not a diff. The frontend can drag-reorder, edit trims,
    or change transitions by PATCH-ing the corresponding row; the
    server is the source of truth.
    """

    id: int = Field(..., description="StudioProjectClip row id")
    edit_session_id: int = Field(..., description="Underlying EditSession id")
    position: int = Field(..., ge=0, description="0-indexed ordering")

    # --- denormalized from the EditSession for the clip rail UI -----
    clip_key: str = Field(..., description="EditSession.clip_key (opaque)")
    title: Optional[str] = Field(default=None, description="EditSession.title")
    source_url: str
    source_start_time: float = Field(..., ge=0.0)
    source_end_time: float = Field(..., ge=0.0)
    session_render_url: Optional[str] = Field(
        default=None,
        description="EditSession.last_render_url — the per-clip MP4 the "
        "project render job stitches. None means the clip hasn't been "
        "individually rendered yet (project render will trigger one).",
    )
    session_render_status: Literal[
        "idle", "queued", "rendering", "done", "failed"
    ] = Field(default="idle")

    # --- project-level overrides ------------------------------------
    trim_in_seconds: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Additional trim from the start of the per-clip render. "
        "None means use the full clip.",
    )
    trim_out_seconds: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Additional trim from the end (clip-local seconds). "
        "None means use the full clip.",
    )
    transition_in_type: Optional[TransitionType] = Field(
        default=None,
        description="Transition INTO this clip from the previous one. "
        "None inherits the project's default_transition_type. Ignored "
        "for the clip at position 0.",
    )
    transition_in_ms: Optional[int] = Field(
        default=None,
        ge=0,
        le=2000,
        description="Transition duration. None inherits the project default.",
    )

    @property
    def effective_duration_seconds(self) -> float:
        """Duration of this clip *after* applying ``trim_in`` /
        ``trim_out``. Used by the timeline UI and the duration sum.

        Note: this is duration of the underlying clip's render output
        as the project will use it — i.e. ``end - start`` minus any
        project-level trim. The underlying ``EditSession`` may
        further restrict this via its own ``source_start_time`` /
        ``source_end_time``, but those are already baked into the
        per-clip MP4 that gets stitched.
        """
        clip_dur = max(0.0, self.source_end_time - self.source_start_time)
        tin = self.trim_in_seconds or 0.0
        tout = self.trim_out_seconds or 0.0
        return max(0.0, clip_dur - tin - tout)


class ProjectSpec(BaseModel):
    """Top-level project spec returned by the API.

    Combines the project's own row with its ordered clip list and any
    computed/denormalized fields the UI wants in one round trip.
    """

    version: int = Field(default=PROJECT_SPEC_VERSION)
    id: int
    user_id: int
    title: str
    description: Optional[str] = Field(
        default=None,
        description="Long-form project description. Used by the Distribution "
        "Hub handoff (Week 9 Connected Tools) as the seed publish "
        "caption / post body when the creator clicks Publish from a "
        "rendered project. Optional — older projects predate the "
        "column and fall back to the title.",
    )
    default_aspect: AspectRatio = AspectRatio.PORTRAIT_9_16
    default_transition_type: TransitionType = TransitionType.CUT
    default_transition_ms: int = Field(default=300, ge=0, le=2000)
    brand_kit: BrandKit = Field(default_factory=BrandKit)

    last_render_status: Literal[
        "idle", "queued", "rendering", "done", "failed"
    ] = Field(default="idle")
    last_render_url: Optional[str] = None
    last_render_error: Optional[str] = None
    render_progress: Optional[int] = Field(default=None, ge=0, le=100)
    render_progress_message: Optional[str] = None

    clips: List[ProjectClipSpec] = Field(default_factory=list)

    @property
    def clip_count(self) -> int:
        return len(self.clips)

    @property
    def total_duration_seconds(self) -> float:
        """Sum of per-clip effective durations minus the transition
        overlaps between them.

        First clip has no incoming transition. Each subsequent clip's
        transition overlap is its ``transition_in_ms`` (falling back
        to the project default) converted to seconds. A transition of
        ``0`` ms or a hard ``cut`` doesn't shorten the output.
        """
        if not self.clips:
            return 0.0
        total = self.clips[0].effective_duration_seconds
        for clip in self.clips[1:]:
            t_type = clip.transition_in_type or self.default_transition_type
            t_ms = clip.transition_in_ms
            if t_ms is None:
                t_ms = self.default_transition_ms
            overlap_s = (t_ms or 0) / 1000.0 if t_type != TransitionType.CUT else 0.0
            total += clip.effective_duration_seconds - overlap_s
        return max(0.0, total)
