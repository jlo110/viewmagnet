"""owner_video_analytics: real owner CTR + retention (Phase 3.2 display half)

Revision ID: 20260625_0035
Revises: 20260624_0034
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "20260625_0035"
down_revision = "20260624_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "owner_video_analytics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.String(length=24), nullable=False),
        sa.Column("video_id", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("views", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("avg_view_percentage", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("avg_view_duration_seconds", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("retention_curve", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "video_id", name="uq_owner_video"),
    )
    op.create_index("ix_owner_video_analytics_user_id", "owner_video_analytics", ["user_id"])
    op.create_index("ix_owner_video_analytics_channel_id", "owner_video_analytics", ["channel_id"])
    op.create_index("ix_owner_video_analytics_video_id", "owner_video_analytics", ["video_id"])


def downgrade() -> None:
    op.drop_index("ix_owner_video_analytics_video_id", table_name="owner_video_analytics")
    op.drop_index("ix_owner_video_analytics_channel_id", table_name="owner_video_analytics")
    op.drop_index("ix_owner_video_analytics_user_id", table_name="owner_video_analytics")
    op.drop_table("owner_video_analytics")
