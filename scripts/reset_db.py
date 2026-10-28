"""Drop every table in the public schema and re-run Alembic migrations.

Use when the database schema and migration state are out of sync (e.g. the
'users' table exists but Alembic thinks revision 0 is current). This is a
development helper — never run against production data.

Usage:
    .venv/bin/python scripts/reset_db.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text  # noqa: E402

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    print("ERROR: DATABASE_URL is not set. Source .env first or export it.")
    sys.exit(1)


def main() -> None:
    print(f"[reset-db] Connecting to {DB_URL.split('@', 1)[-1]}")
    engine = create_engine(DB_URL, isolation_level="AUTOCOMMIT")

    with engine.connect() as conn:
        print("[reset-db] Dropping all tables in public schema…")
        # CASCADE drops dependent objects (foreign keys, sequences, etc.)
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        print("[reset-db] Public schema dropped + recreated.")

    print("[reset-db] Running 'alembic upgrade head'…")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ},
    )
    if result.returncode != 0:
        print("[reset-db] Alembic upgrade FAILED — see output above.")
        sys.exit(result.returncode)

    print("[reset-db] Done.")


if __name__ == "__main__":
    main()
