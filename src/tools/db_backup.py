"""Nightly DB backup + snapshot archival to R2 (the Option-B storage strategy).

Two jobs in one, run daily by the scheduler:

**Backup** — every table is exported with ``COPY ... TO STDOUT WITH CSV HEADER``,
gzipped, and uploaded to ``db-backups/<YYYY-MM-DD>/<table>.csv.gz`` plus a
``manifest.json`` (row counts + alembic version). Railway PG has no managed
backups and this dataset has been lost once before — this is the safety net.
Restore runbook (proven during the Supabase migration): fresh schema via
``Base.metadata.create_all`` + ``alembic stamp head``, then per-table
``COPY ... FROM`` with an explicit column list, then reset sequences with
``setval(pg_get_serial_sequence(t,'id'), max(id)+1)``.

**Archival** — snapshots belonging to videos that finished tracking long ago
are exported to ``snapshot-archive/<date>.csv.gz`` and then DELETEd, keeping
the 5GB Hobby-plan volume flat forever. The age gate (default 49 days after
publish ≈ 2 weeks after tracking completes) keeps recently-completed
trajectories in Postgres for model retraining; archived rows remain loadable
from R2. Deletion happens ONLY after the archive object is uploaded and
size-verified. Retention pruning keeps the last ``BACKUP_KEEP_DAYS`` dailies.
"""
from __future__ import annotations

import gzip
import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta

import structlog

logger = structlog.get_logger(__name__)

BACKUP_PREFIX = "db-backups"
ARCHIVE_PREFIX = "snapshot-archive"
BACKUP_KEEP_DAYS = int(os.getenv("DB_BACKUP_KEEP_DAYS", "14"))
# Videos published more than this many days ago have their snapshots archived out
# of PG. 42 = the 35-day tracking horizon + grace, i.e. tracking is finished, so
# archiving a video never truncates a live trajectory.
#
# This was 49 and it is WHY the disk filled on 2026-07-17: with collection only
# started in June, almost no tracked video was 49 days old, so the nightly job
# found nothing to archive while the volume climbed to 100% and crashed Postgres
# (13-day outage). Age alone is not a safe bound — see ``capacity_pct`` and the
# ``aggressive`` escalation below, which react to actual size pressure.
ARCHIVE_MIN_AGE_DAYS = int(os.getenv("DB_ARCHIVE_MIN_AGE_DAYS", "42"))
ARCHIVE_MAX_ROWS = int(os.getenv("DB_ARCHIVE_MAX_ROWS", "500000"))
# Under size pressure, step the age gate down (never below the last entry, so a
# recent trajectory is never archived mid-flight).
ARCHIVE_PRESSURE_STEPS = [35, 28, 21]
# Usable capacity of the Postgres volume. Railway Hobby caps volumes at 5000MB.
PG_VOLUME_LIMIT_MB = int(os.getenv("PG_VOLUME_LIMIT_MB", "5000"))
CAPACITY_WARN_PCT = float(os.getenv("PG_CAPACITY_WARN_PCT", "70"))
CAPACITY_ACT_PCT = float(os.getenv("PG_CAPACITY_ACT_PCT", "80"))


def _r2():
    """boto3 S3 client for R2 (same env contract as fetch_ml_artifacts)."""
    import boto3
    from botocore.config import Config

    acct = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def _pg():
    import psycopg2

    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(url, connect_timeout=30, client_encoding="utf8",
                            keepalives=1, keepalives_idle=30,
                            keepalives_interval=10, keepalives_count=3)
    conn.autocommit = False
    return conn


def _copy_gzip_to_r2(conn, r2, bucket: str, key: str, copy_sql: str) -> tuple[int, int]:
    """Stream a COPY into a gzipped temp file, upload to R2.

    Returns (raw_bytes, gz_bytes). Raises on any failure — callers must treat
    an exception as 'object not uploaded'."""
    with tempfile.TemporaryFile() as tmp:
        raw = 0
        with gzip.GzipFile(fileobj=tmp, mode="wb") as gz:
            class _Counter(io.RawIOBase):
                def write(self_, b):  # noqa: N805
                    nonlocal raw
                    raw += len(b)
                    gz.write(bytes(b))
                    return len(b)
            with conn.cursor() as cur:
                cur.copy_expert(copy_sql, _Counter())
        gz_bytes = tmp.tell()
        tmp.seek(0)
        r2.upload_fileobj(tmp, bucket, key)
    # Verify the object landed with the expected size before anyone deletes rows.
    head = r2.head_object(Bucket=bucket, Key=key)
    if head["ContentLength"] != gz_bytes:
        raise RuntimeError(f"upload size mismatch for {key}: "
                           f"{head['ContentLength']} != {gz_bytes}")
    return raw, gz_bytes


