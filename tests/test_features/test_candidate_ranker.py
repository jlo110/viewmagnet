"""Tests for the candidate ranker (TODO #9) — scorers mocked, logic real."""
from __future__ import annotations

from unittest.mock import patch

import src.features.candidate_ranker as cr

_RUBRICS = {
    "Strong title under 50": {"overall_score": 80, "under_50_chars": True,
                              "biggest_weakness": "minor", "principles": {}},
    "weak title": {"overall_score": 35, "under_50_chars": True,
                   "biggest_weakness": "no stakes", "principles": {}},
    "Mid title": {"overall_score": 60, "under_50_chars": True,
                  "biggest_weakness": "vague", "principles": {}},
}


def _fake_rubric(title, **kwargs):
    return dict(_RUBRICS[title])


def test_rubric_only_ranking_without_thumbnails():
    cands = [{"title": "weak title"}, {"title": "Strong title under 50"}]
    with patch("src.features.packaging_rubric.score_title", side_effect=_fake_rubric):
        out = cr.rank_candidates(cands)
    assert out["ranking_basis"] == "rubric_only"
    assert out["candidates"][0]["title"] == "Strong title under 50"
    assert out["candidates"][0]["rank"] == 1
    assert out["winner_index"] == 1  # original position of the winner
    assert out["candidates"][0]["reach_score"] is None


def test_blended_ranking_when_all_have_thumbnails(monkeypatch):
    # reach disagrees with rubric: weak title has the better thumbnail
    reach = {"Strong title under 50": 0.2, "weak title": 0.9}
    monkeypatch.setattr(cr, "reach_score", lambda img, t: reach[t])
    monkeypatch.setattr(cr, "reach_model_label", lambda: "finetuned_clip_head_auc_0.668")
    cands = [
        {"title": "Strong title under 50", "image_bytes": b"img1"},
        {"title": "weak title", "image_bytes": b"img2"},
    ]
    with patch("src.features.packaging_rubric.score_title", side_effect=_fake_rubric):
        out = cr.rank_candidates(cands)
    assert out["ranking_basis"] == "rubric+reach_prior"
    # Rubric-LED blend (reach demoted to a weak prior):
    #   strong = .7*.8 + .3*.2 = .62 ; weak = .7*.35 + .3*.9 = .515 -> strong wins
    # (reframe: the rubric drives the pick, not the better thumbnail's reach score)
    assert out["candidates"][0]["title"] == "Strong title under 50"
    assert out["candidates"][0]["rank_score"] == 0.62
    assert out["reach_model"] == "finetuned_clip_head_auc_0.668"
    assert "not a performance prediction" in out["disclaimer"].lower()


def test_partial_thumbnails_fall_back_to_rubric(monkeypatch):
    monkeypatch.setattr(cr, "reach_score", lambda img, t: 0.99)
    cands = [
        {"title": "Mid title", "image_bytes": b"img"},
        {"title": "Strong title under 50"},  # no thumbnail
    ]
    with patch("src.features.packaging_rubric.score_title", side_effect=_fake_rubric):
        out = cr.rank_candidates(cands)
    # one candidate lacks reach -> rubric ordering, but reach still reported
    assert out["ranking_basis"] == "rubric_only"
    assert out["candidates"][0]["title"] == "Strong title under 50"
    mid = [c for c in out["candidates"] if c["title"] == "Mid title"][0]
    assert mid["reach_score"] == 0.99 and mid["has_thumbnail"]


def test_reach_score_degrades_without_artifact(monkeypatch):
    import src.features.reach_model as rm
    monkeypatch.setattr(rm, "available", lambda: False)
    monkeypatch.setattr(cr, "_load_reach", lambda: None)
    assert cr.reach_score(b"img", "title") is None
