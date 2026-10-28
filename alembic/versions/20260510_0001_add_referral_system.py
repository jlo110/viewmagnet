"""Add referral system fields to users table

Revision ID: 20260510_0001
Revises: 20260508_0000_001
Create Date: 2026-05-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260510_0001'
down_revision: Union[str, None] = '20260508_0000_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add referral system columns to users table
    op.add_column('users', sa.Column('referral_code', sa.String(12), nullable=True))
    op.add_column('users', sa.Column('referred_by_id', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('referral_bonus_analyses', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('referral_count', sa.Integer(), nullable=False, server_default='0'))
    
    # Create unique index on referral_code
    op.create_index('ix_users_referral_code', 'users', ['referral_code'], unique=True)


def downgrade() -> None:
    # Remove index
    op.drop_index('ix_users_referral_code', table_name='users')
    
    # Remove columns
    op.drop_column('users', 'referral_count')
    op.drop_column('users', 'referral_bonus_analyses')
    op.drop_column('users', 'referred_by_id')
    op.drop_column('users', 'referral_code')
