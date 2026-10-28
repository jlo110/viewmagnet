"""reconcile channels/videos/channel_snapshots/youtube_connections with ORM

Revision ID: a1c2d3e4f506
Revises: fdf2820c571c
Create Date: 2026-05-17 01:30:00.000000

Background
----------
The previous migrations created the *missing* tables but did not reconcile the
*existing* tables (channels, videos, channel_snapshots, youtube_connections)
with the current SQLAlchemy models. That mismatch caused live errors like::

    psycopg2.errors.UndefinedColumn: column channels.primary_category does not exist

All four tables were verified to be empty at the time this migration was
authored (only ``users`` and ``user_video_analyses`` had rows), so dropping the
legacy columns is safe — no backfill needed.

What this migration does
------------------------
* Adds the columns the ORM expects (``channels.primary_category``,
  ``channels.size_tier``, ``videos.performance_ratio``, etc.).
* Drops obsolete columns (``channels.category``, ``videos.view_count_24h``,
  ``youtube_connections.created_at``, ``channel_snapshots.snapshot_date``, …).
* Updates indexes/unique constraints so they match what the models declare
  (e.g. ``ix_channels_channel_id`` becomes unique).
* Adjusts column types where the ORM disagrees with the existing schema
  (``youtube_connections.client_secret`` → ``String(512)``,
  ``videos.comment_count`` → ``Integer``).

What this migration deliberately does NOT do
--------------------------------------------
* ``server_default`` drift (e.g. ``users.created_at DEFAULT now()``). These
  defaults exist in the DB but aren't declared on the ORM column. Removing
  them would be cosmetic and slightly risky, so they're left alone.
* No touching ``users`` or ``user_video_analyses`` — those tables hold real
  rows and aren't causing errors.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1c2d3e4f506"
down_revision: Union[str, None] = "fdf2820c571c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # channels — add new columns, drop legacy columns, fix indexes
    # ------------------------------------------------------------------
    op.add_column(
        "channels", sa.Column("primary_category", sa.String(length=50), nullable=False)
    )
    op.add_column(
        "channels",
        sa.Column("youtube_category_id", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "channels", sa.Column("size_tier", sa.String(length=20), nullable=False)
    )
    op.add_column(
        "channels", sa.Column("avg_views_per_video", sa.Float(), nullable=True)
    )
    op.add_column("channels", sa.Column("engagement_rate", sa.Float(), nullable=True))
    op.add_column(
        "channels", sa.Column("upload_frequency_days", sa.Float(), nullable=True)
    )
    op.add_column(
        "channels", sa.Column("default_language", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "channels",
        sa.Column("discovery_source", sa.String(length=50), nullable=False),
    )
    op.add_column(
        "channels", sa.Column("discovery_query", sa.String(length=255), nullable=True)
    )
    op.add_column("channels", sa.Column("niche_id", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("collected_at", sa.DateTime(), nullable=False))
    op.add_column(
        "channels", sa.Column("videos_collected", sa.Boolean(), nullable=False)
    )
    op.alter_column("channels", "last_updated", existing_type=postgresql.TIMESTAMP(), nullable=False)

    # Drop legacy unique constraint + index (replaced with unique index below).
    op.drop_constraint(op.f("channels_channel_id_key"), "channels", type_="unique")
    op.drop_index(op.f("ix_channels_category"), table_name="channels")
    op.drop_index(op.f("ix_channels_subscriber_count"), table_name="channels")
    op.drop_index(op.f("ix_channels_channel_id"), table_name="channels")

    op.create_index(op.f("ix_channels_channel_id"), "channels", ["channel_id"], unique=True)
    op.create_index("idx_active_category", "channels", ["is_active", "primary_category"], unique=False)
    op.create_index("idx_category_size", "channels", ["primary_category", "size_tier"], unique=False)
    op.create_index("idx_subscriber_count", "channels", ["subscriber_count"], unique=False)
    op.create_index(op.f("ix_channels_niche_id"), "channels", ["niche_id"], unique=False)
    op.create_index(op.f("ix_channels_primary_category"), "channels", ["primary_category"], unique=False)
    op.create_index(op.f("ix_channels_size_tier"), "channels", ["size_tier"], unique=False)

    op.drop_column("channels", "needs_refresh")
    op.drop_column("channels", "discovered_at")
    op.drop_column("channels", "category")

    # ------------------------------------------------------------------
    # channel_snapshots — rename view_count→total_views, snapshot_date→snapshot_at
    # ------------------------------------------------------------------
    op.add_column(
        "channel_snapshots", sa.Column("total_views", sa.BigInteger(), nullable=False)
    )
    op.add_column(
        "channel_snapshots", sa.Column("snapshot_at", sa.DateTime(), nullable=False)
    )
    op.alter_column("channel_snapshots", "video_count", existing_type=sa.INTEGER(), nullable=False)
    op.drop_index(op.f("ix_channel_snapshots_snapshot_date"), table_name="channel_snapshots")
    op.create_index(
        "idx_channel_snapshot_time",
        "channel_snapshots",
        ["channel_id", "snapshot_at"],
        unique=False,
    )
    op.drop_column("channel_snapshots", "view_count")
    op.drop_column("channel_snapshots", "snapshot_date")

    # ------------------------------------------------------------------
    # videos — add analytics columns, drop legacy view_count_* / category_id
    # ------------------------------------------------------------------
    op.add_column(
        "videos", sa.Column("youtube_category_id", sa.String(length=10), nullable=True)
    )
    op.add_column("videos", sa.Column("performance_ratio", sa.Float(), nullable=True))
    op.add_column("videos", sa.Column("engagement_rate", sa.Float(), nullable=True))
    op.add_column(
        "videos", sa.Column("age_adjusted_performance", sa.Float(), nullable=True)
    )
    op.add_column(
        "videos", sa.Column("features_extracted", sa.Boolean(), nullable=False)
    )
    op.alter_column("videos", "duration_seconds", existing_type=sa.INTEGER(), nullable=False)
    op.alter_column("videos", "published_at", existing_type=postgresql.TIMESTAMP(), nullable=False)
    op.alter_column(
        "videos",
        "comment_count",
        existing_type=sa.BIGINT(),
        type_=sa.Integer(),
        existing_nullable=False,
    )

    op.drop_constraint(op.f("videos_video_id_key"), "videos", type_="unique")
    op.drop_index(op.f("ix_videos_published_at"), table_name="videos")
    op.drop_index(op.f("ix_videos_video_id"), table_name="videos")
    op.create_index(op.f("ix_videos_video_id"), "videos", ["video_id"], unique=True)
    op.create_index("idx_video_channel", "videos", ["channel_id"], unique=False)
    op.create_index("idx_video_performance", "videos", ["performance_ratio"], unique=False)
    op.create_index("idx_video_published", "videos", ["published_at"], unique=False)
    op.create_index("idx_video_views", "videos", ["view_count"], unique=False)

    op.drop_column("videos", "view_count_24h")
    op.drop_column("videos", "view_count_7d")
    op.drop_column("videos", "category_id")
    op.drop_column("videos", "view_count_30d")
    op.drop_column("videos", "view_count_48h")
    op.drop_column("videos", "last_velocity_update")

    # ------------------------------------------------------------------
    # youtube_connections — widen client_secret, drop spare created_at
    # ------------------------------------------------------------------
    op.alter_column(
        "youtube_connections",
        "client_secret",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.String(length=512),
        existing_nullable=False,
    )
    op.drop_column("youtube_connections", "created_at")


def downgrade() -> None:
    # ------------------------------------------------------------------
    # youtube_connections
    # ------------------------------------------------------------------
    op.add_column(
        "youtube_connections",
        sa.Column("created_at", postgresql.TIMESTAMP(), nullable=True),
    )
    op.alter_column(
        "youtube_connections",
        "client_secret",
        existing_type=sa.String(length=512),
        type_=sa.VARCHAR(length=255),
        existing_nullable=False,
    )

    # ------------------------------------------------------------------
    # videos
    # ------------------------------------------------------------------
    op.add_column("videos", sa.Column("last_velocity_update", postgresql.TIMESTAMP(), nullable=True))
    op.add_column("videos", sa.Column("view_count_48h", sa.BIGINT(), nullable=True))
    op.add_column("videos", sa.Column("view_count_30d", sa.BIGINT(), nullable=True))
    op.add_column("videos", sa.Column("category_id", sa.VARCHAR(length=10), nullable=True))
    op.add_column("videos", sa.Column("view_count_7d", sa.BIGINT(), nullable=True))
    op.add_column("videos", sa.Column("view_count_24h", sa.BIGINT(), nullable=True))

    op.drop_index("idx_video_views", table_name="videos")
    op.drop_index("idx_video_published", table_name="videos")
    op.drop_index("idx_video_performance", table_name="videos")
    op.drop_index("idx_video_channel", table_name="videos")
    op.drop_index(op.f("ix_videos_video_id"), table_name="videos")
    op.create_index(op.f("ix_videos_video_id"), "videos", ["video_id"], unique=False)
    op.create_unique_constraint(op.f("videos_video_id_key"), "videos", ["video_id"])
    op.create_index(op.f("ix_videos_published_at"), "videos", ["published_at"], unique=False)

    op.alter_column(
        "videos",
        "comment_count",
        existing_type=sa.Integer(),
        type_=sa.BIGINT(),
        existing_nullable=False,
    )
    op.alter_column("videos", "published_at", existing_type=postgresql.TIMESTAMP(), nullable=True)
    op.alter_column("videos", "duration_seconds", existing_type=sa.INTEGER(), nullable=True)

    op.drop_column("videos", "features_extracted")
    op.drop_column("videos", "age_adjusted_performance")
    op.drop_column("videos", "engagement_rate")
    op.drop_column("videos", "performance_ratio")
    op.drop_column("videos", "youtube_category_id")

    # ------------------------------------------------------------------
    # channel_snapshots
    # ------------------------------------------------------------------
    op.add_column(
        "channel_snapshots",
        sa.Column("snapshot_date", postgresql.TIMESTAMP(), nullable=False),
    )
    op.add_column("channel_snapshots", sa.Column("view_count", sa.BIGINT(), nullable=True))
    op.drop_index("idx_channel_snapshot_time", table_name="channel_snapshots")
    op.create_index(
        op.f("ix_channel_snapshots_snapshot_date"),
        "channel_snapshots",
        ["snapshot_date"],
        unique=False,
    )
    op.alter_column("channel_snapshots", "video_count", existing_type=sa.INTEGER(), nullable=True)
    op.drop_column("channel_snapshots", "snapshot_at")
    op.drop_column("channel_snapshots", "total_views")

    # ------------------------------------------------------------------
    # channels
    # ------------------------------------------------------------------
    op.add_column(
        "channels", sa.Column("category", sa.VARCHAR(length=50), nullable=True)
    )
    op.add_column(
        "channels",
        sa.Column("discovered_at", postgresql.TIMESTAMP(), nullable=False),
    )
    op.add_column("channels", sa.Column("needs_refresh", sa.BOOLEAN(), nullable=False))

    op.drop_index(op.f("ix_channels_size_tier"), table_name="channels")
    op.drop_index(op.f("ix_channels_primary_category"), table_name="channels")
    op.drop_index(op.f("ix_channels_niche_id"), table_name="channels")
    op.drop_index("idx_subscriber_count", table_name="channels")
    op.drop_index("idx_category_size", table_name="channels")
    op.drop_index("idx_active_category", table_name="channels")
    op.drop_index(op.f("ix_channels_channel_id"), table_name="channels")
    op.create_index(op.f("ix_channels_channel_id"), "channels", ["channel_id"], unique=False)
    op.create_index(op.f("ix_channels_subscriber_count"), "channels", ["subscriber_count"], unique=False)
    op.create_index(op.f("ix_channels_category"), "channels", ["category"], unique=False)
    op.create_unique_constraint(op.f("channels_channel_id_key"), "channels", ["channel_id"])

    op.alter_column("channels", "last_updated", existing_type=postgresql.TIMESTAMP(), nullable=True)
    op.drop_column("channels", "videos_collected")
    op.drop_column("channels", "collected_at")
    op.drop_column("channels", "niche_id")
    op.drop_column("channels", "discovery_query")
    op.drop_column("channels", "discovery_source")
    op.drop_column("channels", "default_language")
    op.drop_column("channels", "upload_frequency_days")
    op.drop_column("channels", "engagement_rate")
    op.drop_column("channels", "avg_views_per_video")
    op.drop_column("channels", "size_tier")
    op.drop_column("channels", "youtube_category_id")
    op.drop_column("channels", "primary_category")
