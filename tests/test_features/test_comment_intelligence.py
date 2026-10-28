"""Tests for Phase 7.4 Comment Intelligence (feature layer, LLM mocked)."""
from unittest.mock import MagicMock, patch

from src.features.comment_intelligence import analyze_comments


def test_empty_comments_returns_error():
    out = analyze_comments([])
    assert out == {"error": "no_comments", "comment_count": 0}


def test_analyze_calls_llm_and_returns_insights():
    comments = [
        {"text": "How did you make the intro?", "like_count": 120},
        {"text": "Please do a part 2!", "like_count": 80},
        {"text": "boring", "like_count": 1},
    ]
    fake = {
        "summary": "Mostly positive; viewers want a sequel.",
        "sentiment": {"positive": 70, "neutral": 20, "negative": 10},
        "top_questions": ["How was the intro made?"],
        "next_video_ideas": ["Part 2"],
        "faq": [{"question": "Intro?", "suggested_pinned_answer": "Made in After Effects."}],
        "praise_themes": [],
        "criticism_themes": ["pacing"],
    }
    client = MagicMock()
    client.generate_json.return_value = fake
    with patch("src.features.comment_intelligence.get_llm_client", return_value=client):
        out = analyze_comments(comments, user_id=7, plan="pro")

    # LLM was called with the feature tag + budget attribution.
    _, kwargs = client.generate_json.call_args
    assert kwargs["feature"] == "comment_intelligence"
    assert kwargs["user_id"] == 7 and kwargs["plan"] == "pro"
    # Most-liked comment is included in the prompt, capped/sorted.
    prompt = client.generate_json.call_args[0][1]
    assert "How did you make the intro?" in prompt
    # Result passes through + comment_count is attached.
    assert out["next_video_ideas"] == ["Part 2"]
    assert out["comment_count"] == 3


def test_handles_objects_not_just_dicts():
    class C:
        def __init__(self, text, like_count):
            self.text = text
            self.like_count = like_count

    client = MagicMock()
    client.generate_json.return_value = {"summary": "ok"}
    with patch("src.features.comment_intelligence.get_llm_client", return_value=client):
        out = analyze_comments([C("great vid", 5), C("", 0)])
    assert out["comment_count"] == 1  # empty-text comment skipped


def test_llm_unavailable_degrades_gracefully():
    client = MagicMock()
    client.generate_json.return_value = {}  # parse failure / no provider
    with patch("src.features.comment_intelligence.get_llm_client", return_value=client):
        out = analyze_comments([{"text": "hi", "like_count": 1}])
    assert out["error"] == "llm_unavailable"
    assert out["comment_count"] == 1
