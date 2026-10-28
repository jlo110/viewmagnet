"""Durability-driven sequel recommendation (3.1)."""
from src.features.sequel_recommender import sequel_recommendation


def test_sustain_says_make_a_sequel():
    r = sequel_recommendation("likely_to_sustain")
    assert "sequel" in r["action"].lower() and r["urgency"] == "high"


def test_flash_says_capture_now_not_sequel():
    r = sequel_recommendation("could_flash")
    assert "spike" in r["action"].lower() and r["urgency"] == "high"


def test_too_early_says_wait():
    r = sequel_recommendation("too_early")
    assert r["urgency"] == "low" and "24h" in r["why"]


def test_unknown_label_is_safe_default():
    r = sequel_recommendation(None)
    assert r["action"] and r["why"] and r["urgency"] == "medium"
