"""create topic_clusters (Phase 8.2 — topic-saturation index)

Topic clusters of recent tracked uploads (title embeddings, greedy cosine
clustering), one batch per computed_at. Cluster size/channel_count = the
saturation signal; batch history = topic velocity.

Revision ID: 20260612_0023
Revises: 20260612_0022
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = "20260612_0023"
down_revision = "20260612_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_clusters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("window_hours", sa.Float(), nullable=False, server_default="48"),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("total_views", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("channel_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("example_titles", sa.Text(), nullable=True),
        sa.Column("video_ids", sa.Text(), nullable=True),
    )
    op.create_index("ix_topic_clusters_computed_at", "topic_clusters", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_topic_clusters_computed_at", table_name="topic_clusters")
    op.drop_table("topic_clusters")
