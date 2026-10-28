"""Restore the database from an R2 logical backup (disaster recovery).

Companion to ``db_backup.py``. Used for real on 2026-07-30 after the Postgres
volume filled to 100%, corrupting WAL beyond in-place recovery: a fresh volume
was provisioned and the Jul-16 backup restored into it.

Procedure (proven twice — this and the Supabase migration):
  1. schema via ``Base.metadata.create_all`` + ``alembic stamp head``
     (the migration chain cannot build a fresh DB: 0032+ ALTERs tables that no
     migration creates, so `upgrade head` fails on an empty database)
  2. per-table ``COPY ... FROM STDIN WITH CSV``, streaming the gzip straight
     from R2, using an explicit column list read from each CSV's header
     (physical column order drifts between a long-lived table and a fresh one)
  3. ``setval`` every id sequence to ``max(id)+1`` — COPY does not advance them,
     so without this the first insert collides

``--keep-days`` bounds what lands in Postgres: only snapshots belonging to
videos published within that window are loaded, which keeps each restored
trajectory *intact* (filtering by snapshot age would truncate trajectories
mid-flight). Older snapshots stay in the R2 backup, which is the archive of
record and what model retraining should read. That is the deliberate
serving-set/archive split — it is also what keeps a 5GB volume viable.

Usage (inside a Railway container, so R2 and PG are both local):
    python -m src.tools.db_restore --date 2026-07-16 --keep-days 30
    python -m src.tools.db_restore --date 2026-07-16 --dry-run
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
from datetime import datetime, timedelta

import structlog

logger = structlog.get_logger(__name__)

BACKUP_PREFIX = "db-backups"
# Staging/derived tables not worth restoring into the serving set; they stay in
# the R2 backup. backfill_videos is a historical-import staging table (~200MB).
SKIP_TABLES = {"backfill_videos"}
# Only this table is row-filtered; everything else restores whole.
FILTERED_TABLE = "video_snapshots"


def _r2():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url="https://" + os.environ["R2_ACCOUNT_ID"] + ".r2.cloudflarestorage.com",
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


class _FilteredCSV(io.RawIOBase):
    """File-like feed of a CSV, re-emitting only rows whose ``key_idx`` column
    value is in ``keep``. Used so a filtered COPY needs no temp file.

    Note: parsing loses the CSV distinction between an unquoted empty field
    (NULL) and a quoted one (empty string), so empty strings come back as NULL.
    Only applied to ``video_snapshots``, whose NOT NULL columns (video_id,
    checkpoint) are never empty — every other table streams raw, unparsed.
    """

    def __init__(self, text_stream, key_idx: int, keep: set):
        self._reader = csv.reader(text_stream)
        self._key_idx = key_idx
        self._keep = keep
        self._buf = bytearray()
        self._done = False
        self.kept = 0
        self.seen = 0
        self._sio = io.StringIO()
        self._writer = csv.writer(self._sio, lineterminator="\n")

    def readable(self) -> bool:
        return True

    def _fill(self, n: int) -> None:
        while not self._done and len(self._buf) < n:
            try:
                row = next(self._reader)
            except StopIteration:
                self._done = True
                break
            self.seen += 1
            if row[self._key_idx] in self._keep:
                self._sio.seek(0)
                self._sio.truncate(0)
                self._writer.writerow(row)
                self._buf += self._sio.getvalue().encode("utf-8")
                self.kept += 1

    def readinto(self, b) -> int:  # noqa: D102
        self._fill(len(b))
        n = min(len(b), len(self._buf))
        b[:n] = self._buf[:n]
        del self._buf[:n]
        return n


def _read_line(stream) -> bytes:
    """Read one newline-terminated line from a binary stream without buffering
    ahead (so the stream stays usable for a subsequent bulk COPY)."""
    out = bytearray()
    while True:
        ch = stream.read(1)
        if not ch or ch == b"\n":
            break
        out += ch
    return bytes(out).rstrip(b"\r")


def _table_columns(conn, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s", (table,))
        return [r[0] for r in cur.fetchall()]


def build_schema() -> None:
    """create_all + alembic stamp head on an empty database."""
    import subprocess

    from sqlalchemy import create_engine, text

    from src.database.models import Base

    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg2://")
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    with eng.connect() as c:
        n = c.execute(text("SELECT count(*) FROM information_schema.tables "
                           "WHERE table_schema='public'")).scalar()
    eng.dispose()
    logger.info("restore.schema_created", tables=n)
    r = subprocess.run([sys.executable, "-m", "alembic", "stamp", "head"],
                       capture_output=True, text=True)
    logger.info("restore.alembic_stamped", ok=(r.returncode == 0),
                err=r.stderr.strip()[-200:] if r.returncode else "")


# Count/metric columns the ORM declares as Integer but which hold values beyond
# int4 in practice (a real channel_snapshots.video_count of 62,143,541,891 broke
# both this restore and the Supabase migration). Widen them on the fresh schema
# before loading; they are metrics, never PKs/FKs, so widening is always safe.
_WIDEN_PATTERNS = ["%count%", "%views%", "%_likes", "%like_%", "%subscriber%",
                   "%comment%", "%shares%", "%impressions%", "%_views%", "%duration%"]


def widen_metric_columns(conn) -> int:
    """ALTER integer count/metric columns to bigint so COPY can't overflow."""
    like = " OR ".join("column_name LIKE %s" for _ in _WIDEN_PATTERNS)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            f"WHERE table_schema='public' AND data_type='integer' AND ({like})",
            _WIDEN_PATTERNS)
        targets = cur.fetchall()
        for t, col in targets:
            cur.execute(f'ALTER TABLE "{t}" ALTER COLUMN "{col}" TYPE bigint')
    conn.autocommit = False
    logger.info("restore.columns_widened", count=len(targets))
    return len(targets)


