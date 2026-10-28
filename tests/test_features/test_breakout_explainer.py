"""Tests for the breakout explainer (plan 8.7) — evidence + mocked LLM."""
from unittest.mock import MagicMock, patch

from src.features import breakout_explainer as be

_EV = {
    "title": "I Survived 100 Days In The Wild",
    "niche": "Entertainment", "views": 800000, "outpaces_channel_x": 6.2,
    "breakout": {"probability": 0.92, "level": "breakout", "checkpoint": "6h"},
    "topic": {"label": "survival challenge", "uploads": 28, "channels": 15},
    "top_comments": ["this is insane", "how did he do that"],
}
_FAKE_LLM = {
    "why": "It's at 6.2x its channel norm and riding a crowded survival wave.",
    "packaging_takeaway": "Specific day-count + extreme stakes in the title.",
    "your_angle": "Do a 24-hour version in YOUR niche with a clear failure stake.",
}


def test_explain_builds_grounded_prompt_and_parses(monkeypatch):
    monkeypatch.setattr(be, "gather_evidence", lambda s, v: dict(_EV))
    client = MagicMock()
    client.generate_json.return_value = _FAKE_LLM
    with patch("src.features.llm_client.get_llm_client", return_value=client):
        out = be.explain_breakout(None, "vid123", user_idea="cooking", user_id=4, plan="pro")
    assert out["why"].startswith("It's at 6.2x")
    assert out["your_angle"]
    assert out["evidence"]["outpaces_channel_x"] == 6.2
    # the prompt must carry the SPECIFIC measured evidence (grounding) + crowded flag
    args, kwargs = client.generate_json.call_args
    prompt = args[1]
    assert "6.2x" in prompt and "CROWDED" in prompt and "survival challenge" in prompt
    assert "cooking" in prompt  # the creator's context
    assert kwargs["feature"] == "breakout_explainer" and kwargs["user_id"] == 4


def test_explain_missing_video(monkeypatch):
    monkeypatch.setattr(be, "gather_evidence", lambda s, v: None)
    out = be.explain_breakout(None, "nope")
    assert out["error"] == "video_not_found_or_no_snapshots"


def test_explain_llm_unavailable_returns_evidence(monkeypatch):
    monkeypatch.setattr(be, "gather_evidence", lambda s, v: dict(_EV))
    client = MagicMock()
    client.generate_json.return_value = {}
    with patch("src.features.llm_client.get_llm_client", return_value=client):
        out = be.explain_breakout(None, "vid123")
    assert out["error"] == "llm_unavailable" and out["evidence"]["title"]


def test_open_ground_topic_phrasing(monkeypatch):
    ev = dict(_EV); ev["topic"] = {"label": "niche thing", "uploads": 4, "channels": 3}
    monkeypatch.setattr(be, "gather_evidence", lambda s, v: ev)
    client = MagicMock(); client.generate_json.return_value = _FAKE_LLM
    with patch("src.features.llm_client.get_llm_client", return_value=client):
        be.explain_breakout(None, "vid123")
    prompt = client.generate_json.call_args[0][1]
    assert "open ground" in prompt and "CROWDED" not in prompt
