"""Test the breakout Teardown endpoint composes its sections."""
from unittest.mock import patch


def test_teardown_composes_sections(client, auth_headers):
    with patch("src.features.breakout_explainer.explain_breakout", return_value={
        "evidence": {"title": "Messi vs Ronaldo: The Final"}, "why": "3x its channel norm",
        "your_angle": "make your version", "caveat": "timing + luck",
    }), patch("src.api.routers.breakouts._teardown_comments",
              return_value=[{"text": "incredible match!", "like_count": 9}]), \
         patch("src.features.comment_intelligence.analyze_comments", return_value={
             "summary": "overwhelmingly positive", "top_questions": ["who won?"],
             "next_video_ideas": ["a rematch breakdown"],
         }):
        r = client.get("/breakouts/vid12345678/teardown", headers=auth_headers)

    assert r.status_code == 200, r.text
    b = r.json()
    assert b["explanation"]["why"] == "3x its channel norm"
    assert b["format"]["key"] == "x-vs-y"  # matched "... vs ..." title
    assert b["comments"]["summary"] == "overwhelmingly positive"
    assert b["retention"] is None  # no heatmap captured for this video


def test_teardown_degrades_when_no_comments(client, auth_headers):
    with patch("src.features.breakout_explainer.explain_breakout", return_value={
        "evidence": {"title": "How to fix anything"}, "why": "ahead of channel",
    }), patch("src.api.routers.breakouts._teardown_comments", return_value=[]):
        r = client.get("/breakouts/vidnone00000/teardown", headers=auth_headers)
    assert r.status_code == 200
    b = r.json()
    assert b["comments"] is None and b["format"]["key"] == "how-to"  # still composes the rest


def test_teardown_requires_auth(client):
    assert client.get("/breakouts/x/teardown").status_code in (401, 403)
