"""Billing (Stripe subscription) + password-reset columns and payment_history.

Adds the columns the live billing flow + password-reset flow need, plus the
``payment_history`` table that Stripe webhook handlers write to.

New ``users`` columns:
- ``stripe_subscription_id`` — the active Stripe subscription id (indexed for
  webhook lookup by subscription).
- ``subscription_status`` — mirror of the Stripe subscription status
  (active / past_due / canceled / ...).
- ``password_reset_token`` — single-use token emailed for password reset.
- ``password_reset_expires`` — expiry for the reset token.

New table:
- ``payment_history`` — one row per Stripe invoice (succeeded/failed), used by
  the billing dashboard.

Every step is guarded against the column/table already existing because this
codebase has a history of ``create_all()`` drift — the migration must be
safe to run against a database that was partially bootstrapped outside
Alembic.

Revision ID: 20260530_0016
Revises: 20260526_0015
Create Date: 2026-05-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260530_0016"
down_revision: str | None = "20260526_0015"
branch_labels = None
depends_on = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def _existing_indexes(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    return table in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    user_cols = _existing_columns("users")

    if "stripe_subscription_id" not in user_cols:
        op.add_column(
            "users",
            sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        )
    if "subscription_status" not in user_cols:
        op.add_column(
            "users",
            sa.Column("subscription_status", sa.String(length=50), nullable=True),
        )
    if "password_reset_token" not in user_cols:
        op.add_column(
            "users",
            sa.Column("password_reset_token", sa.String(length=128), nullable=True),
        )
    if "password_reset_expires" not in user_cols:
        op.add_column(
            "users",
            sa.Column("password_reset_expires", sa.DateTime(), nullable=True),
        )

    user_indexes = _existing_indexes("users")
    if "ix_users_stripe_subscription_id" not in user_indexes:
        op.create_index(
            "ix_users_stripe_subscription_id",
            "users",
            ["stripe_subscription_id"],
            unique=False,
        )
    if "ix_users_password_reset_token" not in user_indexes:
        op.create_index(
            "ix_users_password_reset_token",
            "users",
            ["password_reset_token"],
            unique=False,
        )

    if not _table_exists("payment_history"):
        op.create_table(
            "payment_history",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("stripe_payment_id", sa.String(length=255), nullable=True),
            sa.Column("stripe_invoice_id", sa.String(length=255), nullable=True),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("plan", sa.String(length=50), nullable=True),
            sa.Column("period_start", sa.DateTime(), nullable=True),
            sa.Column("period_end", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_payment_history_user_id", "payment_history", ["user_id"], unique=False
        )


def downgrade() -> None:
    if _table_exists("payment_history"):
        op.drop_index("ix_payment_history_user_id", table_name="payment_history")
        op.drop_table("payment_history")

    user_indexes = _existing_indexes("users")
    if "ix_users_password_reset_token" in user_indexes:
        op.drop_index("ix_users_password_reset_token", table_name="users")
    if "ix_users_stripe_subscription_id" in user_indexes:
        op.drop_index("ix_users_stripe_subscription_id", table_name="users")

    user_cols = _existing_columns("users")
    for col in (
        "password_reset_expires",
        "password_reset_token",
        "subscription_status",
        "stripe_subscription_id",
    ):
        if col in user_cols:
            op.drop_column("users", col)
