"""Weekly niche digest: opt-in gating, ranking by durability, render."""
from types import SimpleNamespace
from unittest.mock import patch

from src.features.niche_digest import _durability_rank, _render


def test_durability_rank_prefers_stuck_then_strongest():
    stuck = {"probability": 0.8, "durability": {"probability": 0.9}}
    flash = {"probability": 0.99, "durability": {"probability": 0.2}}
    ungraded = {"probability": 0.95, "durability": {}}
    ranked = sorted([flash, ungraded, stuck], key=_durability_rank, reverse=True)
    assert ranked[0] is stuck          # highest durability wins over raw probability
    assert ranked[-1] is ungraded      # missing durability sorts last


def test_render_includes_titles_and_durability_notes():
    items = [
        {"title": "A", "probability": 0.97, "durability": {"label": "likely_to_sustain"},
         "channel_title": "Chan", "watch_url": "http://x/a"},
        {"title": "B", "probability": 0.71, "durability": {"label": "could_flash"},
         "watch_url": "http://x/b"},
    ]
    subject, text, html = _render("Sam", items)
    assert "2" in subject
    assert "Sam" in text and "A" in text and "stuck" in text and "flashed" in text
    assert "http://x/a" in text and "Chan" in html


class _Q:
    """Minimal chainable query stub for the digest's session calls."""
    def __init__(self, rows):
        self._rows = rows
    def filter(self, *a, **k):
        return self
    def all(self):
        return self._rows


def test_send_skips_when_no_opted_in_users():
    session = SimpleNamespace(query=lambda *models: _Q([]))  # nobody opted in
    from src.features.niche_digest import send_niche_digests
    out = send_niche_digests(session)
    assert out == {"users_digested": 0, "breakouts": 0}


def test_send_emails_opted_in_user_with_breakout():
    user = SimpleNamespace(id=1, email="a@b.co", name="Sam", weekly_digest=True)

    def query(*models):
        if getattr(models[0], "__name__", "") == "User":
            return _Q([user])
        # WatchlistChannel.user_id, channel_id, channel_title  → one watched channel
        return _Q([(1, "UCchan", "Cool Channel")])

    session = SimpleNamespace(query=query)
    detected = [{"video_id": "v1", "channel_id": "UCchan", "title": "Hit",
                 "probability": 0.95, "watch_url": "http://x/v1"}]
    sent = []
    from src.features.niche_digest import send_niche_digests
    with patch("src.features.breakout_detector.detect_live_breakouts", return_value=detected), \
         patch("src.features.durability_grader.grade",
               return_value={"v1": {"label": "likely_to_sustain", "probability": 0.8}}), \
         patch("src.features.notifications.send_email",
               side_effect=lambda *a, **k: sent.append(a) or True):
        out = send_niche_digests(session)
    assert out["users_digested"] == 1 and out["breakouts"] == 1
    assert sent and sent[0][0] == "a@b.co"
