"""Tests for the Week 6 EditSpec normalize() migrator + back-compat.

Sessions saved before Week 6 should still load cleanly and gain the new
features (stable ids, boundary_transitions list, layout, background_loop)
without manual intervention. This suite codifies the back-compat
contract so we don't accidentally break old user data.
"""
from __future__ import annotations

import json

import pytest

from src.features.studio.spec import (
    EditSpec,
    TransitionInstance,
    TransitionType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CLIP = {
    "key": "abc",
    "source_url": "https://example.com/a.mp4",
    "start_time": 0.0,
    "end_time": 10.0,
    "duration_seconds": 10.0,
    "video_width": 1920,
    "video_height": 1080,
    "fps": 30.0,
}


# ---------------------------------------------------------------------------
# Old-spec back-compat
# ---------------------------------------------------------------------------


class TestOldSpecBackCompat:
    def test_minimal_old_spec_loads(self):
        """A pre-Week-6 spec missing layout / background_loop / boundary_transitions
        must still parse — defaults fill in via Pydantic ``Field``."""
        old = {"clip": _BASE_CLIP}
        spec = EditSpec.model_validate(old)
        assert spec.layout.mode == "single"
        assert spec.background_loop is None
        assert spec.boundary_transitions == []

    def test_old_broll_gets_stable_id(self):
        """Week-5 broll clips were saved without ``id`` — the default_factory
        should populate them on load so per-boundary lookups work."""
        old = {
            "clip": _BASE_CLIP,
            "broll": {
                "clips": [
                    {"start": 1.0, "end": 3.0, "clip_url": "https://x/1.mp4"}
                ]
            },
        }
        spec = EditSpec.model_validate(old)
        assert len(spec.broll.clips) == 1
        assert spec.broll.clips[0].id, "BRollClip id should auto-populate"

    def test_old_camera_cut_gets_stable_id(self):
        old = {
            "clip": _BASE_CLIP,
            "camera": {
                "tracks": [
                    {"start": 0.0, "end": 4.0, "subject_id": 0},
                    {"start": 4.0, "end": 8.0, "subject_id": 1},
                ]
            },
        }
        spec = EditSpec.model_validate(old)
        ids = [c.id for c in spec.camera.tracks]
        assert all(ids), "Every CameraCut must have a stable id"
        assert len(set(ids)) == len(ids), "IDs must be unique"

    def test_old_transitions_block_still_loads(self):
        """Pre-Week-6 spec with the global ``transitions`` block but no
        ``boundary_transitions`` list should validate cleanly."""
        old = {
            "clip": _BASE_CLIP,
            "transitions": {
                "enabled": True,
                "type": "fade",
                "duration_ms": 300,
            },
        }
        spec = EditSpec.model_validate(old)
        assert spec.transitions.enabled is True
        assert spec.transitions.type == TransitionType.FADE
        assert spec.boundary_transitions == []


# ---------------------------------------------------------------------------
# normalize() expansion
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_no_op_when_disabled(self):
        spec = EditSpec.model_validate(
            {
                "clip": _BASE_CLIP,
                "transitions": {"enabled": False, "type": "fade"},
            }
        )
        out = spec.normalize()
        assert out.boundary_transitions == []

    def test_expands_global_to_per_broll_edges(self):
        """When the global transition is enabled, normalize() should
        synthesize a TransitionInstance per B-roll IN and OUT edge."""
        spec = EditSpec.model_validate(
            {
                "clip": _BASE_CLIP,
                "broll": {
                    "clips": [
                        {"start": 1.0, "end": 3.0, "clip_url": "https://x/1.mp4"},
                        {"start": 5.0, "end": 7.0, "clip_url": "https://x/2.mp4"},
                    ]
                },
                "transitions": {
                    "enabled": True,
                    "type": "fade",
                    "duration_ms": 250,
                    "sfx_enabled": True,
                },
            }
        )
        out = spec.normalize()
        # 2 clips × 2 edges = 4 instances
        assert len(out.boundary_transitions) == 4
        clip_ids = {c.id for c in out.broll.clips}
        for inst in out.boundary_transitions:
            assert inst.type == TransitionType.FADE
            assert inst.duration_ms == 250
            assert inst.sfx_enabled is True
            # boundary_id matches the broll_<id>_in/_out scheme
            assert any(cid in inst.boundary_id for cid in clip_ids)

    def test_expands_global_to_camera_cuts(self):
        spec = EditSpec.model_validate(
            {
                "clip": _BASE_CLIP,
                "camera": {
                    "tracks": [
                        {"start": 0.0, "end": 3.0, "subject_id": 0},
                        {"start": 3.0, "end": 7.0, "subject_id": 1},
                    ]
                },
                "transitions": {"enabled": True, "type": "swipe"},
            }
        )
        out = spec.normalize()
        assert len(out.boundary_transitions) == 2  # one per camera cut
        for inst in out.boundary_transitions:
            assert inst.type == TransitionType.SWIPE
            assert "camera_cut_" in inst.boundary_id

    def test_user_overrides_preserved(self):
        """An existing boundary_transitions list is left ALONE — normalize()
        only expands when the list is empty."""
        spec = EditSpec.model_validate(
            {
                "clip": _BASE_CLIP,
                "broll": {
                    "clips": [
                        {
                            "start": 1.0,
                            "end": 3.0,
                            "clip_url": "https://x/1.mp4",
                            "id": "fixedid",
                        }
                    ]
                },
                "boundary_transitions": [
                    {
                        "boundary_id": "broll_fixedid_in",
                        "type": "zoom_in",
                        "duration_ms": 400,
                    }
                ],
                "transitions": {
                    "enabled": True,
                    "type": "fade",
                    "duration_ms": 250,
                },
            }
        )
        out = spec.normalize()
        assert len(out.boundary_transitions) == 1
        assert out.boundary_transitions[0].type == TransitionType.ZOOM_IN

    def test_normalize_is_deep_copy(self):
        """Mutating the returned spec should NOT mutate the original."""
        spec = EditSpec.model_validate(
            {
                "clip": _BASE_CLIP,
                "broll": {
                    "clips": [
                        {"start": 1.0, "end": 3.0, "clip_url": "https://x/1.mp4"}
                    ]
                },
                "transitions": {"enabled": True, "type": "fade"},
            }
        )
        out = spec.normalize()
        out.boundary_transitions.clear()
        # Re-normalize the original should still produce instances.
        out2 = spec.normalize()
        assert len(out2.boundary_transitions) == 2


# ---------------------------------------------------------------------------
# Round trip — model_dump_json + model_validate stay consistent
# ---------------------------------------------------------------------------


def test_full_spec_round_trip():
    spec = EditSpec.model_validate(
        {
            "clip": _BASE_CLIP,
            "broll": {
                "clips": [
                    {"start": 1.0, "end": 3.0, "clip_url": "https://x/1.mp4"}
                ]
            },
            "transitions": {"enabled": True, "type": "fade", "duration_ms": 250},
            "layout": {"mode": "split_horizontal", "main_weight": 0.65},
            "background_loop": {
                "source": "pexels",
                "clip_url": "https://x/bg.mp4",
                "volume": 0.0,
            },
        }
    )
    blob = spec.model_dump_json()
    reparsed = EditSpec.model_validate(json.loads(blob))
    assert reparsed.layout.mode == "split_horizontal"
    assert reparsed.background_loop is not None
    assert reparsed.broll.clips[0].id == spec.broll.clips[0].id


def test_transition_instance_validation():
    """Required fields + bounded ranges are enforced by Pydantic."""
    with pytest.raises(Exception):
        TransitionInstance(boundary_id="x")  # too short for min_length
    inst = TransitionInstance(boundary_id="broll_abc123_in", type=TransitionType.FADE)
    assert inst.duration_ms == 300
