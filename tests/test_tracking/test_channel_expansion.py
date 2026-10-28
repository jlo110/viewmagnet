"""Tests for the shared tracked-set expansion logic (plan 8.11)."""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base, TrackedChannel, TrackedVideo, VideoSnapshot
from src.tracking import channel_expansion as ce


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()
    engine.dispose()


class _StubClient:
    """Returns fixed channels per (region, category); records calls."""

    def __init__(self, by_combo):
        self._by_combo = by_combo
        self.calls = []

    def get_most_popular(self, region_code, video_category_id=None):
        self.calls.append((region_code, video_category_id))
        return [SimpleNamespace(channel_id=ch) for ch in self._by_combo.get((region_code, video_category_id), [])]


def test_fetch_dedupes_across_combos():
    client = _StubClient({
        ("US", None): ["UCa", "UCb"],
        ("US", "20"): ["UCb", "UCc"],  # UCb repeats
    })
    found = ce.fetch_popular_channels(client, ["US"], [None, "20"])
    assert set(found) == {"UCa", "UCb", "UCc"}
    assert len(client.calls) == 2


def test_skips_non_english():
    # English-first gate: only English chart videos enroll their channel.
    class _C:
        def get_most_popular(self, region_code, video_category_id=None):
            return [
                SimpleNamespace(channel_id="UCen", title="How to cook pasta", default_audio_language="en"),
                SimpleNamespace(channel_id="UCpt", title="Como fazer macarrao", default_audio_language="pt"),
                SimpleNamespace(channel_id="UCte", title="వంట ఎలా", default_audio_language=None),
            ]
    found = ce.fetch_popular_channels(_C(), ["US"], [None])
    assert "UCen" in found       # English
    assert "UCpt" not in found   # non-en audio language
    assert "UCte" not in found   # non-Latin title


def test_expand_enrolls_only_new(db):
    db.add(TrackedChannel(channel_id="UCexisting", recent_video_count=1, is_active=True))
    db.commit()
    client = _StubClient({("US", None): ["UCexisting", "UCnew1", "UCnew2"]})
    out = ce.expand_tracked_set(db, client, regions=["US"], categories=[None])
    assert out["enrolled"] == 2 and out["total_active"] == 3
    assert {c.channel_id for c in db.query(TrackedChannel).all()} == {"UCexisting", "UCnew1", "UCnew2"}
    new = db.query(TrackedChannel).filter_by(channel_id="UCnew1").one()
    assert new.is_active and new.source.startswith("chart:")


def test_expand_respects_limit(db):
    client = _StubClient({("US", None): ["UCa", "UCb", "UCc", "UCd"]})
    out = ce.expand_tracked_set(db, client, regions=["US"], categories=[None], limit=2)
    assert out["enrolled"] == 2 and out["total_active"] == 2


def test_source_label_fits_column(db):
    # Long category names must be truncated to String(20).
    client = _StubClient({("US", "24"): ["UCx"]})
    ce.expand_tracked_set(db, client, regions=["US"], categories=["24"])
    row = db.query(TrackedChannel).one()
    assert len(row.source) <= 20
    assert row.enrolled_via == "chart"  # enrollment channel is now recorded


def _add_channel_with_videos(db, channel_id, langs):
    """Enroll an active channel + one tracked video/snapshot per language code."""
    from datetime import datetime

    db.add(TrackedChannel(channel_id=channel_id, recent_video_count=len(langs), is_active=True))
    for i, lang in enumerate(langs):
        vid = f"{channel_id}_v{i}"
        title = "How to cook pasta" if lang == "en" else "Como fazer macarrao"
        db.add(TrackedVideo(video_id=vid, channel_id=channel_id, title=title, published_at=datetime.utcnow()))
        db.add(VideoSnapshot(video_id=vid, checkpoint="6h", hours_since_publish=6.0,
                             title=title, default_audio_language=lang))
    db.commit()


class TestPruneNonEnglish:
    def test_deactivates_non_english_keeps_english(self, db):
        _add_channel_with_videos(db, "UCen", ["en", "en", "en"])
        _add_channel_with_videos(db, "UCpt", ["pt", "pt", "pt"])
        out = ce.prune_non_english_channels(db)
        assert out["deactivated"] == 1
        assert db.query(TrackedChannel).filter_by(channel_id="UCen").one().is_active is True
        assert db.query(TrackedChannel).filter_by(channel_id="UCpt").one().is_active is False

    def test_leaves_thin_signal_active(self, db):
        # Fewer than PRUNE_MIN_SAMPLE judged videos -> not enough to deactivate.
        _add_channel_with_videos(db, "UCfew", ["pt", "pt"])
        out = ce.prune_non_english_channels(db)
        assert out["deactivated"] == 0
        assert db.query(TrackedChannel).filter_by(channel_id="UCfew").one().is_active is True

    def test_safety_abort_when_signal_looks_broken(self, db, monkeypatch):
        # If almost everything would be deactivated, refuse (likely broken data).
        _add_channel_with_videos(db, "UCpt", ["pt", "pt", "pt"])
        monkeypatch.setattr(ce, "PRUNE_MAX_SHARE", 0.0)
        out = ce.prune_non_english_channels(db)
        assert out.get("aborted") is True and out["deactivated"] == 0
        assert db.query(TrackedChannel).filter_by(channel_id="UCpt").one().is_active is True


class _SearchClient:
    """Stub YouTube client: returns fixed channel-search items, records queries."""

    def __init__(self, items):
        self._items = items
        self.queries = []

    def search_channels(self, query, max_results=50, region_code="US", relevance_language="en"):
        self.queries.append((query, region_code))
        return {"items": self._items}


def _chan_item(channel_id, title):
    return {"id": {"channelId": channel_id}, "snippet": {"title": title}}


class TestSearchDiscovery:
    def test_enrolls_english_skips_foreign_and_dupes(self, db):
        db.add(TrackedChannel(channel_id="UCdupe", recent_video_count=1, is_active=True))
        db.commit()
        client = _SearchClient([
            _chan_item("UCnew", "How to Build a PC"),     # English -> enroll
            _chan_item("UCdupe", "Already Tracked"),       # already tracked -> skip
            _chan_item("UCforeign", "వంట చానల్"),          # non-Latin -> skip
        ])
        out = ce.discover_channels_by_search(db, client, max_queries=1)
        assert out["enrolled"] == 1
        row = db.query(TrackedChannel).filter_by(channel_id="UCnew").one()
        assert row.is_active and row.enrolled_via == "search"
        assert row.source.startswith("search:")

    def test_bounded_by_max_queries(self, db):
        client = _SearchClient([])
        ce.discover_channels_by_search(db, client, max_queries=3)
        assert len(client.queries) == 3  # one search.list call per starved niche, capped

    def test_starved_niches_prefer_coverage(self, db):
        from datetime import datetime

        from src.database.models import NicheCoverage
        now = datetime.utcnow()
        db.add(NicheCoverage(niche="20", starved=True, deficit=500, tracked_channels=10,
                             target_channels=3300, computed_at=now))
        db.add(NicheCoverage(niche="27", starved=False, deficit=0, tracked_channels=4000,
                             target_channels=3300, computed_at=now))
        db.commit()
        assert ce._starved_niches(db) == ["20"]  # only the starved niche, not the healthy one
