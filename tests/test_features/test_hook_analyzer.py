"""Tests for the hook analyzer (Phase 8.6) — pure metrics + mocked LLM rubric."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from src.features.hook_analyzer import analyze_hook, frame_metrics

_FAKE = {
    "instant_clarity": {"score": 8, "note": "clear premise"},
    "curiosity_or_stakes": {"score": 6, "note": "stakes arrive late"},
    "visual_energy": {"score": 7, "note": "good motion"},
    "payoff_promise": {"score": 5, "note": "no promise"},
    "biggest_fix": "state the stakes in the first sentence",
    "stronger_openings": ["Opening A", "Opening B", "Opening C", "Opening D"],
}


def _patched(return_value=_FAKE):
    client = MagicMock()
    client.generate_json.return_value = return_value
    return patch("src.features.llm_client.get_llm_client", return_value=client), client


# ---------------------------------------------------------------------------
# frame_metrics (pure)
# ---------------------------------------------------------------------------


def test_frame_metrics_static_frames_have_no_motion():
    frame = np.full((90, 160), 128, dtype=np.uint8)
    m = frame_metrics([frame.copy() for _ in range(6)])
    assert m["motion_score"] == 0.0
    assert m["cut_count"] == 0
    assert abs(m["brightness"] - 128 / 255) < 0.01
    assert m["contrast"] == 0.0


def test_frame_metrics_detects_hard_cuts_and_motion():
    black = np.zeros((90, 160), dtype=np.uint8)
    white = np.full((90, 160), 255, dtype=np.uint8)
    # black -> white -> black = two hard cuts, max motion
    m = frame_metrics([black, white, black])
    assert m["cut_count"] == 2
    assert m["motion_score"] > 0.9


def test_frame_metrics_too_few_frames():
    assert frame_metrics([]) is None
    assert frame_metrics([np.zeros((4, 4), dtype=np.uint8)]) is None


# ---------------------------------------------------------------------------
# analyze_hook (LLM mocked)
# ---------------------------------------------------------------------------


def test_analyze_hook_scores_and_caps_openings():
    p, client = _patched()
    with p:
        out = analyze_hook(
            transcript="In this video I'm going to show you...",
            title="I Tested Every AI Tool",
            user_id=7, plan="pro",
        )
    # overall = mean(8,6,7,5)=6.5 -> 65
    assert out["overall_score"] == 65
    assert out["biggest_fix"] == "state the stakes in the first sentence"
    assert out["stronger_openings"] == ["Opening A", "Opening B", "Opening C"]
    _, kwargs = client.generate_json.call_args
    assert kwargs["feature"] == "hook_analyzer" and kwargs["user_id"] == 7


def test_analyze_hook_injects_visual_metrics_into_prompt():
    p, client = _patched()
    metrics = {"motion_score": 0.01, "cut_count": 0, "brightness": 0.2, "contrast": 0.05}
    with p:
        out = analyze_hook(transcript="hello", visual_metrics=metrics)
    args, _ = client.generate_json.call_args
    user_prompt = args[1]
    assert "static/slideshow-like" in user_prompt  # low motion classified
    assert "0 hard cut(s)" in user_prompt
    assert out["visual_metrics"] == metrics


def test_analyze_hook_nothing_to_analyze():
    assert analyze_hook()["error"] == "nothing_to_analyze"


def test_analyze_hook_llm_unavailable_keeps_metrics():
    p, _ = _patched(return_value={})
    metrics = {"motion_score": 0.1, "cut_count": 2, "brightness": 0.5, "contrast": 0.2}
    with p:
        out = analyze_hook(transcript="hi", visual_metrics=metrics)
    assert out["error"] == "llm_unavailable"
    assert out["overall_score"] is None
    assert out["visual_metrics"] == metrics  # measured signal survives
