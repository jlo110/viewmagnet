"""create missing tables for velocity tracking, video features, niches

Revision ID: fdf2820c571c
Revises: 20260517_0004
Create Date: 2026-05-16 21:22:25.716585

Background
----------
The initial schema migration (``20260508_0000_001_initial_schema``) was
incomplete: several ORM models in ``src/database/models.py`` never had a
matching ``CREATE TABLE`` migration. That meant endpoints like
``POST /velocity/monitor`` started failing with::

    psycopg2.errors.UndefinedTable: relation "tracked_channels" does not exist

This migration creates the eight missing tables and their indexes/constraints.

What this migration deliberately does NOT do
--------------------------------------------
``alembic --autogenerate`` also flagged a large number of *non-additive*
schema differences on the existing tables (column type tweaks, dropped
``server_default``s, dropped columns like ``videos.view_count_24h``,
``channels.category``, ``channels.discovered_at``, etc.). Those changes
would destroy data and are not required to unbreak the API today, so they
were intentionally stripped out of this revision. If/when the team wants to
reconcile those columns with the ORM, do it in a follow-up migration after
a backup.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fdf2820c571c"
down_revision: Union[str, None] = "20260517_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # api_key_usage
    # ------------------------------------------------------------------
    op.create_table(
        "api_key_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key_index", sa.Integer(), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("units_used", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_index", "date", name="uq_key_date"),
    )
    op.create_index("idx_key_date", "api_key_usage", ["key_index", "date"], unique=False)

    # ------------------------------------------------------------------
    # discovery_progress
    # ------------------------------------------------------------------
    op.create_table(
        "discovery_progress",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("size_tier", sa.String(length=20), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("current_count", sa.Integer(), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category", "size_tier", name="uq_category_size"),
    )

    # ------------------------------------------------------------------
    # niches
    # ------------------------------------------------------------------
    op.create_table(
        "niches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("channel_count", sa.Integer(), nullable=False),
        sa.Column("avg_subscribers", sa.Float(), nullable=False),
        sa.Column("avg_views_per_video", sa.Float(), nullable=True),
        sa.Column("avg_engagement_rate", sa.Float(), nullable=True),
        sa.Column("avg_video_duration", sa.Float(), nullable=True),
        sa.Column("avg_upload_frequency", sa.Float(), nullable=True),
        sa.Column("avg_face_rate", sa.Float(), nullable=True),
        sa.Column("avg_text_in_thumbnail", sa.Float(), nullable=True),
        sa.Column("dominant_colors", sa.String(length=255), nullable=True),
        sa.Column("avg_title_length", sa.Float(), nullable=True),
        sa.Column("common_hook_types", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_niche_category", "niches", ["category"], unique=False)
    op.create_index(op.f("ix_niches_category"), "niches", ["category"], unique=False)

    # ------------------------------------------------------------------
    # tracked_channels
    # ------------------------------------------------------------------
    op.create_table(
        "tracked_channels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("channel_id", sa.String(length=24), nullable=False),
        sa.Column("recent_video_count", sa.Integer(), nullable=False),
        sa.Column("avg_upload_frequency_days", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_checked", sa.DateTime(), nullable=True),
        sa.Column("last_video_found", sa.DateTime(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_tracked_active", "tracked_channels", ["is_active"], unique=False)
    op.create_index(
        "idx_tracked_last_checked", "tracked_channels", ["last_checked"], unique=False
    )
    op.create_index(
        op.f("ix_tracked_channels_channel_id"),
        "tracked_channels",
        ["channel_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # tracked_videos
    # ------------------------------------------------------------------
    op.create_table(
        "tracked_videos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("channel_id", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("thumbnail_url", sa.String(length=500), nullable=True),
        sa.Column("tracking_started", sa.DateTime(), nullable=False),
        sa.Column("tracking_complete", sa.Boolean(), nullable=False),
        sa.Column("checkpoint_1h", sa.Boolean(), nullable=False),
        sa.Column("checkpoint_6h", sa.Boolean(), nullable=False),
        sa.Column("checkpoint_24h", sa.Boolean(), nullable=False),
        sa.Column("checkpoint_3d", sa.Boolean(), nullable=False),
        sa.Column("checkpoint_7d", sa.Boolean(), nullable=False),
        sa.Column("checkpoint_14d", sa.Boolean(), nullable=False),
        sa.Column("checkpoint_30d", sa.Boolean(), nullable=False),
        sa.Column("final_views", sa.BigInteger(), nullable=True),
        sa.Column("final_likes", sa.BigInteger(), nullable=True),
        sa.Column("final_comments", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_tracked_video_channel", "tracked_videos", ["channel_id"], unique=False
    )
    op.create_index(
        "idx_tracked_video_complete",
        "tracked_videos",
        ["tracking_complete"],
        unique=False,
    )
    op.create_index(
        "idx_tracked_video_published",
        "tracked_videos",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tracked_videos_channel_id"),
        "tracked_videos",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tracked_videos_video_id"),
        "tracked_videos",
        ["video_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # video_content_analysis
    # ------------------------------------------------------------------
    op.create_table(
        "video_content_analysis",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("r2_video_key", sa.String(length=255), nullable=True),
        sa.Column("r2_audio_key", sa.String(length=255), nullable=True),
        sa.Column("hook_face_appears_seconds", sa.Float(), nullable=True),
        sa.Column("hook_text_appears_seconds", sa.Float(), nullable=True),
        sa.Column("hook_scene_changes_count", sa.Integer(), nullable=True),
        sa.Column("hook_avg_motion", sa.Float(), nullable=True),
        sa.Column("hook_words_count", sa.Integer(), nullable=True),
        sa.Column("total_scene_changes", sa.Integer(), nullable=True),
        sa.Column("avg_scene_duration", sa.Float(), nullable=True),
        sa.Column("scene_change_variance", sa.Float(), nullable=True),
        sa.Column("avg_brightness", sa.Float(), nullable=True),
        sa.Column("brightness_variance", sa.Float(), nullable=True),
        sa.Column("avg_sharpness", sa.Float(), nullable=True),
        sa.Column("face_screen_time_ratio", sa.Float(), nullable=True),
        sa.Column("face_size_consistency", sa.Float(), nullable=True),
        sa.Column("audio_energy_mean", sa.Float(), nullable=True),
        sa.Column("audio_energy_variance", sa.Float(), nullable=True),
        sa.Column("audio_tempo", sa.Float(), nullable=True),
        sa.Column("loudness_range", sa.Float(), nullable=True),
        sa.Column("energy_ramp_up", sa.Float(), nullable=True),
        sa.Column("has_music_intro", sa.Boolean(), nullable=True),
        sa.Column("intro_duration_seconds", sa.Float(), nullable=True),
        sa.Column("transcript_word_count", sa.Integer(), nullable=True),
        sa.Column("words_per_minute", sa.Float(), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=True),
        sa.Column("call_to_action_count", sa.Integer(), nullable=True),
        sa.Column("transcript_sentiment", sa.Float(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("video_duration_analyzed", sa.Float(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(), nullable=False),
        sa.Column("extraction_success", sa.Boolean(), nullable=False),
        sa.Column("extraction_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_content_success",
        "video_content_analysis",
        ["extraction_success"],
        unique=False,
    )
    op.create_index(
        "idx_content_video", "video_content_analysis", ["video_id"], unique=False
    )
    op.create_index(
        op.f("ix_video_content_analysis_video_id"),
        "video_content_analysis",
        ["video_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # video_features
    # ------------------------------------------------------------------
    op.create_table(
        "video_features",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("face_count", sa.Integer(), nullable=True),
        sa.Column("face_area_ratio", sa.Float(), nullable=True),
        sa.Column("has_face", sa.Boolean(), nullable=True),
        sa.Column("has_text", sa.Boolean(), nullable=True),
        sa.Column("text_word_count", sa.Integer(), nullable=True),
        sa.Column("text_area_ratio", sa.Float(), nullable=True),
        sa.Column("text_readability", sa.Float(), nullable=True),
        sa.Column("dominant_color_1", sa.String(length=7), nullable=True),
        sa.Column("dominant_color_2", sa.String(length=7), nullable=True),
        sa.Column("dominant_color_3", sa.String(length=7), nullable=True),
        sa.Column("brightness", sa.Float(), nullable=True),
        sa.Column("saturation", sa.Float(), nullable=True),
        sa.Column("contrast", sa.Float(), nullable=True),
        sa.Column("visual_complexity", sa.Float(), nullable=True),
        sa.Column("edge_density", sa.Float(), nullable=True),
        sa.Column("composition_score", sa.Float(), nullable=True),
        sa.Column("rule_of_thirds_score", sa.Float(), nullable=True),
        sa.Column("focal_point_x", sa.Float(), nullable=True),
        sa.Column("focal_point_y", sa.Float(), nullable=True),
        sa.Column("focal_point_quadrant", sa.String(length=20), nullable=True),
        sa.Column("on_power_point", sa.Boolean(), nullable=True),
        sa.Column("channel_momentum_at_upload", sa.Float(), nullable=True),
        sa.Column("channel_engagement_trend_at_upload", sa.Float(), nullable=True),
        sa.Column("channel_hit_rate_at_upload", sa.Float(), nullable=True),
        sa.Column("channel_recent_avg_ratio_at_upload", sa.Float(), nullable=True),
        sa.Column("face_emotion_primary", sa.String(length=20), nullable=True),
        sa.Column("face_emotion_intensity", sa.Float(), nullable=True),
        sa.Column("title_char_length", sa.Integer(), nullable=True),
        sa.Column("title_word_count", sa.Integer(), nullable=True),
        sa.Column("title_has_number", sa.Boolean(), nullable=True),
        sa.Column("title_number_position", sa.String(length=10), nullable=True),
        sa.Column("title_has_question", sa.Boolean(), nullable=True),
        sa.Column("title_has_exclamation", sa.Boolean(), nullable=True),
        sa.Column("title_has_brackets", sa.Boolean(), nullable=True),
        sa.Column("title_caps_ratio", sa.Float(), nullable=True),
        sa.Column("title_hook_type", sa.String(length=30), nullable=True),
        sa.Column("title_emotional_score", sa.Float(), nullable=True),
        sa.Column("title_sentiment", sa.Float(), nullable=True),
        sa.Column("title_trending_score", sa.Float(), nullable=True),
        sa.Column("title_specificity_score", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("duration_category_ratio", sa.Float(), nullable=True),
        sa.Column("posting_day_of_week", sa.Integer(), nullable=True),
        sa.Column("posting_hour", sa.Integer(), nullable=True),
        sa.Column("tags_count", sa.Integer(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(), nullable=False),
        sa.Column("thumbnail_processed", sa.Boolean(), nullable=False),
        sa.Column("title_processed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_features_hook", "video_features", ["title_hook_type"], unique=False
    )
    op.create_index("idx_features_video", "video_features", ["video_id"], unique=False)
    op.create_index(
        op.f("ix_video_features_video_id"), "video_features", ["video_id"], unique=True
    )

    # ------------------------------------------------------------------
    # video_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        "video_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("checkpoint", sa.String(length=10), nullable=False),
        sa.Column("hours_since_publish", sa.Float(), nullable=False),
        sa.Column("view_count", sa.BigInteger(), nullable=False),
        sa.Column("like_count", sa.BigInteger(), nullable=False),
        sa.Column("comment_count", sa.Integer(), nullable=False),
        sa.Column("views_per_hour", sa.Float(), nullable=True),
        sa.Column("engagement_rate", sa.Float(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id", "checkpoint", name="uq_video_checkpoint"),
    )
    op.create_index(
        "idx_snapshot_video_checkpoint",
        "video_snapshots",
        ["video_id", "checkpoint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_video_snapshots_video_id"),
        "video_snapshots",
        ["video_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_video_snapshots_video_id"), table_name="video_snapshots")
    op.drop_index("idx_snapshot_video_checkpoint", table_name="video_snapshots")
    op.drop_table("video_snapshots")

    op.drop_index(op.f("ix_video_features_video_id"), table_name="video_features")
    op.drop_index("idx_features_video", table_name="video_features")
    op.drop_index("idx_features_hook", table_name="video_features")
    op.drop_table("video_features")

    op.drop_index(
        op.f("ix_video_content_analysis_video_id"),
        table_name="video_content_analysis",
    )
    op.drop_index("idx_content_video", table_name="video_content_analysis")
    op.drop_index("idx_content_success", table_name="video_content_analysis")
    op.drop_table("video_content_analysis")

    op.drop_index(op.f("ix_tracked_videos_video_id"), table_name="tracked_videos")
    op.drop_index(op.f("ix_tracked_videos_channel_id"), table_name="tracked_videos")
    op.drop_index("idx_tracked_video_published", table_name="tracked_videos")
    op.drop_index("idx_tracked_video_complete", table_name="tracked_videos")
    op.drop_index("idx_tracked_video_channel", table_name="tracked_videos")
    op.drop_table("tracked_videos")

    op.drop_index(op.f("ix_tracked_channels_channel_id"), table_name="tracked_channels")
    op.drop_index("idx_tracked_last_checked", table_name="tracked_channels")
    op.drop_index("idx_tracked_active", table_name="tracked_channels")
    op.drop_table("tracked_channels")

    op.drop_index(op.f("ix_niches_category"), table_name="niches")
    op.drop_index("idx_niche_category", table_name="niches")
    op.drop_table("niches")

    op.drop_table("discovery_progress")

    op.drop_index("idx_key_date", table_name="api_key_usage")
    op.drop_table("api_key_usage")
