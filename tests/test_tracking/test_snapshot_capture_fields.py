"""Phase 8.5: the collector persists the capture-now metadata fields.

These fields (description, tags, live flag, audio language) come free in the
videos.list call — the regression this guards against is fetching them and
silently discarding them again.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base, TrackedVideo, VideoSnapshot
from src.tracking.video_tracker import VideoTracker
from src.youtube.client import VideoInfo


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


class _StubClient:
    """Returns one fixed VideoInfo; satisfies the tracker's client surface."""

    def __init__(self, info: VideoInfo):
        self._info = info

    def get_video_details(self, video_ids):
        return [self._info]

    def get_quota_status(self):
        return {"total_remaining": 99999}


def _info(video_id: str) -> VideoInfo:
    return VideoInfo(
        video_id=video_id,
        channel_id="UCchan",
        title="A title",
        description="First 1000 chars of description\n00:00 intro\n01:00 part two",
        thumbnail_url="https://i.ytimg.com/vi/x/maxres.jpg",
        tags=["ai", "youtube", "ml"],
        duration_seconds=300,
        published_at=datetime.utcnow() - timedelta(hours=1.5),
        youtube_category_id="28",
        view_count=1234,
        like_count=56,
        comment_count=7,
        live_broadcast_content="none",
        default_audio_language="en",
    )


def test_collect_snapshots_persists_capture_now_fields(db):
    vid = "vid00000001"
    db.add(
        TrackedVideo(
            video_id=vid,
            channel_id="UCchan",
            title="A title",
            published_at=datetime.utcnow() - timedelta(hours=1.5),  # in the 1h window
        )
    )
    db.commit()

    tracker = VideoTracker(db, youtube_client=_StubClient(_info(vid)))
    result = tracker.collect_snapshots()
    assert result.snapshots_collected == 1

    snap = db.query(VideoSnapshot).filter_by(video_id=vid).one()
    assert snap.checkpoint == "1h"
    # 7.1 fields still flow.
    assert snap.title == "A title"
    assert snap.tag_count == 3
    assert snap.is_short is False
    # 8.5 fields now persisted instead of discarded.
    assert "00:00 intro" in snap.description
    assert json.loads(snap.tags) == ["ai", "youtube", "ml"]
    assert snap.live_broadcast_content == "none"
    assert snap.default_audio_language == "en"


def test_videoinfo_defaults_keep_old_constructors_working():
    # Older code/tests build VideoInfo without the 8.5 kwargs.
    info = VideoInfo(
        video_id="v", channel_id="c", title="t", description=None,
        thumbnail_url=None, tags=[], duration_seconds=10,
        published_at=datetime.utcnow(), youtube_category_id=None,
        view_count=0, like_count=0, comment_count=0,
    )
    assert info.live_broadcast_content is None
    assert info.default_audio_language is None
