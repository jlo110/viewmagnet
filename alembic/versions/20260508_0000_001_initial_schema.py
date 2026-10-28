"""Initial schema migration

Revision ID: 20260508_0000_001
Revises: 
Create Date: 2026-05-08

This is the initial migration that captures the existing database schema.
It should only be run on new databases. Existing databases should have
this migration marked as applied without running it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '20260508_0000_001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('avatar_url', sa.String(length=500), nullable=True),
        sa.Column('plan', sa.String(length=50), nullable=False, server_default='free'),
        sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
        sa.Column('subscription_expires', sa.DateTime(), nullable=True),
        sa.Column('analyses_today', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('analyses_this_month', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_analysis_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_login', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index('ix_users_email', 'users', ['email'])

    # YouTube connections table
    op.create_table(
        'youtube_connections',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('channel_id', sa.String(length=24), nullable=False),
        sa.Column('channel_name', sa.String(length=255), nullable=False),
        sa.Column('subscriber_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('access_token', sa.Text(), nullable=False),
        sa.Column('refresh_token', sa.Text(), nullable=False),
        sa.Column('token_uri', sa.String(length=500), nullable=False),
        sa.Column('client_id', sa.String(length=255), nullable=False),
        sa.Column('client_secret', sa.String(length=255), nullable=False),
        sa.Column('scopes', sa.Text(), nullable=False),
        sa.Column('token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_synced', sa.DateTime(), nullable=True),
        sa.Column('connected_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'channel_id', name='uq_user_channel')
    )
    op.create_index('ix_youtube_connections_user_id', 'youtube_connections', ['user_id'])
    op.create_index('ix_youtube_connections_channel_id', 'youtube_connections', ['channel_id'])

    # User video analyses table
    op.create_table(
        'user_video_analyses',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('video_id', sa.String(length=11), nullable=False),
        sa.Column('video_url', sa.String(length=500), nullable=True),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('prediction_score', sa.Float(), nullable=True),
        sa.Column('prediction_tier', sa.String(length=20), nullable=True),
        sa.Column('title_score', sa.Float(), nullable=True),
        sa.Column('thumbnail_score', sa.Float(), nullable=True),
        sa.Column('shap_explanations', sa.Text(), nullable=True),
        sa.Column('recommendations', sa.Text(), nullable=True),
        sa.Column('analyzed_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_user_video_analyses_user_id', 'user_video_analyses', ['user_id'])
    op.create_index('ix_user_video_analyses_video_id', 'user_video_analyses', ['video_id'])
    op.create_index('ix_user_video_analyses_analyzed_at', 'user_video_analyses', ['analyzed_at'])

    # Channels table
    op.create_table(
        'channels',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('channel_id', sa.String(length=24), nullable=False),
        sa.Column('channel_name', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('subscriber_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('total_views', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('video_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('country', sa.String(length=10), nullable=True),
        sa.Column('thumbnail_url', sa.String(length=500), nullable=True),
        sa.Column('custom_url', sa.String(length=255), nullable=True),
        sa.Column('created_at_yt', sa.DateTime(), nullable=True),
        sa.Column('discovered_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('needs_refresh', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel_id')
    )
    op.create_index('ix_channels_channel_id', 'channels', ['channel_id'])
    op.create_index('ix_channels_category', 'channels', ['category'])
    op.create_index('ix_channels_subscriber_count', 'channels', ['subscriber_count'])

    # Videos table
    op.create_table(
        'videos',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('video_id', sa.String(length=11), nullable=False),
        sa.Column('channel_id', sa.String(length=24), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('view_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('like_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('comment_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('thumbnail_url', sa.String(length=500), nullable=True),
        sa.Column('category_id', sa.String(length=10), nullable=True),
        sa.Column('tags', sa.Text(), nullable=True),
        sa.Column('collected_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('view_count_24h', sa.BigInteger(), nullable=True),
        sa.Column('view_count_48h', sa.BigInteger(), nullable=True),
        sa.Column('view_count_7d', sa.BigInteger(), nullable=True),
        sa.Column('view_count_30d', sa.BigInteger(), nullable=True),
        sa.Column('last_velocity_update', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('video_id')
    )
    op.create_index('ix_videos_video_id', 'videos', ['video_id'])
    op.create_index('ix_videos_channel_id', 'videos', ['channel_id'])
    op.create_index('ix_videos_published_at', 'videos', ['published_at'])

    # Channel snapshots table
    op.create_table(
        'channel_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('channel_id', sa.String(length=24), nullable=False),
        sa.Column('subscriber_count', sa.BigInteger(), nullable=False),
        sa.Column('view_count', sa.BigInteger(), nullable=True),
        sa.Column('video_count', sa.Integer(), nullable=True),
        sa.Column('snapshot_date', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_channel_snapshots_channel_id', 'channel_snapshots', ['channel_id'])
    op.create_index('ix_channel_snapshots_snapshot_date', 'channel_snapshots', ['snapshot_date'])


def downgrade() -> None:
    op.drop_table('channel_snapshots')
    op.drop_table('videos')
    op.drop_table('channels')
    op.drop_table('user_video_analyses')
    op.drop_table('youtube_connections')
    op.drop_table('users')