def run_backup(conn=None, r2=None) -> dict:
    """Full logical backup: every table -> db-backups/<date>/<table>.csv.gz."""
    from src.database.models import Base

    conn = conn or _pg()
    r2 = r2 or _r2()
    bucket = os.environ["R2_BUCKET_NAME"]
    day = date.today().isoformat()
    tables = [t.name for t in Base.metadata.sorted_tables]
    manifest: dict = {"date": day, "tables": {}, "started": datetime.utcnow().isoformat()}

    for t in tables:
        with conn.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM "{t}"')
            n = cur.fetchone()[0]
        raw, gz_b = _copy_gzip_to_r2(
            conn, r2, bucket, f"{BACKUP_PREFIX}/{day}/{t}.csv.gz",
            f'COPY (SELECT * FROM "{t}") TO STDOUT WITH CSV HEADER')
        manifest["tables"][t] = {"rows": n, "raw_bytes": raw, "gz_bytes": gz_b}
        conn.commit()  # release the COPY's snapshot/locks between tables

    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        manifest["alembic_version"] = cur.fetchone()[0]
    manifest["finished"] = datetime.utcnow().isoformat()
    r2.put_object(Bucket=bucket, Key=f"{BACKUP_PREFIX}/{day}/manifest.json",
                  Body=json.dumps(manifest, indent=2).encode())

    pruned = _prune_old_backups(r2, bucket)
    total_gz = sum(v["gz_bytes"] for v in manifest["tables"].values())
    logger.info("db_backup.complete", tables=len(tables),
                gz_mb=round(total_gz / 1e6, 1), pruned_days=pruned)
    return {"tables": len(tables), "gz_bytes": total_gz, "pruned_days": pruned}


def _prune_old_backups(r2, bucket: str) -> int:
    """Delete backup day-prefixes older than BACKUP_KEEP_DAYS."""
    cutoff = (date.today() - timedelta(days=BACKUP_KEEP_DAYS)).isoformat()
    pruned = 0
    resp = r2.list_objects_v2(Bucket=bucket, Prefix=f"{BACKUP_PREFIX}/", Delimiter="/")
    for p in resp.get("CommonPrefixes", []):
        day = p["Prefix"].split("/")[-2]
        if day < cutoff:
            objs = r2.list_objects_v2(Bucket=bucket, Prefix=p["Prefix"])
            keys = [{"Key": o["Key"]} for o in objs.get("Contents", [])]
            if keys:
                r2.delete_objects(Bucket=bucket, Delete={"Objects": keys})
            pruned += 1
    return pruned


