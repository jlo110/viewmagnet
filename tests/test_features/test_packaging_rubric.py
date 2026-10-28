"""Tests for the MrBeast packaging rubric (LLM mocked)."""
from unittest.mock import MagicMock, patch

import pytest

from src.features.packaging_rubric import score_title


@pytest.fixture(autouse=True)
def _cold_rubric_cache():
    """Isolate scoring-logic tests from the (Redis-backed) title cache so the LLM
    is always invoked. Caching itself is covered separately."""
    with patch("src.cache.analyze.get_packaging_rubric_cached", return_value=None), \
         patch("src.cache.analyze.set_packaging_rubric_cached"):
        yield

_FAKE = {
    "curiosity_gap": {"score": 8, "note": "strong hook"},
    "extremity": {"score": 6, "note": "could be more extreme"},
    "clarity": {"score": 9, "note": "clear"},
    "specificity": {"score": 7, "note": "has a number"},
    "biggest_weakness": "not extreme enough",
    "stronger_titles": ["A", "B", "C", "D"],
}


def _patched(return_value=_FAKE):
    client = MagicMock()
    client.generate_json.return_value = return_value
    return patch("src.features.packaging_rubric.get_llm_client", return_value=client), client


def test_empty_title():
    assert score_title("  ") == {"error": "empty_title"}


def test_scores_and_computes_overall():
    p, client = _patched()
    with p:
        out = score_title("I survived 50 hours underwater", user_id=3, plan="pro")
    # deterministic length check
    assert out["char_count"] == len("I survived 50 hours underwater")
    assert out["under_50_chars"] is True and out["truncation_risk"] is False
    # overall = mean(8,6,9,7)=7.5 -> 75, no truncation penalty
    assert out["overall_score"] == 75
    assert out["biggest_weakness"] == "not extreme enough"
    assert out["stronger_titles"] == ["A", "B", "C"]  # capped at 3
    # budget attribution propagated
    _, kwargs = client.generate_json.call_args
    assert kwargs["feature"] == "packaging_rubric" and kwargs["user_id"] == 3


def test_truncation_penalty_for_long_titles():
    long_title = "I spent one hundred hours building the world's largest sandcastle ever"
    assert len(long_title) > 50
    p, _ = _patched()
    with p:
        out = score_title(long_title)
    assert out["under_50_chars"] is False and out["truncation_risk"] is True
    # 75 base - 15 truncation penalty = 60
    assert out["overall_score"] == 60


def test_llm_unavailable_keeps_deterministic_part():
    p, _ = _patched(return_value={})
    with p:
        out = score_title("short title")
    assert out["error"] == "llm_unavailable"
    assert out["overall_score"] is None
    assert out["char_count"] == len("short title")  # deterministic part still there
