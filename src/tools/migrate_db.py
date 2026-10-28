"""One-shot data copy Supabase -> hosted Postgres, run INSIDE an app
container (so both endpoints are in the same region and the dest hop is the
private network -- orders of magnitude faster than streaming through a laptop).

Gated by the ``MIGRATE_DB_TO`` env var (the destination PG's internal URL, e.g.
postgresql://USER:PASSWORD@DB_HOST:5432/DB_NAME). When set, the scheduler
runs this once on boot before starting its jobs, then continues normally. Remove
the var after it completes.

Assumes the dest schema already exists (built via create_all + alembic stamp).
Idempotent: each table is truncated then COPY'd, so a restart mid-run is safe.
FK triggers are disabled during load. Verifies row counts per table.
"""
from __future__ import annotations

import os
import tempfile
import time

import structlog

logger = structlog.get_logger(__name__)


def _norm(u: str) -> str:
    return u.replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://")


def _direct_from_pooler(url: str):
    """Extract ``(ref, password)`` from a Supabase Supavisor pooler URL, used to
    build the direct / per-project db-host endpoints that bypass the shared
    pooler. Returns None if the URL isn't a recognisable pooler URL.

    Pooler: postgresql://postgres.<ref>:<pw>@aws-N-<region>.pooler.supabase.com:5432/postgres"""
    import re

    m = re.match(r"postgresql://postgres\.([a-z0-9]+):([^@]+)@[^/]*pooler\.supabase\.com", url)
    if not m:
        return None
    ref, pw = m.group(1), m.group(2)
    return ref, pw


def _connect_source(url: str):
    """Connect to the source DB, preferring endpoints that bypass the shared
    session pooler (which exhausts its slots -> ECHECKOUTTIMEOUT), falling back
    to the pooler URL with retries."""
    import psycopg2

    # Proven from a Railway container: the db.<ref> hosts are IPv6-only and
    # Railway has no IPv6 egress -- don't waste 40s failing on them. The session
    # pooler connects (with retries for a free slot); the shared transaction
    # pooler (same host, port 6543) is the IPv4 fallback.
    candidates = [("pooler", url)]
    if ".pooler.supabase.com:5432" in url:
        candidates.append(("txn-6543", url.replace(":5432/", ":6543/")))

    last = None
    for label, dsn in candidates:
        for attempt in range(6):
            try:
                conn = psycopg2.connect(
                    _norm(dsn), connect_timeout=30, client_encoding="utf8",
                    # Dead-connection detection: the 1.9GB COPY hung 13h when the
                    # pooler silently dropped the stream (statement_timeout=0
                    # removed the only safety net). Keepalives surface a dead
                    # peer in ~1 min instead of blocking forever.
                    keepalives=1, keepalives_idle=30,
                    keepalives_interval=10, keepalives_count=3,
                )
                # autocommit BEFORE any execute: otherwise the SET below opens a
                # transaction and run_copy's autocommit toggle raises
                # 'set_session cannot be used inside a transaction'.
                conn.autocommit = True
                # The source role has statement_timeout=2min, which kills the
                # count()/COPY of big tables mid-migration. Lift it for this
                # session (best-effort; harmless if the pooler drops the SET).
                try:
                    with conn.cursor() as c:
                        c.execute("SET statement_timeout = 0")
                except Exception:  # noqa: BLE001
                    pass
                logger.info("migrate.source_connected", via=label, attempt=attempt + 1)
                return conn
            except Exception as e:  # noqa: BLE001
                last = e
                logger.warning("migrate.source_connect_retry", via=label,
                               attempt=attempt + 1, error=str(e).strip()[:80])
                time.sleep(5)
    raise last


def _common_columns(src, dst, table: str):
    """Columns present on BOTH sides, in dest order. COPY without a column list
    depends on physical column order, which drifts between a long-lived prod
    table and a freshly created one (observed: prod channels' timestamp landed
    in engagement_rate). An explicit intersection list is order-proof and
    tolerates columns that exist on only one side."""
    q = ("SELECT column_name FROM information_schema.columns "
         "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position")
    with src.cursor() as c:
        c.execute(q, (table,))
        s = [r[0] for r in c.fetchall()]
    with dst.cursor() as c:
        c.execute(q, (table,))
        d = [r[0] for r in c.fetchall()]
    s_set = set(s)
    cols = [col for col in d if col in s_set]
    skipped = sorted((s_set | set(d)) - set(cols))
    return cols, skipped


# Tables above this row count copy in id-ordered chunks with resume, instead of
# one giant COPY. A single 30-min COPY of the 1.9GB video_snapshots hung forever
# when the pooler dropped the stream mid-way; chunks bound each statement to a
# few minutes and a restart resumes from dst max(id) instead of starting over.
CHUNK_THRESHOLD = 300_000
CHUNK_ROWS = 100_000


