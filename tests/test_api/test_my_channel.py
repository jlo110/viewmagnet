"""Connect Your Own Channel (3.1): own-channel breakouts + sequel rec."""
from unittest.mock import patch


def test_not_connected_returns_connected_false(client, auth_headers):
    r = client.get("/my-channel/breakouts", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False and body["count"] == 0


def test_breakouts_attach_recommendation(client, auth_headers):
    item = {"video_id": "vmine123456", "channel_id": "UCmine0000000000000000000",
            "title": "My hit", "probability": 0.95, "views": 50000, "level": "breakout"}
    with patch("src.api.routers.my_channel._connected_channels",
               return_value={"UCmine0000000000000000000": "My Channel"}), \
         patch("src.features.breakout_detector.detect_live_breakouts", return_value=[item]), \
         patch("src.features.durability_grader.grade", return_value={
             "vmine123456": {"label": "likely_to_sustain", "probability": 0.82}}):
        r = client.get("/my-channel/breakouts", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is True and body["count"] == 1
    b = body["breakouts"][0]
    assert b["durability"]["label"] == "likely_to_sustain"
    assert "sequel" in b["recommendation"]["action"].lower()
    assert b["channel_name"] == "My Channel"


def test_enroll_requires_a_connection(client, auth_headers):
    with patch("src.api.routers.my_channel._connected_channels", return_value={}):
        r = client.post("/my-channel/enroll", headers=auth_headers)
    assert r.status_code == 400


def test_analytics_returns_stored_rows(client, auth_headers):
    with patch("src.api.routers.my_channel._connected_channels",
               return_value={"UCmine0000000000000000000": "My Channel"}), \
         patch("src.features.owner_analytics.get_stored_analytics", return_value={
             "channel_avg_ctr": 0.06, "fetched_at": None,
             "videos": [{"video_id": "v1", "title": "T", "views": 10, "impressions": 100,
                         "ctr": 0.08, "avg_view_percentage": 40.0,
                         "avg_view_duration_seconds": 90.0, "retention_curve": None,
                         "watch_url": "http://y/v1"}]}):
        r = client.get("/my-channel/analytics", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is True and body["channel_avg_ctr"] == 0.06
    assert body["videos"][0]["ctr"] == 0.08


def test_analytics_refresh_needs_connection(client, auth_headers):
    with patch("src.api.routers.my_channel._connected_channels", return_value={}):
        r = client.post("/my-channel/analytics/refresh", headers=auth_headers)
    assert r.status_code == 400


def test_requires_auth(client):
    assert client.get("/my-channel/breakouts").status_code in (401, 403)
