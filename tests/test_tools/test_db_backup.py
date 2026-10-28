"""db_backup: archival eligibility + delete-only-after-verified-upload."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, TrackedVideo, VideoSnapshot
from src.tools.db_backup import select_archivable_ids, run_archive


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()
    engine.dispose()


def _video(db, vid, age_days, complete):
    now = datetime.utcnow()
    db.add(TrackedVideo(video_id=vid, channel_id="UC" + "x" * 22, title=vid,
                        published_at=now - timedelta(days=age_days),
                        tracking_started=now, tracking_complete=complete))
    db.add(VideoSnapshot(video_id=vid, checkpoint="24h",
                         hours_since_publish=24.0, view_count=100,
                         captured_at=now - timedelta(days=age_days - 1)))
    db.commit()


def test_eligibility_is_age_based(db):
    """Past the 42d gate the tracking horizon has closed, so tracking_complete is
    not required — requiring it was part of why the 2026-07 archival never fired."""
    _video(db, "oldcomplete1", age_days=60, complete=True)    # eligible
    _video(db, "oldactive001", age_days=60, complete=False)   # eligible: old enough
    _video(db, "newcomplete1", age_days=20, complete=True)    # too recent (<42d)
    ids = select_archivable_ids(db, min_age_days=42, cap=100)
    vids = {db.get(VideoSnapshot, i).video_id for i in ids}
    assert vids == {"oldcomplete1", "oldactive001"}


def test_aggressive_steps_gate_down_under_pressure(db):
    """With nothing past the normal gate, a full disk must still be relievable."""
    _video(db, "recent000001", age_days=30, complete=False)   # inside 42d gate
    assert select_archivable_ids(db, min_age_days=42, cap=100) == []
    ids = select_archivable_ids(db, min_age_days=42, cap=100, aggressive=True)
    assert len(ids) == 1  # found via the 28-day pressure step


def test_never_archives_inside_the_floor(db):
    """Even aggressive must not touch a trajectory younger than the last step."""
    _video(db, "veryfresh001", age_days=5, complete=False)
    assert select_archivable_ids(db, min_age_days=42, cap=100, aggressive=True) == []


def test_capacity_pct_math(monkeypatch):
    from unittest.mock import MagicMock
    import src.tools.db_backup as bk
    monkeypatch.setattr(bk, "PG_VOLUME_LIMIT_MB", 5000)
    cur = MagicMock()
    cur.fetchone.side_effect = [(3_000_000_000,), (1_000_000_000,)]
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = lambda s, *a: False
    cap = bk.capacity_pct(conn)
    assert cap["db_mb"] == 3000.0 and cap["wal_mb"] == 1000.0
    assert cap["pct"] == 80.0        # (3000+1000)/5000 -> acts at 80%


def test_cap_limits_batch(db):
    for i in range(5):
        _video(db, f"v{i}complete00", age_days=60, complete=True)
    assert len(select_archivable_ids(db, min_age_days=49, cap=3)) == 3


def test_archive_does_not_delete_when_upload_fails(db, monkeypatch):
    _video(db, "victim000001", age_days=60, complete=True)
    ids = select_archivable_ids(db, min_age_days=49, cap=10)
    assert ids

    conn = MagicMock()   # psycopg2 conn (unused before the failure)
    r2 = MagicMock()
    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")
    with patch("src.tools.db_backup._copy_gzip_to_r2",
               side_effect=RuntimeError("upload size mismatch")):
        with pytest.raises(RuntimeError):
            run_archive(conn=conn, r2=r2, ids=ids)
    # No DELETE was ever issued on the connection.
    assert not any("DELETE" in str(c) for c in conn.cursor.mock_calls)
    # And the row is still present in the DB session's world.
    assert db.execute(select(func.count()).select_from(VideoSnapshot)).scalar() == 1


def test_archive_deletes_after_verified_upload(db, monkeypatch):
    _video(db, "victim000002", age_days=60, complete=True)
    ids = select_archivable_ids(db, min_age_days=49, cap=10)

    executed = []
    cur = MagicMock()
    cur.rowcount = len(ids)
    cur.execute = lambda sql, params=None: executed.append(sql)
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = lambda s, *a: False
    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")
    with patch("src.tools.db_backup._copy_gzip_to_r2", return_value=(1000, 200)):
        out = run_archive(conn=conn, r2=MagicMock(), ids=ids)
    assert out["archived"] == len(ids) and out["deleted"] == len(ids)
    assert any("DELETE FROM video_snapshots" in s for s in executed)
