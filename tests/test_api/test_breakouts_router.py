"""Tests for the Breakout Radar router helpers (plan 9.1) — no live DB."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.api.routers.breakouts import _annotate_niche, best_cat_matches
from src.database.models import Base, VideoSnapshot


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()
    yield s
    s.close()
    engine.dispose()


_CHECKPOINTS = ["1h", "6h", "24h", "3d", "7d"]


def _snap(db, vid, cat, n=1):
    # (video_id, checkpoint) is unique -> one row per checkpoint; a video's
    # category is the mode across its checkpoints.
    for i in range(n):
        db.add(VideoSnapshot(video_id=vid, checkpoint=_CHECKPOINTS[i], hours_since_publish=6,
                             view_count=1000, youtube_category_id=cat))
    db.commit()


def test_annotate_niche_attaches_category_confidence_and_links(db):
    _snap(db, "vidNews0001", "25", n=3)   # News -> high confidence (AUC 0.958)
    _snap(db, "vidGame0001", "20", n=2)   # Gaming -> lower (AUC 0.843)
    items = [{"video_id": "vidNews0001"}, {"video_id": "vidGame0001"}, {"video_id": "vidUnknown0"}]
    out = _annotate_niche(db, items)
    by = {it["video_id"]: it for it in out}
    assert by["vidNews0001"]["niche"] == "News" and by["vidNews0001"]["confidence"] == "high"
    assert by["vidGame0001"]["niche"] == "Gaming" and by["vidGame0001"]["confidence"] == "lower"
    # unknown video -> no category row -> "Other" + global-fallback confidence
    assert by["vidUnknown0"]["niche"] == "Other"
    # links constructed from the video id
    assert by["vidNews0001"]["thumbnail_url"].endswith("vidNews0001/hqdefault.jpg")
    assert "watch?v=vidNews0001" in by["vidNews0001"]["watch_url"]


def test_annotate_niche_uses_modal_category(db):
    # News at 1h+6h, Gaming at 24h -> modal is News.
    db.add(VideoSnapshot(video_id="vidMixed001", checkpoint="1h", hours_since_publish=1, view_count=10, youtube_category_id="25"))
    db.add(VideoSnapshot(video_id="vidMixed001", checkpoint="6h", hours_since_publish=6, view_count=20, youtube_category_id="25"))
    db.add(VideoSnapshot(video_id="vidMixed001", checkpoint="24h", hours_since_publish=24, view_count=30, youtube_category_id="20"))
    db.commit()
    out = _annotate_niche(db, [{"video_id": "vidMixed001"}])
    assert out[0]["niche"] == "News"


def test_annotate_niche_empty():
    assert _annotate_niche(None, []) == []


def test_best_cat_matches():
    assert best_cat_matches({"niche": "Gaming"}, "20")
    assert not best_cat_matches({"niche": "News"}, "20")
