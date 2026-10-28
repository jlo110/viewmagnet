"""Tests for the watchlist email-alert job (dedup + send contract)."""
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base, User, WatchlistAlertSent, WatchlistChannel
from src.features import watchlist_alerts as wa


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()
    engine.dispose()


def _seed(db):
    db.add(User(id=1, email="u@example.com", name="Watcher", password_hash="x"))
    db.add(WatchlistChannel(user_id=1, channel_id="UCwatched0000000000000000"))
    db.commit()


_ITEM = {"video_id": "vid1234abcd", "channel_id": "UCwatched0000000000000000",
         "title": "Big breakout", "probability": 0.9, "watch_url": "https://y/vid1234abcd"}


def test_sends_then_dedups(db):
    _seed(db)
    send = MagicMock(return_value=True)
    with patch("src.features.breakout_detector.detect_live_breakouts", return_value=[dict(_ITEM)]), \
         patch("src.features.durability_grader.grade", return_value={"vid1234abcd": {"label": "likely_to_sustain"}}), \
         patch("src.features.notifications.send_email", send):
        out1 = wa.send_watchlist_alerts(db)
        out2 = wa.send_watchlist_alerts(db)  # same breakout → already sent

    assert out1["emails_sent"] == 1
    assert send.call_count == 1  # second run deduped, no re-send
    assert out2["emails_sent"] == 0
    assert db.query(WatchlistAlertSent).filter_by(user_id=1, video_id="vid1234abcd").count() == 1


def test_respects_email_optout(db):
    db.add(User(id=1, email="u@example.com", name="Watcher", password_hash="x",
                watchlist_email_alerts=False))
    db.add(WatchlistChannel(user_id=1, channel_id="UCwatched0000000000000000"))
    db.commit()
    send = MagicMock(return_value=True)
    with patch("src.features.breakout_detector.detect_live_breakouts", return_value=[dict(_ITEM)]), \
         patch("src.features.durability_grader.grade", return_value={}), \
         patch("src.features.notifications.send_email", send):
        out = wa.send_watchlist_alerts(db)
    assert send.call_count == 0 and out["emails_sent"] == 0


def test_no_watchers_noop(db):
    with patch("src.features.breakout_detector.detect_live_breakouts", return_value=[dict(_ITEM)]):
        assert wa.send_watchlist_alerts(db)["users_alerted"] == 0


def test_only_alerts_watched_channels(db):
    _seed(db)
    other = {**_ITEM, "video_id": "other999999", "channel_id": "UCnotwatched00000000000000"}
    send = MagicMock(return_value=True)
    with patch("src.features.breakout_detector.detect_live_breakouts", return_value=[other]), \
         patch("src.features.durability_grader.grade", return_value={}), \
         patch("src.features.notifications.send_email", send):
        out = wa.send_watchlist_alerts(db)
    assert out.get("emails_sent", 0) == 0 and send.call_count == 0


def test_webhook_fires_alongside_email(db):
    db.add(User(id=1, email="u@example.com", name="Watcher", password_hash="x",
                alert_webhook_url="https://hooks.slack.com/services/T/B/x"))
    db.add(WatchlistChannel(user_id=1, channel_id="UCwatched0000000000000000"))
    db.commit()
    hook = MagicMock(return_value=True)
    with patch("src.features.breakout_detector.detect_live_breakouts", return_value=[dict(_ITEM)]), \
         patch("src.features.durability_grader.grade", return_value={}), \
         patch("src.features.notifications.send_email", MagicMock(return_value=True)), \
         patch("src.features.notifications.send_webhook", hook):
        out = wa.send_watchlist_alerts(db)
    assert out["emails_sent"] == 1 and out["webhooks_sent"] == 1
    assert hook.call_count == 1 and "Big breakout" in hook.call_args.args[1]


def test_webhook_only_when_email_opted_out(db):
    db.add(User(id=1, email="u@example.com", name="Watcher", password_hash="x",
                watchlist_email_alerts=False,
                alert_webhook_url="https://discord.com/api/webhooks/1/x"))
    db.add(WatchlistChannel(user_id=1, channel_id="UCwatched0000000000000000"))
    db.commit()
    send = MagicMock(return_value=True)
    hook = MagicMock(return_value=True)
    with patch("src.features.breakout_detector.detect_live_breakouts", return_value=[dict(_ITEM)]), \
         patch("src.features.durability_grader.grade", return_value={}), \
         patch("src.features.notifications.send_email", send), \
         patch("src.features.notifications.send_webhook", hook):
        out = wa.send_watchlist_alerts(db)
    assert send.call_count == 0 and hook.call_count == 1
    assert out["emails_sent"] == 0 and out["webhooks_sent"] == 1
