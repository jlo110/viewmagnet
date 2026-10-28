"""watchlist_channels: per-user watched channels (competitive breakout intel)

Revision ID: 20260621_0029
Revises: 20260618_0028
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "20260621_0029"
down_revision = "20260618_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.String(length=24), nullable=False),
        sa.Column("channel_title", sa.String(length=200), nullable=True),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "channel_id", name="uq_watchlist_user_channel"),
    )
    op.create_index("ix_watchlist_channels_user_id", "watchlist_channels", ["user_id"])
    op.create_index("ix_watchlist_channels_channel_id", "watchlist_channels", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_channels_channel_id", table_name="watchlist_channels")
    op.drop_index("ix_watchlist_channels_user_id", table_name="watchlist_channels")
    op.drop_table("watchlist_channels")
