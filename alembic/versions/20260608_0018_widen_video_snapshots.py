"""widen video_snapshots with metadata + engagement ratios (Phase 7.1)

Adds per-checkpoint metadata (title, thumbnail_url, duration_seconds,
youtube_category_id, tag_count, is_short) and normalized engagement
ratios (like_view_ratio, comment_view_ratio) so the velocity collector
captures the title/thumbnail-swap natural experiments and Shorts-vs-
long-form signal it was previously discarding.

All columns are nullable — existing rows keep NULL, new snapshots fill them.

Revision ID: 20260608_0018
Revises: 20260531_0017
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "20260608_0018"
down_revision = "20260531_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("video_snapshots", sa.Column("like_view_ratio", sa.Float(), nullable=True))
    op.add_column("video_snapshots", sa.Column("comment_view_ratio", sa.Float(), nullable=True))
    op.add_column("video_snapshots", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("video_snapshots", sa.Column("thumbnail_url", sa.String(length=500), nullable=True))
    op.add_column("video_snapshots", sa.Column("duration_seconds", sa.Integer(), nullable=True))
    op.add_column("video_snapshots", sa.Column("youtube_category_id", sa.String(length=10), nullable=True))
    op.add_column("video_snapshots", sa.Column("tag_count", sa.Integer(), nullable=True))
    op.add_column("video_snapshots", sa.Column("is_short", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("video_snapshots", "is_short")
    op.drop_column("video_snapshots", "tag_count")
    op.drop_column("video_snapshots", "youtube_category_id")
    op.drop_column("video_snapshots", "duration_seconds")
    op.drop_column("video_snapshots", "thumbnail_url")
    op.drop_column("video_snapshots", "title")
    op.drop_column("video_snapshots", "comment_view_ratio")
    op.drop_column("video_snapshots", "like_view_ratio")
