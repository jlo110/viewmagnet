"""Phase 1+4 security/spend/audit hardening

- ``users.usage_period_start`` for monthly quota window
- ``users.token_version`` for JWT revocation
- ``users.is_verified``, ``users.email_verification_token``
- ``users.totp_secret``, ``users.totp_enabled``
- ``llm_usage_records`` (per-call LLM cost ledger)
- ``audit_events`` (security audit log)
- Re-encrypt existing OAuth tokens via Fernet (best-effort)

Revision ID: 20260516_0003
Revises: 20260515_0002
Create Date: 2026-05-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260516_0003"
down_revision: Union[str, None] = "20260515_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    
    # ----- users: hardening columns -----
    if "usage_period_start" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "usage_period_start",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
    
    if "token_version" not in user_columns:
        op.add_column(
            "users",
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        )
    
    if "is_verified" not in user_columns:
        op.add_column(
            "users",
            sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    
    if "email_verification_token" not in user_columns:
        op.add_column(
            "users",
            sa.Column("email_verification_token", sa.String(128), nullable=True),
        )
        op.create_index(
            "ix_users_email_verification_token",
            "users",
            ["email_verification_token"],
        )
    
    if "totp_secret" not in user_columns:
        op.add_column("users", sa.Column("totp_secret", sa.String(64), nullable=True))
    
    if "totp_enabled" not in user_columns:
        op.add_column(
            "users",
            sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    
    # ----- llm_usage_records -----
    if "llm_usage_records" not in inspector.get_table_names():
        op.create_table(
            "llm_usage_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("model", sa.String(64), nullable=False),
            sa.Column("feature", sa.String(64), nullable=False),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("idx_llm_user_date", "llm_usage_records", ["user_id", "created_at"])
        op.create_index("idx_llm_feature_date", "llm_usage_records", ["feature", "created_at"])
        op.create_index("ix_llm_usage_records_created_at", "llm_usage_records", ["created_at"])
        op.create_index("ix_llm_usage_records_user_id", "llm_usage_records", ["user_id"])
        op.create_index("ix_llm_usage_records_feature", "llm_usage_records", ["feature"])
    
    # ----- audit_events -----
    if "audit_events" not in inspector.get_table_names():
        op.create_table(
            "audit_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.String(255), nullable=True),
            sa.Column("details", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("idx_audit_user_date", "audit_events", ["user_id", "created_at"])
        op.create_index("idx_audit_event_date", "audit_events", ["event_type", "created_at"])
        op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
        op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
        op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    
    # ----- referred_by_id: backfill missing FK -----
    fkeys = {fk["name"] for fk in inspector.get_foreign_keys("users") if fk.get("name")}
    if "fk_users_referred_by_id_users" not in fkeys:
        try:
            op.create_foreign_key(
                "fk_users_referred_by_id_users",
                "users",
                "users",
                ["referred_by_id"],
                ["id"],
                ondelete="SET NULL",
            )
        except Exception:
            # SQLite cannot ALTER TABLE ADD FOREIGN KEY -- skip on dev DBs.
            pass
    
    # ----- Re-encrypt existing OAuth tokens (best-effort) -----
    # Encrypts in place; rows already starting with "enc:" are left alone.
    try:
        from src.security.crypto import encrypt
        for table in ("youtube_connections", "connected_accounts"):
            if table not in inspector.get_table_names():
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            for col in ("access_token", "refresh_token", "client_secret"):
                if col not in cols:
                    continue
                rows = bind.execute(sa.text(f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL")).fetchall()
                for row_id, value in rows:
                    if value and not value.startswith("enc:"):
                        encrypted = encrypt(value)
                        bind.execute(
                            sa.text(f"UPDATE {table} SET {col} = :v WHERE id = :id"),
                            {"v": encrypted, "id": row_id},
                        )
    except Exception:
        # Encryption is best-effort during the migration; failures should not
        # block the schema upgrade. Operators can re-run a backfill script.
        pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    if "audit_events" in inspector.get_table_names():
        op.drop_table("audit_events")
    if "llm_usage_records" in inspector.get_table_names():
        op.drop_table("llm_usage_records")
    
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    for col in (
        "totp_enabled",
        "totp_secret",
        "email_verification_token",
        "is_verified",
        "token_version",
        "usage_period_start",
    ):
        if col in user_columns:
            try:
                op.drop_column("users", col)
            except Exception:
                pass
