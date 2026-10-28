"""widen video_snapshots: description, tags, live flag, audio language (Phase 8.5)

These come free in the videos.list call the collector already makes per
checkpoint; we were fetching and discarding them. description -> chapters/
links/hashtags + edit detection; tags -> topic-saturation signal (8.2);
live/premiere videos follow different view curves and silently contaminate
training when unlabeled.

Revision ID: 20260612_0021
Revises: 20260610_0020
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = "20260612_0021"
down_revision = "20260610_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("video_snapshots", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("video_snapshots", sa.Column("tags", sa.Text(), nullable=True))
    op.add_column(
        "video_snapshots",
        sa.Column("live_broadcast_content", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "video_snapshots",
        sa.Column("default_audio_language", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("video_snapshots", "default_audio_language")
    op.drop_column("video_snapshots", "live_broadcast_content")
    op.drop_column("video_snapshots", "tags")
    op.drop_column("video_snapshots", "description")
