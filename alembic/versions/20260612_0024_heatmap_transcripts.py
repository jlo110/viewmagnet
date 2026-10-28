"""add opening transcript to video_heatmaps (8.6 follow-up)

The yt-dlp probe that fetches the Most-Replayed heatmap also exposes caption
tracks (manual subs + auto-captions, zero quota). Store the opening ~60s
transcript alongside — fuels the hook analyzer, breakout explainers, and
transcript-level topic clustering.

Revision ID: 20260612_0024
Revises: 20260612_0023
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = "20260612_0024"
down_revision = "20260612_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("video_heatmaps", sa.Column("opening_transcript", sa.Text(), nullable=True))
    op.add_column("video_heatmaps", sa.Column("transcript_lang", sa.String(length=16), nullable=True))
    op.add_column("video_heatmaps", sa.Column("transcript_source", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("video_heatmaps", "transcript_source")
    op.drop_column("video_heatmaps", "transcript_lang")
    op.drop_column("video_heatmaps", "opening_transcript")