def capacity_pct(conn) -> dict:
    """Postgres volume usage estimate: database + WAL vs the volume limit.

    The scheduler cannot ``df`` the Postgres service's volume, so size is derived
    in-database (pg_database_size + pg_ls_waldir), which tracked the real volume
    figure closely in the 2026-07 incident. This is the signal whose absence let
    the disk reach 100% unnoticed: monitoring watched row counts, not bytes."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_database_size(current_database())")
        db_b = cur.fetchone()[0]
        try:
            # sum() returns Decimal — cast, or the arithmetic below raises.
            cur.execute("SELECT coalesce(sum(size), 0)::bigint FROM pg_ls_waldir()")
            wal_b = cur.fetchone()[0]
        except Exception:  # noqa: BLE001 — needs superuser on some setups
            conn.rollback()
            wal_b = 0
    db_b, wal_b = int(db_b), int(wal_b)
    total_mb = (db_b + wal_b) / 1e6
    pct = 100.0 * total_mb / max(PG_VOLUME_LIMIT_MB, 1)
    return {"db_mb": round(db_b / 1e6, 1), "wal_mb": round(wal_b / 1e6, 1),
            "total_mb": round(total_mb, 1), "limit_mb": PG_VOLUME_LIMIT_MB,
            "pct": round(pct, 1)}


def select_archivable_ids(session, min_age_days: int = ARCHIVE_MIN_AGE_DAYS,
                          cap: int = ARCHIVE_MAX_ROWS,
                          aggressive: bool = False) -> list[int]:
    """Snapshot ids safe to move out of PG: their video was published more than
    ``min_age_days`` ago, so its tracking horizon has closed and archiving it
    cannot truncate a live trajectory.

    ``aggressive`` (set by the caller under size pressure) steps the age gate
    down through ARCHIVE_PRESSURE_STEPS until a batch is found, so a full volume
    can always be relieved even when no video is old enough for the normal gate.
    Pure SQLAlchemy — unit-testable."""
    from sqlalchemy import select

    from src.database.models import TrackedVideo, VideoSnapshot

    thresholds = [min_age_days] + (ARCHIVE_PRESSURE_STEPS if aggressive else [])
    for days in thresholds:
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = session.execute(
            select(VideoSnapshot.id)
            .join(TrackedVideo, TrackedVideo.video_id == VideoSnapshot.video_id)
            .where(TrackedVideo.published_at < cutoff)
            .order_by(VideoSnapshot.id)
            .limit(cap)
        ).all()
        if rows:
            if days != min_age_days:
                logger.warning("db_archive.pressure_gate", used_days=days)
            return [r[0] for r in rows]
    return []


def run_archive(conn=None, r2=None, ids: list[int] | None = None,
                aggressive: bool = False) -> dict:
    """Export archivable snapshots to R2, verify, then delete them from PG."""
    conn = conn or _pg()
    r2 = r2 or _r2()
    bucket = os.environ["R2_BUCKET_NAME"]

    if ids is None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg2://")
        eng = create_engine(url)
        s = sessionmaker(bind=eng)()
        try:
            ids = select_archivable_ids(s, aggressive=aggressive)
        finally:
            s.close()
            eng.dispose()
    if not ids:
        logger.info("db_archive.nothing_eligible")
        return {"archived": 0}

    key = f"{ARCHIVE_PREFIX}/{date.today().isoformat()}-{ids[0]}-{ids[-1]}.csv.gz"
    id_list = ",".join(str(int(i)) for i in ids)
    _copy_gzip_to_r2(
        conn, r2, bucket, key,
        f'COPY (SELECT * FROM video_snapshots WHERE id IN ({id_list}) ORDER BY id) '
        f'TO STDOUT WITH CSV HEADER')

    # Upload verified (size-checked) — only now is deletion allowed.
    deleted = 0
    with conn.cursor() as cur:
        for i in range(0, len(ids), 10_000):
            chunk = ids[i:i + 10_000]
            cur.execute("DELETE FROM video_snapshots WHERE id = ANY(%s)", (chunk,))
            deleted += cur.rowcount
        conn.commit()

    # DELETE leaves dead tuples: without this the file never stops growing even
    # though rows were archived (observed 2026-07-30 — db_mb was unchanged right
    # after a 368k-row archive). Plain VACUUM returns the space to Postgres for
    # reuse, which is what actually bounds the volume. (VACUUM FULL would shrink
    # the file but needs ~2x the table size in free space — impossible here,
    # which is exactly the situation we are recovering from.)
    prev_autocommit = conn.autocommit
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("VACUUM (ANALYZE) video_snapshots")
    except Exception as e:  # noqa: BLE001 — reclaim is best-effort
        logger.warning("db_archive.vacuum_failed", error=str(e)[:150])
    finally:
        conn.autocommit = prev_autocommit

    logger.info("db_archive.complete", archived=len(ids), deleted=deleted, key=key)
    return {"archived": len(ids), "deleted": deleted, "key": key}


def run_backup_and_archive() -> dict:
    """Nightly entry point: backup first; archive only if the backup succeeded.

    Archival escalates to ``aggressive`` when the volume is already under
    pressure, so a nightly run can always relieve a filling disk."""
    conn = _pg()
    r2 = _r2()
    try:
        cap = capacity_pct(conn)
        logger.info("db_capacity", **cap)
        backup = run_backup(conn, r2)
        archive = run_archive(conn, r2, aggressive=cap["pct"] >= CAPACITY_WARN_PCT)
        return {"backup": backup, "archive": archive, "capacity": cap}
    finally:
        conn.close()


def capacity_guard() -> dict:
    """Hourly watchdog on Postgres volume usage.

    Exists because the 2026-07-17 outage was a *silent* disk-full: health checks
    queried row counts, never bytes, so the volume hit 100% between check-ins and
    corrupted WAL beyond in-place recovery (13 days down). At/above
    CAPACITY_ACT_PCT this archives immediately rather than waiting for the
    nightly job; every run logs the number so it is visible in the logs."""
    conn = _pg()
    try:
        cap = capacity_pct(conn)
        if cap["pct"] >= CAPACITY_ACT_PCT:
            logger.error("db_capacity.critical", action="archiving_now", **cap)
            res = run_archive(conn, _r2(), aggressive=True)
            after = capacity_pct(conn)
            logger.info("db_capacity.after_archive", archived=res.get("archived", 0),
                        **after)
            return {"capacity": cap, "action": "archived", "after": after}
        if cap["pct"] >= CAPACITY_WARN_PCT:
            logger.warning("db_capacity.high", **cap)
        else:
            logger.info("db_capacity.ok", **cap)
        return {"capacity": cap, "action": "none"}
    finally:
        conn.close()
