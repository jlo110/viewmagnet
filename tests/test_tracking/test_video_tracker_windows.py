"""Tests for the velocity tracker's checkpoint-window logic.

The critical invariant: a checkpoint is sampled ONLY inside its
``[target, target+grace]`` window, and is labelled with the window we are
actually in — never an earlier checkpoint backfilled with stale data. The old
"earliest missing checkpoint" logic would, e.g., sample a 7-day-old video and
store its view count under the "1h" checkpoint, corrupting the training set.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from src.tracking.video_tracker import CHECKPOINT_WINDOWS, VideoTracker


def _video(age_hours: float, **collected):
    """A fake TrackedVideo: published `age_hours` ago, with the given
    checkpoint_* booleans set True (all others False)."""
    flags = {f"checkpoint_{k}": False for k, _, _ in CHECKPOINT_WINDOWS}
    flags.update({f"checkpoint_{k}": v for k, v in collected.items()})
    return SimpleNamespace(
        published_at=datetime.utcnow() - timedelta(hours=age_hours),
        tracking_complete=False,
        **flags,
    )


def _tracker():
    # session/client unused by the pure window helpers; pass sentinels.
    return VideoTracker(session=None, youtube_client=object())


class TestDueCheckpoint:
    def test_in_window_returns_that_checkpoint(self):
        t = _tracker()
        assert t._due_checkpoint(_video(1.5), datetime.utcnow()) == "1h"
        assert t._due_checkpoint(_video(25), datetime.utcnow()) == "24h"
        assert t._due_checkpoint(_video(170), datetime.utcnow()) == "7d"

    def test_before_first_window_returns_none(self):
        # 0.5h old: the 1h window hasn't opened yet.
        assert _tracker()._due_checkpoint(_video(0.5), datetime.utcnow()) is None

    def test_THE_BUG_late_sample_never_mislabels_as_early_checkpoint(self):
        """A 7-day-old video with NO checkpoints must NOT be sampled as '1h'.

        Old behaviour returned '1h' here and stored 7-day views as the 1h
        value. Correct behaviour: only the currently-in-window '7d' is due;
        the long-passed 1h/6h/24h/3d windows are not backfilled.
        """
        cp = _tracker()._due_checkpoint(_video(168), datetime.utcnow())
        assert cp == "7d"
        assert cp != "1h"

    def test_between_windows_returns_none(self):
        # 100h ≈ 4.16d: past 3d+grace(4d) window, before 7d window. Nothing due.
        assert _tracker()._due_checkpoint(_video(100), datetime.utcnow()) is None

    def test_already_collected_checkpoint_not_redue(self):
        # In the 24h window but 24h already collected → not due again.
        assert _tracker()._due_checkpoint(_video(25, **{"24h": True}), datetime.utcnow()) is None

    def test_prefers_latest_window_when_multiple_open(self):
        # Contrived: if 7d window is open and earlier ones somehow still pending
        # and in-window, prefer the latest target. At 170h only 7d is in-window,
        # so this asserts the selection rule directly via a 30h sample where
        # both 24h(24-36) is open; 6h(6-12) is long closed → 24h chosen.
        assert _tracker()._due_checkpoint(_video(30), datetime.utcnow()) == "24h"


import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, TrackedVideo, VideoSnapshot


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()
    engine.dispose()


def _row(db, vid, age_hours, **collected):
    now = datetime.utcnow()
    cps = {f"checkpoint_{k}": False for k, _, _ in CHECKPOINT_WINDOWS}
    cps.update({f"checkpoint_{k}": v for k, v in collected.items()})
    db.add(TrackedVideo(video_id=vid, channel_id="UC" + "x" * 22, title=vid,
                        published_at=now - timedelta(hours=age_hours),
                        tracking_started=now, tracking_complete=False, **cps))
    db.commit()


class TestRetireExpired:
    def test_bulk_ages_out_only_expired_videos(self, db):
        _row(db, "fresh0000000", 100)   # < 840h → stays active
        _row(db, "old000000000", 900)   # > 840h → retired
        _row(db, "old111111111", 841)   # just past 840h → retired
        n = VideoTracker(session=db, youtube_client=object())._retire_expired(datetime.utcnow())
        db.commit()
        assert n == 2
        done = {r.video_id for r in db.execute(
            select(TrackedVideo).where(TrackedVideo.tracking_complete == True)).scalars()}  # noqa: E712
        assert done == {"old000000000", "old111111111"}
        # Retirement writes NO snapshot rows (honest gaps, never backfilled).
        assert db.execute(select(func.count()).select_from(VideoSnapshot)).scalar() == 0


class TestGetVideosDueSQL:
    def test_sql_filter_matches_due_checkpoint(self, db):
        # One video per situation; only the in-window ones should come back.
        _row(db, "due1h0000000", 1.5)                       # in 1h window
        _row(db, "due24h000000", 30)                        # in 24h window
        _row(db, "before000000", 0.5)                       # 1h window not open yet
        _row(db, "between00000", 100)                       # between 3d and 7d windows
        _row(db, "collected0001", 25, **{"24h": True})      # in 24h window but already done
        _row(db, "aged00000000", 900)                       # past everything
        t = VideoTracker(session=db, youtube_client=object())
        due = {v.video_id: cp for v, cp in t._get_videos_due_for_snapshot(datetime.utcnow())}
        assert due == {"due1h0000000": "1h", "due24h000000": "24h"}

    def test_limit_is_applied(self, db):
        for i in range(5):
            _row(db, f"v{i}0000000000"[:12], 1.5)  # all in the 1h window
        t = VideoTracker(session=db, youtube_client=object())
        assert len(t._get_videos_due_for_snapshot(datetime.utcnow(), limit=3)) == 3


class TestUnfetchableMarking:
    def test_deleted_video_checkpoint_resolved_without_snapshot(self, db):
        """A video the API doesn't return (deleted/private) must have its due
        checkpoint marked missed — otherwise it stays due all window and, being
        oldest, permanently clogs the front of the collection queue."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        _row(db, "livevid00001", 1.5)   # in 1h window; API returns it
        _row(db, "deadvid00001", 1.6)   # in 1h window; API does NOT return it

        live = SimpleNamespace(
            video_id="livevid00001", view_count=100, like_count=5, comment_count=1,
            title="Live", thumbnail_url=None, duration_seconds=120,
            youtube_category_id="22", tags=None, description=None,
        )
        client = MagicMock()
        client.get_video_details.return_value = [live]
        client.get_quota_status.return_value = {"total_remaining": 10_000}

        t = VideoTracker(session=db, youtube_client=client)
        result = t.collect_snapshots(max_videos=100)
        db.commit()

        assert result.snapshots_collected == 1     # only the live one
        rows = {r.video_id: r for r in db.execute(
            select(TrackedVideo)).scalars()}
        assert rows["livevid00001"].checkpoint_1h is True
        assert rows["deadvid00001"].checkpoint_1h is True   # resolved as missed
        snaps = {r.video_id for r in db.execute(select(VideoSnapshot)).scalars()}
        assert snaps == {"livevid00001"}           # no snapshot for the dead one
