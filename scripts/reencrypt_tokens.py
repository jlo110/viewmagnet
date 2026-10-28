"""Re-encrypt at-rest OAuth tokens after an ENCRYPTION_KEY rotation.

Context
-------
``ENCRYPTION_KEY`` (a Fernet key) encrypts OAuth tokens at rest. It leaked via
a committed ``.env`` and must be rotated. Rotating the key alone makes every
existing ciphertext undecryptable, so every stored token must be decrypted with
the OLD key and re-encrypted with the NEW key.

Encrypted columns (raw DB columns, ``enc:`` prefix + Fernet ciphertext):
  - youtube_connections.access_token / refresh_token / client_secret
  - connected_accounts.access_token / refresh_token

Usage
-----
    # 1. Generate a new key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    # 2. Dry run (default) — reports what WOULD change, writes nothing:
    OLD_ENCRYPTION_KEY="<leaked-key>" ENCRYPTION_KEY="<new-key>" \
        python -m scripts.reencrypt_tokens

    # 3. Apply:
    OLD_ENCRYPTION_KEY="<leaked-key>" ENCRYPTION_KEY="<new-key>" \
        python -m scripts.reencrypt_tokens --commit

    # 4. Deploy the app with ENCRYPTION_KEY=<new-key> and drop OLD_ENCRYPTION_KEY.

Safety
------
- Dry run by default; only ``--commit`` writes.
- Idempotent: rows already decryptable with the NEW key are skipped, so a
  re-run after a partial failure is safe.
- Rows that decrypt with NEITHER key are reported and left untouched (manual
  review) rather than silently dropped.
- Run a DB backup/snapshot before ``--commit``.
"""
from __future__ import annotations

import argparse
import os
import sys

import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from src.database.connection import get_session

logger = structlog.get_logger(__name__)

_PREFIX = "enc:"  # must match src/security/crypto.py

# (table, [columns]) — the raw encrypted columns.
_TARGETS = [
    ("youtube_connections", ["access_token", "refresh_token", "client_secret"]),
    ("connected_accounts", ["access_token", "refresh_token"]),
]


def _decrypt_with(fernet: Fernet, value: str) -> str | None:
    """Return plaintext if ``value`` decrypts with ``fernet``, else None.

    Non-prefixed values are treated as legacy plaintext (returned as-is).
    """
    if not value.startswith(_PREFIX):
        return value  # legacy plaintext
    try:
        return fernet.decrypt(value[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        return None


def _encrypt_with(fernet: Fernet, plaintext: str) -> str:
    return _PREFIX + fernet.encrypt(plaintext.encode()).decode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Apply changes. Without this flag the script is a dry run.",
    )
    args = parser.parse_args()

    old_key = os.environ.get("OLD_ENCRYPTION_KEY")
    new_key = os.environ.get("ENCRYPTION_KEY")
    if not old_key or not new_key:
        print("ERROR: set both OLD_ENCRYPTION_KEY and ENCRYPTION_KEY in the environment.")
        return 2
    if old_key == new_key:
        print("ERROR: OLD_ENCRYPTION_KEY and ENCRYPTION_KEY are identical — nothing to rotate.")
        return 2

    old_fernet = Fernet(old_key.encode())
    new_fernet = Fernet(new_key.encode())

    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"=== Token re-encryption ({mode}) ===")

    totals = {"rotated": 0, "already_new": 0, "plaintext": 0, "undecryptable": 0}

    with get_session() as session:
        for table, columns in _TARGETS:
            col_list = ", ".join(["id", *columns])
            rows = session.execute(text(f"SELECT {col_list} FROM {table}")).mappings().all()
            print(f"\n[{table}] {len(rows)} row(s)")

            for row in rows:
                updates: dict[str, str] = {}
                for col in columns:
                    value = row[col]
                    if value is None or value == "":
                        continue

                    plaintext = _decrypt_with(old_fernet, value)
                    if plaintext is None:
                        # Didn't decrypt with old key. Already rotated?
                        if _decrypt_with(new_fernet, value) is not None:
                            totals["already_new"] += 1
                        else:
                            totals["undecryptable"] += 1
                            logger.warning(
                                "reencrypt.undecryptable",
                                table=table, column=col, row_id=row["id"],
                            )
                        continue

                    if not value.startswith(_PREFIX):
                        totals["plaintext"] += 1  # legacy plaintext -> will be encrypted

                    updates[col] = _encrypt_with(new_fernet, plaintext)
                    totals["rotated"] += 1

                if updates and args.commit:
                    set_clause = ", ".join(f"{c} = :{c}" for c in updates)
                    session.execute(
                        text(f"UPDATE {table} SET {set_clause} WHERE id = :id"),
                        {**updates, "id": row["id"]},
                    )

        if args.commit:
            session.commit()
            print("\nCommitted.")
        else:
            print("\nDry run — no changes written. Re-run with --commit to apply.")

    print(
        f"\nSummary: rotated={totals['rotated']} "
        f"already_new={totals['already_new']} "
        f"legacy_plaintext={totals['plaintext']} "
        f"undecryptable={totals['undecryptable']}"
    )
    if totals["undecryptable"]:
        print("WARNING: some values decrypted with neither key — review the logs above.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
