"""Tests for :mod:`src.features.studio.project_spec`.

These cover the *spec math* only — duration computation, transition
overlap, and trim accounting. The full render-pipeline tests (which
require ffmpeg) live separately. Spec math is the part the frontend
mirrors in TypeScript (see ``computeTotalSeconds`` in
``StudioProject.tsx``), so keeping it pinned by tests prevents the
two implementations from drifting.
"""
from __future__ import annotations

import pytest

from src.features.studio.project_spec import (
    PROJECT_SPEC_VERSION,
    ProjectClipSpec,
    ProjectSpec,
)
from src.features.studio.spec import AspectRatio, TransitionType


def _clip(
    *,
    id: int,
    position: int,
    duration: float,
    trim_in: float = 0.0,
    trim_out: float = 0.0,
    transition_type: TransitionType | None = None,
    transition_ms: int | None = None,
) -> ProjectClipSpec:
    """Tiny constructor for ProjectClipSpec test fixtures."""
    return ProjectClipSpec(
        id=id,
        edit_session_id=id * 10,
        position=position,
        clip_key=f"key_{id}",
        title=f"clip {id}",
        source_url="https://example.com/v.mp4",
        source_start_time=0.0,
        source_end_time=duration,
        session_render_url=f"https://r2.example.com/{id}.mp4",
        session_render_status="done",
        trim_in_seconds=trim_in or None,
        trim_out_seconds=trim_out or None,
        transition_in_type=transition_type,
        transition_in_ms=transition_ms,
    )


def _project(clips: list[ProjectClipSpec], **kwargs) -> ProjectSpec:
    return ProjectSpec(
        version=PROJECT_SPEC_VERSION,
        id=1,
        user_id=1,
        title="Test project",
        default_aspect=AspectRatio.PORTRAIT_9_16,
        default_transition_type=kwargs.get(
            "default_transition_type", TransitionType.CUT
        ),
        default_transition_ms=kwargs.get("default_transition_ms", 300),
        clips=clips,
    )


class TestEffectiveDuration:
    def test_no_trim_returns_source_duration(self):
        clip = _clip(id=1, position=0, duration=10.0)
        assert clip.effective_duration_seconds == 10.0

    def test_trim_in_subtracts_from_duration(self):
        clip = _clip(id=1, position=0, duration=10.0, trim_in=2.5)
        assert clip.effective_duration_seconds == 7.5

    def test_trim_out_subtracts_from_duration(self):
        clip = _clip(id=1, position=0, duration=10.0, trim_out=1.0)
        assert clip.effective_duration_seconds == 9.0

    def test_combined_trim(self):
        clip = _clip(id=1, position=0, duration=10.0, trim_in=2.0, trim_out=1.0)
        assert clip.effective_duration_seconds == 7.0

    def test_over_trim_floors_at_zero(self):
        """If the user trims more than the clip duration we clamp at 0
        rather than emitting a negative duration into the render math."""
        clip = _clip(id=1, position=0, duration=5.0, trim_in=10.0)
        assert clip.effective_duration_seconds == 0.0


class TestTotalDuration:
    def test_empty_project_is_zero(self):
        project = _project([])
        assert project.total_duration_seconds == 0.0

    def test_single_clip_equals_its_duration(self):
        project = _project([_clip(id=1, position=0, duration=10.0)])
        assert project.total_duration_seconds == 10.0

    def test_cut_transitions_do_not_subtract(self):
        """A cut has 0 overlap — concatenated duration equals the sum."""
        project = _project(
            [
                _clip(id=1, position=0, duration=10.0),
                _clip(id=2, position=1, duration=8.0),
                _clip(id=3, position=2, duration=6.0),
            ],
            default_transition_type=TransitionType.CUT,
            default_transition_ms=500,
        )
        assert project.total_duration_seconds == 24.0

    def test_default_fade_subtracts_overlap_per_boundary(self):
        """With ``fade`` defaulting to 500ms, three clips produce two
        boundaries → 2 × 0.5s = 1.0s of overlap removed from the sum."""
        project = _project(
            [
                _clip(id=1, position=0, duration=10.0),
                _clip(id=2, position=1, duration=8.0),
                _clip(id=3, position=2, duration=6.0),
            ],
            default_transition_type=TransitionType.FADE,
            default_transition_ms=500,
        )
        # 10 + (8 - 0.5) + (6 - 0.5) = 23.0
        assert project.total_duration_seconds == pytest.approx(23.0)

    def test_per_clip_transition_overrides_project_default(self):
        """A clip with its own ``transition_in_*`` ignores the project
        default — useful for "fade everywhere except this one cut"."""
        project = _project(
            [
                _clip(id=1, position=0, duration=10.0),
                _clip(
                    id=2,
                    position=1,
                    duration=8.0,
                    transition_type=TransitionType.CUT,
                    transition_ms=0,
                ),
                _clip(id=3, position=2, duration=6.0),
            ],
            default_transition_type=TransitionType.FADE,
            default_transition_ms=400,
        )
        # 10 + (8 - 0) + (6 - 0.4) = 23.6
        assert project.total_duration_seconds == pytest.approx(23.6)

    def test_trim_and_transition_combine(self):
        """Trim shortens each clip's effective duration BEFORE the
        transition overlap is subtracted (matches render-pipeline
        order: trim first, then concat)."""
        project = _project(
            [
                _clip(id=1, position=0, duration=10.0, trim_in=1.0),
                _clip(id=2, position=1, duration=8.0, trim_out=2.0),
            ],
            default_transition_type=TransitionType.DISSOLVE,
            default_transition_ms=500,
        )
        # effective: 9.0, 6.0 — overlap 0.5 → 9 + 5.5 = 14.5
        assert project.total_duration_seconds == pytest.approx(14.5)

    def test_first_clip_has_no_incoming_transition(self):
        """The first clip's ``transition_in_*`` is ignored — even if
        set — because there's no predecessor to fade from."""
        project = _project(
            [
                _clip(
                    id=1,
                    position=0,
                    duration=10.0,
                    transition_type=TransitionType.FADE,
                    transition_ms=1000,
                ),
                _clip(id=2, position=1, duration=8.0),
            ],
            default_transition_type=TransitionType.CUT,
            default_transition_ms=0,
        )
        # The fade on clip[0] doesn't apply (no predecessor) and the
        # default for clip[1] is a hard cut → 10 + 8 = 18.
        assert project.total_duration_seconds == 18.0
