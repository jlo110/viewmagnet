"""Tests for WebSub push discovery (plan 7.5) — pure helpers + renewal logic."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base, TrackedChannel, WebSubSubscription
from src.tracking import websub as ws

ATOM_BODY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>VIDEO1234ab</yt:videoId>
    <yt:channelId>UCtrackedchannel000000</yt:channelId>
    <title>Brand new upload</title>
    <published>2026-06-12T18:00:00+00:00</published>
  </entry>
</feed>"""


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_topic_roundtrip():
    t = ws.topic_url("UCabc")
    assert ws.channel_id_from_topic(t) == "UCabc"
    assert ws.channel_id_from_topic("https://example.com/nope") is None


def test_parse_notification_extracts_entries():
    out = ws.parse_notification(ATOM_BODY)
    assert len(out) == 1
    e = out[0]
    assert e["video_id"] == "VIDEO1234ab"
    assert e["channel_id"] == "UCtrackedchannel000000"
    assert e["title"] == "Brand new upload"
    assert e["published_at"] == datetime(2026, 6, 12, 18, 0, 0)


def test_parse_notification_garbage_and_deleted():
    assert ws.parse_notification(b"not xml at all") == []
    assert ws.parse_notification(b"<feed xmlns='http://www.w3.org/2005/Atom'/>") == []


def test_verify_signature_modes():
    secret = "s3cret"
    sig = "sha1=" + hmac.new(secret.encode(), ATOM_BODY, hashlib.sha1).hexdigest()
    assert ws.verify_signature(ATOM_BODY, sig, secret)            # valid
    assert not ws.verify_signature(ATOM_BODY, sig, "other")       # wrong secret
    assert not ws.verify_signature(ATOM_BODY, None, secret)       # missing header
    assert not ws.verify_signature(ATOM_BODY, "sha1=dead", secret)  # bad digest
    assert ws.verify_signature(ATOM_BODY, None, None)             # no secret configured


# ---------------------------------------------------------------------------
# Renewal selection
# ---------------------------------------------------------------------------


def test_renewal_targets_new_and_expiring(db, monkeypatch):
    now = datetime.utcnow()
    for ch, name in [("UCnew0000000000000000aa", "new"),
                     ("UCexp0000000000000000bb", "expiring"),
                     ("UCok00000000000000000cc", "healthy")]:
        db.add(TrackedChannel(channel_id=ch, recent_video_count=3, is_active=True))
    db.add(WebSubSubscription(channel_id="UCexp0000000000000000bb", status="verified",
                              lease_expires_at=now + timedelta(hours=12)))  # < RENEW_BEFORE
    db.add(WebSubSubscription(channel_id="UCok00000000000000000cc", status="verified",
                              lease_expires_at=now + timedelta(days=8)))    # healthy
    db.commit()

    calls = []
    monkeypatch.setattr(ws, "subscribe_channel", lambda ch, cb, sec, lease: calls.append(ch) or True)

    class _S:
        websub_callback_url = "https://api.example.com"
        websub_secret = "x"
        websub_lease_seconds = 828000
    import src.config as cfg
    monkeypatch.setattr(ws, "renew_due_subscriptions", ws.renew_due_subscriptions)
    monkeypatch.setattr(cfg, "get_settings", lambda: _S())
    # websub module imports get_settings inside the function from src.config
    out = ws.renew_due_subscriptions(db, batch=10)

    assert sorted(calls) == ["UCexp0000000000000000bb", "UCnew0000000000000000aa"]
    assert out["accepted"] == 2
    new_sub = db.query(WebSubSubscription).filter_by(channel_id="UCnew0000000000000000aa").one()
    # Lease is set by the hub's verification GET, not optimistically here.
    assert new_sub.status == "pending" and new_sub.lease_expires_at is None
    assert new_sub.last_subscribed_at is not None


def test_renewal_retries_stale_pending_but_not_fresh(db, monkeypatch):
    now = datetime.utcnow()
    db.add(TrackedChannel(channel_id="UCstale000000000000000a", recent_video_count=1, is_active=True))
    db.add(TrackedChannel(channel_id="UCfresh000000000000000b", recent_video_count=1, is_active=True))
    db.add(WebSubSubscription(channel_id="UCstale000000000000000a", status="pending",
                              last_subscribed_at=now - timedelta(hours=2)))
    db.add(WebSubSubscription(channel_id="UCfresh000000000000000b", status="pending",
                              last_subscribed_at=now - timedelta(minutes=5)))
    db.commit()

    calls = []
    monkeypatch.setattr(ws, "subscribe_channel", lambda ch, cb, sec, lease: calls.append(ch) or True)

    class _S:
        websub_callback_url = "https://api.example.com"
        websub_secret = "x"
        websub_lease_seconds = 828000
    import src.config as cfg
    monkeypatch.setattr(cfg, "get_settings", lambda: _S())
    ws.renew_due_subscriptions(db, batch=10)
    assert calls == ["UCstale000000000000000a"]  # fresh pending not hammered


def test_renewal_disabled_without_callback(db, monkeypatch):
    class _S:
        websub_callback_url = None
    import src.config as cfg
    monkeypatch.setattr(cfg, "get_settings", lambda: _S())
    assert ws.renew_due_subscriptions(db) == {"disabled": True}