def _eligible_video_ids(conn, keep_days: int, backup_date: str) -> set:
    """video_ids published within keep_days of the backup date. Trajectories for
    these stay whole in Postgres; everything older lives in the R2 backup."""
    cutoff = datetime.fromisoformat(backup_date) - timedelta(days=keep_days)
    with conn.cursor() as cur:
        cur.execute("SELECT video_id FROM tracked_videos WHERE published_at >= %s",
                    (cutoff,))
        ids = {r[0] for r in cur.fetchall()}
    logger.info("restore.eligible_videos", count=len(ids), cutoff=cutoff.isoformat())
    return ids


def restore(date: str, keep_days: int = 30, dry_run: bool = False) -> dict:
    r2 = _r2()
    bucket = os.environ["R2_BUCKET_NAME"]
    manifest = json.loads(
        r2.get_object(Bucket=bucket, Key=f"{BACKUP_PREFIX}/{date}/manifest.json")
        ["Body"].read())
    tables = manifest["tables"]
    logger.info("restore.manifest", date=date, tables=len(tables),
                alembic=manifest.get("alembic_version"))
    if dry_run:
        for t, meta in sorted(tables.items(), key=lambda kv: -kv[1]["gz_bytes"]):
            logger.info("restore.plan", table=t, rows=meta["rows"],
                        gz_mb=round(meta["gz_bytes"] / 1e6, 1),
                        action=("SKIP" if t in SKIP_TABLES else
                                "FILTER" if t == FILTERED_TABLE else "FULL"))
        return {"dry_run": True, "tables": len(tables)}

    build_schema()
    conn = _pg()
    widen_metric_columns(conn)
    results: dict = {}

    # Everything except the filtered table first (the filter needs tracked_videos).
    order = [t for t in tables if t not in SKIP_TABLES and t != FILTERED_TABLE]
    for t in order + [FILTERED_TABLE]:
        if t not in tables or t in SKIP_TABLES:
            continue
        live_cols = _table_columns(conn, t)
        if not live_cols:
            logger.warning("restore.table_missing_in_schema", table=t)
            continue
        obj = r2.get_object(Bucket=bucket, Key=f"{BACKUP_PREFIX}/{date}/{t}.csv.gz")
        gz = gzip.GzipFile(fileobj=io.BytesIO(obj["Body"].read()))
        # Read the header off the BINARY stream byte-wise: a TextIOWrapper would
        # read ahead into its own buffer, so handing the raw stream to COPY
        # afterwards would skip data. Column names never contain newlines.
        header = next(csv.reader([_read_line(gz).decode("utf-8")]))
        cols = [c for c in header if c in set(live_cols)]
        if len(cols) != len(header):
            logger.warning("restore.column_drift", table=t,
                           dropped=sorted(set(header) - set(cols)))
        collist = ", ".join(f'"{c}"' for c in cols)

        with conn.cursor() as cur:
            # Idempotent: a re-run after a mid-restore failure must not double-load.
            cur.execute(f'TRUNCATE "{t}" CASCADE')
            if t == FILTERED_TABLE:
                keep = _eligible_video_ids(conn, keep_days, date)
                # Header already consumed from the binary stream, so the text
                # wrapper starts on the first data row.
                text_stream = io.TextIOWrapper(gz, encoding="utf-8", newline="")
                src = _FilteredCSV(text_stream, header.index("video_id"), keep)
                cur.copy_expert(f'COPY "{t}" ({collist}) FROM STDIN WITH CSV', src)
                logger.info("restore.filtered", table=t, seen=src.seen, kept=src.kept)
            else:
                cur.copy_expert(f'COPY "{t}" ({collist}) FROM STDIN WITH CSV', gz)
            cur.execute(f'SELECT count(*) FROM "{t}"')
            n = cur.fetchone()[0]
        conn.commit()
        results[t] = {"rows": n, "backup_rows": tables[t]["rows"]}
        logger.info("restore.table", table=t, restored=n, in_backup=tables[t]["rows"])

    reset_sequences(conn)
    conn.close()
    total = sum(v["rows"] for v in results.values())
    logger.info("restore.complete", tables=len(results), total_rows=total)
    return {"tables": len(results), "total_rows": total, "detail": results}


def reset_sequences(conn) -> int:
    """COPY does not advance sequences; without this the first insert collides."""
    fixed = 0
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND column_name='id'")
        for (t,) in cur.fetchall():
            cur.execute("SELECT pg_get_serial_sequence(%s, 'id')", (f'"{t}"',))
            seq = cur.fetchone()[0]
            if not seq:
                continue
            cur.execute(f'SELECT coalesce(max(id), 0) FROM "{t}"')
            cur.execute("SELECT setval(%s, %s, false)", (seq, cur.fetchone()[0] + 1))
            fixed += 1
    conn.autocommit = False
    logger.info("restore.sequences_reset", tables=fixed)
    return fixed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", required=True, help="backup date, e.g. 2026-07-16")
    ap.add_argument("--keep-days", type=int, default=30,
                    help="load snapshots for videos published within N days of --date")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    restore(a.date, a.keep_days, a.dry_run)


if __name__ == "__main__":
    main()
