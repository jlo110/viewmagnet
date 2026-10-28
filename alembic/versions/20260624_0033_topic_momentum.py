"""topic_momentum: per-topic breakout-density time series (Phase 2.1)

Revision ID: 20260624_0033
Revises: 20260624_0032
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = "20260624_0033"
down_revision = "20260624_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_momentum",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("window_hours", sa.Float(), nullable=False, server_default="48.0"),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("topic_size", sa.Integer(), nullable=False),
        sa.Column("breakout_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("breakout_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_views", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("channel_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trend", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("prev_breakout_rate", sa.Float(), nullable=True),
        sa.Column("example_titles", sa.Text(), nullable=True),
        sa.Column("video_ids", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_topic_momentum_computed_at", "topic_momentum", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_topic_momentum_computed_at", table_name="topic_momentum")
    op.drop_table("topic_momentum")