def _copy_chunked(src, dst, t: str, collist: str, n_src: int) -> int:
    """Append-only chunked copy for big serial-PK tables. Never truncates:
    resumes from the dest's max(id). Correct for append-only tables (snapshots);
    rows updated in place on the source after their chunk copied are not
    re-synced -- acceptable for immutable snapshot rows."""
    total_bytes = 0
    with dst.cursor() as dc:
        dc.execute(f'SELECT coalesce(max(id), 0) FROM "{t}"')
        last = dc.fetchone()[0]
    if last:
        logger.info("migrate.chunk_resume", table=t, from_id=last)
    while True:
        with tempfile.TemporaryFile() as f:
            with src.cursor() as sc:
                sc.copy_expert(
                    f'COPY (SELECT {collist} FROM "{t}" WHERE id > {int(last)} '
                    f'ORDER BY id LIMIT {CHUNK_ROWS}) TO STDOUT', f)
            size = f.tell()
            if size == 0:
                break
            f.seek(0)
            with dst.cursor() as dc:
                dc.copy_expert(f'COPY "{t}" ({collist}) FROM STDIN', f)
        dst.commit()
        total_bytes += size
        with dst.cursor() as dc:
            dc.execute(f'SELECT coalesce(max(id), 0), count(*) FROM "{t}"')
            last, n_dst = dc.fetchone()
        logger.info("migrate.chunk", table=t, dst_rows=n_dst, of=n_src,
                    mb=round(total_bytes / 1e6, 1))
    return total_bytes


def run_copy(src_url: str, dst_url: str) -> dict:
    import psycopg2

    from src.database.models import Base

    src = _connect_source(src_url)
    dst = psycopg2.connect(_norm(dst_url), connect_timeout=30, client_encoding="utf8")
    src.autocommit = True
    dst.autocommit = False
    with dst.cursor() as c:
        c.execute("SET session_replication_role = replica")  # skip FK triggers

    tables = [t.name for t in Base.metadata.sorted_tables if t.name != "alembic_version"]
    total = 0
    for t in tables:
        with src.cursor() as sc:
            sc.execute(f'SELECT count(*) FROM "{t}"')
            n_src = sc.fetchone()[0]
        with dst.cursor() as dc:
            dc.execute(f'SELECT count(*) FROM "{t}"')
            n_dst_before = dc.fetchone()[0]
        # Idempotent skip: if this table already fully copied, don't redo it.
        if n_src == n_dst_before and n_src > 0:
            logger.info("migrate.skip_done", table=t, rows=n_src)
            total += n_src
            continue
        cols, skipped_cols = _common_columns(src, dst, t)
        if skipped_cols:
            logger.warning("migrate.cols_skipped", table=t, cols=skipped_cols)
        collist = ", ".join(f'"{c}"' for c in cols)
        logger.info("migrate.table_start", table=t, src_rows=n_src)
        t0 = time.time()
        if n_src > CHUNK_THRESHOLD and "id" in cols:
            size = _copy_chunked(src, dst, t, collist, n_src)
        else:
            with tempfile.TemporaryFile() as f:
                with src.cursor() as sc:
                    sc.copy_expert(f'COPY (SELECT {collist} FROM "{t}") TO STDOUT', f)
                size = f.tell()
                f.seek(0)
                with dst.cursor() as dc:
                    dc.execute(f'TRUNCATE "{t}" CASCADE')
                    dc.copy_expert(f'COPY "{t}" ({collist}) FROM STDIN', f)
        dst.commit()
        with dst.cursor() as dc:
            dc.execute(f'SELECT count(*) FROM "{t}"')
            n_dst = dc.fetchone()[0]
        total += n_dst
        logger.info("migrate.table", table=t, src=n_src, dst=n_dst,
                    ok=(n_dst == n_src), mb=round(size / 1e6, 1),
                    secs=round(time.time() - t0, 1))
    with dst.cursor() as c:
        c.execute("SET session_replication_role = default")
    dst.commit()
    src.close()
    dst.close()
    logger.info("migrate.done", total_rows=total)
    return {"tables": len(tables), "total_rows": total}


def maybe_run_boot_migration() -> None:
    """If MIGRATE_DB_TO is set, run the one-shot copy before the scheduler starts.

    Best-effort: on failure we log and let the scheduler proceed (the app keeps
    running on the source DB). Remove the env var once it has completed."""
    dest = os.environ.get("MIGRATE_DB_TO")
    if not dest:
        return
    src = os.environ.get("DATABASE_URL")
    if not src:
        logger.warning("migrate.no_source")
        return
    logger.info("migrate.starting")
    try:
        run_copy(src, dest)
    except Exception as e:  # noqa: BLE001
        logger.error("migrate.failed", error=str(e)[:300])
