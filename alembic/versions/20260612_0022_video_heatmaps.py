"""create video_heatmaps (Phase 8.1 — Most Replayed retention proxy)

Public per-video replay heatmaps (~100 normalized points) captured once a
video is old enough for YouTube to render them (~2 weeks). has_heatmap=False
rows record exhausted probes so videos aren't re-fetched forever.

Revision ID: 20260612_0022
Revises: 20260612_0021
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = "20260612_0022"
down_revision = "20260612_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_heatmaps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("video_id", sa.String(length=11), nullable=False, unique=True),
        sa.Column("has_heatmap", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("points", sa.Text(), nullable=True),
        sa.Column("n_points", sa.Integer(), nullable=True),
        sa.Column("video_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("captured_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_video_heatmaps_video_id", "video_heatmaps", ["video_id"])


def downgrade() -> None:
    op.drop_index("ix_video_heatmaps_video_id", table_name="video_heatmaps")
    op.drop_table("video_heatmaps")
