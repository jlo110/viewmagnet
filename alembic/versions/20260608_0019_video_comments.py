"""create video_comments (Phase 7.2 — top comments @ 24h)

Stores a sample of top comments captured ~24h after a tracked video publishes,
for comment intelligence (viewer intent / FAQ / next-video ideas).

Revision ID: 20260608_0019
Revises: 20260608_0018
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "20260608_0019"
down_revision = "20260608_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("comment_id", sa.String(length=64), nullable=False),
        sa.Column("author_name", sa.String(length=255), nullable=True),
        sa.Column("author_channel_id", sa.String(length=64), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("video_id", "comment_id", name="uq_video_comment"),
    )
    op.create_index("ix_video_comments_video_id", "video_comments", ["video_id"])


def downgrade() -> None:
    op.drop_index("ix_video_comments_video_id", table_name="video_comments")
    op.drop_table("video_comments")
