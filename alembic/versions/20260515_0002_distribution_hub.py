"""Add distribution hub tables (connected_accounts, distribution_jobs, distribution_results)

Revision ID: 20260515_0002
Revises: 20260510_0001
Create Date: 2026-05-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260515_0002'
down_revision: Union[str, None] = '20260510_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----- connected_accounts -----
    op.create_table(
        'connected_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('platform', sa.String(20), nullable=False),
        sa.Column('platform_account_id', sa.String(255), nullable=False),
        sa.Column('handle', sa.String(100), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('avatar_url', sa.String(500), nullable=True),
        sa.Column('access_token', sa.Text(), nullable=False),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('scopes', sa.Text(), nullable=True),
        sa.Column('follower_count', sa.BigInteger(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('auto_publish', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('default_caption_variation', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('connected_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'platform', 'platform_account_id', name='uq_user_platform_account'),
    )
    op.create_index('ix_connected_accounts_user_id', 'connected_accounts', ['user_id'])
    op.create_index('ix_connected_accounts_platform', 'connected_accounts', ['platform'])
    op.create_index('idx_connected_user_platform', 'connected_accounts', ['user_id', 'platform'])
    op.create_index('idx_connected_active', 'connected_accounts', ['user_id', 'is_active'])
    
    # ----- distribution_jobs -----
    op.create_table(
        'distribution_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('base_caption', sa.Text(), nullable=True),
        sa.Column('video_url', sa.String(500), nullable=True),
        sa.Column('video_path', sa.String(500), nullable=True),
        sa.Column('thumbnail_url', sa.String(500), nullable=True),
        sa.Column('source_video_url', sa.String(500), nullable=True),
        sa.Column('clip_start_sec', sa.Float(), nullable=True),
        sa.Column('clip_end_sec', sa.Float(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('target_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('success_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vary_captions', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_distribution_jobs_user_id', 'distribution_jobs', ['user_id'])
    op.create_index('idx_distribution_user_created', 'distribution_jobs', ['user_id', 'created_at'])
    op.create_index('idx_distribution_status', 'distribution_jobs', ['status'])
    
    # ----- distribution_results -----
    op.create_table(
        'distribution_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('platform', sa.String(20), nullable=False),
        sa.Column('posted_url', sa.String(500), nullable=True),
        sa.Column('posted_id', sa.String(255), nullable=True),
        sa.Column('caption_used', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_distribution_results_job_id', 'distribution_results', ['job_id'])
    op.create_index('ix_distribution_results_account_id', 'distribution_results', ['account_id'])
    op.create_index('idx_dist_result_job', 'distribution_results', ['job_id'])
    op.create_index('idx_dist_result_account', 'distribution_results', ['account_id'])


def downgrade() -> None:
    op.drop_index('idx_dist_result_account', table_name='distribution_results')
    op.drop_index('idx_dist_result_job', table_name='distribution_results')
    op.drop_index('ix_distribution_results_account_id', table_name='distribution_results')
    op.drop_index('ix_distribution_results_job_id', table_name='distribution_results')
    op.drop_table('distribution_results')
    
    op.drop_index('idx_distribution_status', table_name='distribution_jobs')
    op.drop_index('idx_distribution_user_created', table_name='distribution_jobs')
    op.drop_index('ix_distribution_jobs_user_id', table_name='distribution_jobs')
    op.drop_table('distribution_jobs')
    
    op.drop_index('idx_connected_active', table_name='connected_accounts')
    op.drop_index('idx_connected_user_platform', table_name='connected_accounts')
    op.drop_index('ix_connected_accounts_platform', table_name='connected_accounts')
    op.drop_index('ix_connected_accounts_user_id', table_name='connected_accounts')
    op.drop_table('connected_accounts')
