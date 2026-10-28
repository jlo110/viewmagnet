"""create websub_subscriptions (plan 7.5 — push discovery)

Lease state per tracked channel for YouTube WebSub push notifications —
replaces ~99.5% of YouTube API quota (polling discovery) with zero-quota,
minutes-latency pushes.

Revision ID: 20260612_0025
Revises: 20260612_0024
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = "20260612_0025"
down_revision = "20260612_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "websub_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.String(length=24), nullable=False, unique=True),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="pending"),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_subscribed_at", sa.DateTime(), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(), nullable=True),
        sa.Column("notification_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_websub_subscriptions_channel_id", "websub_subscriptions", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_websub_subscriptions_channel_id", table_name="websub_subscriptions")
    op.drop_table("websub_subscriptions")
