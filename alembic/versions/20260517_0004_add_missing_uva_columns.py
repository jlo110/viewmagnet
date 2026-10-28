"""Add missing columns to user_video_analyses

These columns exist on the UserVideoAnalysis SQLAlchemy model but were
never included in the initial 20260508_0000_001 migration, so /dashboard/stats
(which selects them via the ORM) errors with UndefinedColumn against
existing databases.

Revision ID: 20260517_0004
Revises: 20260516_0003
Create Date: 2026-05-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260517_0004"
down_revision: str | None = "20260516_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add channel_id + outcome tracking columns to user_video_analyses."""
    with op.batch_alter_table("user_video_analyses") as batch_op:
        batch_op.add_column(sa.Column("channel_id", sa.String(length=24), nullable=True))
        batch_op.add_column(sa.Column("actual_views_7d", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("actual_ctr", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("actual_avg_duration", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("outcome_checked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_video_analyses") as batch_op:
        batch_op.drop_column("outcome_checked_at")
        batch_op.drop_column("actual_avg_duration")
        batch_op.drop_column("actual_ctr")
        batch_op.drop_column("actual_views_7d")
        batch_op.drop_column("channel_id")
