"""Add personal_access_tokens table (MCP server v1 foundation).

The MCP server (`viewmagnet-mcp`) authenticates to the API on a user's
behalf without ever seeing their password. This migration adds the
``personal_access_tokens`` table that backs the
``POST /auth/tokens`` / ``GET /auth/tokens`` / ``DELETE /auth/tokens/{id}``
endpoints.

Token format presented to the user once:
    ``vm_pat_<8-char prefix>_<32-char secret>``

The prefix half is stored verbatim (indexed for fast lookup); the secret
half is sha256-hashed before storage. A leak of this table cannot be
replayed because the plaintext secret is never persisted.

Indexes:
- ``ix_personal_access_tokens_user_id`` — list-my-tokens query path
- ``ix_personal_access_tokens_prefix`` — auth lookup hot path
- ``ix_personal_access_tokens_token_hash`` (unique) — exact match check
- ``idx_pat_user_active`` (composite) — "active tokens for user X"

Revision ID: 20260526_0015
Revises: 20260523_0014
Create Date: 2026-05-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260526_0015"
down_revision: str | None = "20260523_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_access_tokens",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prefix", sa.String(length=20), nullable=False),
        sa.Column(
            "token_hash",
            sa.String(length=128),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "scopes",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_personal_access_tokens_user_id",
        "personal_access_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_personal_access_tokens_prefix",
        "personal_access_tokens",
        ["prefix"],
    )
    op.create_index(
        "ix_personal_access_tokens_token_hash",
        "personal_access_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "idx_pat_user_active",
        "personal_access_tokens",
        ["user_id", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_pat_user_active",
        table_name="personal_access_tokens",
    )
    op.drop_index(
        "ix_personal_access_tokens_token_hash",
        table_name="personal_access_tokens",
    )
    op.drop_index(
        "ix_personal_access_tokens_prefix",
        table_name="personal_access_tokens",
    )
    op.drop_index(
        "ix_personal_access_tokens_user_id",
        table_name="personal_access_tokens",
    )
    op.drop_table("personal_access_tokens")
