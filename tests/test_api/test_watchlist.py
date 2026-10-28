"""Tests for the Competitive Watchlist endpoints."""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _stub_youtube():
    """Stub YouTubeClient so add/resolve needs no network/keys."""
    client = MagicMock()
    client.search_channels.return_value = {
        "items": [{"id": {"channelId": "UCsearchresolved00000000"},
                   "snippet": {"title": "Resolved Channel"}}]
    }
    with patch("src.youtube.client.YouTubeClient", return_value=client):
        yield client


def test_add_resolves_via_search_and_enrolls(client, auth_headers, _stub_youtube):
    from src.database.models import TrackedChannel

    resp = client.post("/watchlist", json={"url": "@somecreator"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["channel_id"] == "UCsearchresolved00000000" and body["added"] is True

    # listed
    lst = client.get("/watchlist", headers=auth_headers).json()["channels"]
    assert any(c["channel_id"] == "UCsearchresolved00000000" for c in lst)

    # enrolled into collection (TrackedChannel) as a watchlist/user source
    from src.database.connection import get_session
    with get_session() as db:
        tc = db.query(TrackedChannel).filter_by(channel_id="UCsearchresolved00000000").first()
        assert tc is not None and tc.is_active and tc.source == "watchlist"


def test_add_direct_channel_url_skips_search(client, auth_headers, _stub_youtube):
    cid = "UCdirecturlchannel000000"
    resp = client.post("/watchlist", json={"url": f"https://youtube.com/channel/{cid}"},
                       headers=auth_headers)
    assert resp.status_code == 200 and resp.json()["channel_id"] == cid
    _stub_youtube.search_channels.assert_not_called()  # resolved by regex, no search


def test_add_is_idempotent(client, auth_headers, _stub_youtube):
    for _ in range(2):
        resp = client.post("/watchlist", json={"url": "@dupe"}, headers=auth_headers)
        assert resp.status_code == 200
    rows = [c for c in client.get("/watchlist", headers=auth_headers).json()["channels"]
            if c["channel_id"] == "UCsearchresolved00000000"]
    assert len(rows) == 1  # unique (user, channel)


def test_unresolvable_returns_400(client, auth_headers):
    empty = MagicMock()
    empty.search_channels.return_value = {"items": []}
    with patch("src.youtube.client.YouTubeClient", return_value=empty):
        resp = client.post("/watchlist", json={"url": "not a channel"}, headers=auth_headers)
    assert resp.status_code == 400


def test_remove(client, auth_headers, _stub_youtube):
    client.post("/watchlist", json={"url": "@toremove"}, headers=auth_headers)
    cid = "UCsearchresolved00000000"
    assert client.delete(f"/watchlist/{cid}", headers=auth_headers).json()["removed"] is True
    assert all(c["channel_id"] != cid
               for c in client.get("/watchlist", headers=auth_headers).json()["channels"])


def test_breakouts_empty_without_watched_channels(client, auth_headers):
    resp = client.get("/watchlist/breakouts", headers=auth_headers)
    assert resp.status_code == 200 and resp.json()["count"] == 0


def test_leaderboard_empty_without_watched_channels(client, auth_headers):
    resp = client.get("/watchlist/leaderboard", headers=auth_headers)
    assert resp.status_code == 200 and resp.json()["channels"] == []


def test_leaderboard_ranks_watched_channels(client, auth_headers, _stub_youtube):
    client.post("/watchlist", json={"url": "@studied"}, headers=auth_headers)
    cid = "UCsearchresolved00000000"
    detected = [
        {"video_id": "v1", "channel_id": cid, "title": "Big hit", "probability": 0.97,
         "views": 100000, "level": "breakout"},
        {"video_id": "v2", "channel_id": cid, "title": "Smaller", "probability": 0.71,
         "views": 20000, "level": "heating_up"},
        {"video_id": "vX", "channel_id": "UCothernotwatched000000", "title": "ignore",
         "probability": 0.9, "views": 5000, "level": "breakout"},
    ]
    with patch("src.features.breakout_detector.detect_live_breakouts", return_value=detected), \
         patch("src.features.durability_grader.grade", return_value={
             "v1": {"label": "likely_to_sustain", "probability": 0.8},
             "v2": {"label": "could_flash", "probability": 0.3},
         }):
        resp = client.get("/watchlist/leaderboard", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    chans = resp.json()["channels"]
    assert len(chans) == 1  # the non-watched channel is filtered out
    row = chans[0]
    assert row["channel_id"] == cid and row["breakout_count"] == 2
    assert row["avg_durability"] == pytest.approx(0.55, abs=0.01)  # (0.8 + 0.3) / 2
    assert row["top_video"]["video_id"] == "v1"  # highest probability


def test_requires_auth(client):
    assert client.get("/watchlist").status_code in (401, 403)
