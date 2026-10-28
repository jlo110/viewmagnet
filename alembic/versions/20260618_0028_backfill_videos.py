"""backfill_videos: rebuilt cross-sectional training set

Reconstructs a fresh labelled dataset from channels' upload history (the
historical scrape was lost). One row per backfilled video; label = views vs the
channel's own median (log space). Channel-grouped for leak-free CV splits.

Revision ID: 20260618_0028
Revises: 20260615_0027
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "20260618_0028"
down_revision = "20260615_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backfill_videos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("video_id", sa.String(length=20), nullable=False),
        sa.Column("channel_id", sa.String(length=30), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("is_short", sa.Boolean(), nullable=True),
        sa.Column("youtube_category_id", sa.String(length=8), nullable=True),
        sa.Column("default_audio_language", sa.String(length=10), nullable=True),
        sa.Column("view_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("like_count", sa.BigInteger(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("channel_median_views", sa.Float(), nullable=True),
        sa.Column("outlier", sa.Float(), nullable=True),
        sa.Column("log_outlier", sa.Float(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_backfill_videos_video_id", "backfill_videos", ["video_id"], unique=True)
    op.create_index("ix_backfill_videos_channel_id", "backfill_videos", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_backfill_videos_channel_id", table_name="backfill_videos")
    op.drop_index("ix_backfill_videos_video_id", table_name="backfill_videos")
    op.drop_table("backfill_videos")
