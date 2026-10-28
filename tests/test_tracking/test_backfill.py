"""Tests for the training-set backfill (rebuilds the lost dataset)."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base, BackfillVideo, TrackedChannel
from src.tracking import backfill as bf


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()
    engine.dispose()


@dataclass
class _Vid:
    video_id: str
    channel_id: str
    title: str
    view_count: int
    duration_seconds: int = 600
    thumbnail_url: Optional[str] = None
    tags: Optional[list] = None
    published_at: Optional[datetime] = None
    youtube_category_id: Optional[str] = None
    like_count: Optional[int] = 10
    comment_count: Optional[int] = 5
    default_audio_language: Optional[str] = "en"


class _Client:
    """Stub: returns a fixed uploads list + details keyed by the channel."""

    def __init__(self, views_by_channel):
        self._views = views_by_channel

    def get_channel_videos(self, playlist_id, max_results=50):
        ch = "UC" + playlist_id[2:]
        n = len(self._views.get(ch, []))
        return {"items": [{"contentDetails": {"videoId": f"{ch}_v{i}"}} for i in range(n)]}

    def get_video_details(self, video_ids):
        out = []
        for vid in video_ids:
            ch, idx = vid.rsplit("_v", 1)
            views = self._views[ch][int(idx)]
            out.append(_Vid(video_id=vid, channel_id=ch, title=f"Video {idx}", view_count=views,
                            published_at=datetime.utcnow()))
        return out


def _add_active(db, channel_id):
    db.add(TrackedChannel(channel_id=channel_id, recent_video_count=1, is_active=True))


def test_uploads_playlist_id():
    assert bf._uploads_playlist_id("UCabc123") == "UUabc123"
    assert bf._uploads_playlist_id("bad") is None


def test_backfill_labels_outlier_vs_channel_median(db):
    _add_active(db, "UCa")
    # 5 videos; median views = 100. A 1000-view video is a 10x outlier.
    client = _Client({"UCa": [50, 80, 100, 120, 1000]})
    out = bf.backfill_channel_history(db, client, max_channels=10)
    assert out["channels"] == 1 and out["videos"] == 5
    rows = {r.video_id: r for r in db.query(BackfillVideo).all()}
    big = rows["UCa_v4"]
    assert big.channel_median_views == 100.0
    assert big.outlier == 10.0
    assert round(big.log_outlier, 2) == round(__import__("math").log(10), 2)


def test_skips_channels_with_too_few_videos(db):
    _add_active(db, "UCthin")
    client = _Client({"UCthin": [10, 20]})  # < MIN_VIDEOS_FOR_LABEL
    out = bf.backfill_channel_history(db, client, max_channels=10)
    assert out["channels"] == 0 and out["videos"] == 0


def test_idempotent_skips_already_backfilled(db):
    _add_active(db, "UCa")
    client = _Client({"UCa": [50, 80, 100, 120, 1000]})
    bf.backfill_channel_history(db, client, max_channels=10)
    out2 = bf.backfill_channel_history(db, client, max_channels=10)  # nothing new
    assert out2["channels"] == 0
    assert db.query(BackfillVideo).count() == 5  # no duplicates
