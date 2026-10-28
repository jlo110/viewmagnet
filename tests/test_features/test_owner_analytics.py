"""Owner analytics pull (3.2 display half): upsert + reader + per-video fail-open."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import (
    Base,
    OwnerVideoAnalytics,
    TrackedVideo,
    YouTubeConnection,
)
from src.features import owner_analytics as oa


@pytest.fixture(autouse=True)
def _fernet():
    """Pin a valid Fernet so YouTubeConnection's encrypted token columns round-trip
    (the test env's ENCRYPTION_KEY isn't a valid Fernet key)."""
    from cryptography.fernet import Fernet
    f = Fernet(Fernet.generate_key())
    with patch("src.security.crypto._fernet", return_value=f):
        yield


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()
    engine.dispose()


def _va(video_id, ctr, title="V"):
    return SimpleNamespace(video_id=video_id, title=title, views=1000, impressions=20000,
                           ctr=ctr, avg_view_percentage=45.0, avg_view_duration_seconds=120.0)


def _seed_conn(db, channel_id="UCmine0000000000000000000"):
    db.add(YouTubeConnection(
        user_id=1, channel_id=channel_id, channel_name="Mine",
        access_token="t", refresh_token="r", token_uri="u",
        client_id="cid", client_secret="cs", scopes="[]"))
    db.add(TrackedVideo(video_id="vid1aaaaaaa", channel_id=channel_id, title="One",
                        published_at=datetime.utcnow() - timedelta(days=2)))
    db.add(TrackedVideo(video_id="vid2bbbbbbb", channel_id=channel_id, title="Two",
                        published_at=datetime.utcnow() - timedelta(days=5)))
    db.commit()


def test_pull_upserts_one_row_per_video(db):
    _seed_conn(db)
    client = MagicMock()
    client.get_video_analytics.side_effect = lambda v: _va(v, 0.08 if v == "vid1aaaaaaa" else 0.04)
    client.get_retention_curve.return_value = [1.0, 0.8, 0.5]
    with patch("src.integrations.youtube_analytics.YouTubeAnalyticsClient", return_value=client):
        out = oa.pull_owner_analytics(db, user_id=1)
    assert out == {"connections": 1, "videos": 2}
    rows = db.query(OwnerVideoAnalytics).filter_by(user_id=1).all()
    assert {r.video_id for r in rows} == {"vid1aaaaaaa", "vid2bbbbbbb"}
    assert any(r.retention_curve for r in rows)  # curve persisted as JSON


def test_pull_is_idempotent_upsert(db):
    _seed_conn(db)
    client = MagicMock()
    client.get_video_analytics.side_effect = lambda v: _va(v, 0.05)
    client.get_retention_curve.return_value = None
    with patch("src.integrations.youtube_analytics.YouTubeAnalyticsClient", return_value=client):
        oa.pull_owner_analytics(db, user_id=1)
        oa.pull_owner_analytics(db, user_id=1)
    assert db.query(OwnerVideoAnalytics).filter_by(user_id=1).count() == 2  # not duplicated


def test_one_bad_video_does_not_abort_batch(db):
    _seed_conn(db)
    client = MagicMock()

    def maybe_fail(v):
        if v == "vid1aaaaaaa":
            raise RuntimeError("analytics 403")
        return _va(v, 0.05)

    client.get_video_analytics.side_effect = maybe_fail
    client.get_retention_curve.return_value = None
    with patch("src.integrations.youtube_analytics.YouTubeAnalyticsClient", return_value=client):
        out = oa.pull_owner_analytics(db, user_id=1)
    assert out["videos"] == 1  # the good one still landed
    assert db.query(OwnerVideoAnalytics).filter_by(user_id=1).count() == 1


def test_reader_computes_channel_ctr_baseline(db):
    _seed_conn(db)
    db.add(OwnerVideoAnalytics(user_id=1, channel_id="UCx", video_id="a",
                               impressions=100, ctr=0.10, fetched_at=datetime.utcnow()))
    db.add(OwnerVideoAnalytics(user_id=1, channel_id="UCx", video_id="b",
                               impressions=100, ctr=0.20, fetched_at=datetime.utcnow()))
    db.commit()
    data = oa.get_stored_analytics(db, user_id=1)
    assert data["channel_avg_ctr"] == pytest.approx(0.15)
    assert len(data["videos"]) == 2
