"""Add multi-subject tracking cache + status columns to edit_sessions

Stores the precomputed per-subject crop curves + sparse per-frame bounding
boxes that drive the Studio Camera lane (Week 4). Cache is keyed on
(tracking_subjects_n, tracking_start_time, tracking_end_time) so trimming the
clip or asking for a different subject count transparently invalidates it.

Revision ID: 20260518_0009
Revises: 20260518_0008
Create Date: 2026-05-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260518_0009"
down_revision: str | None = "20260518_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("edit_sessions") as batch_op:
        batch_op.add_column(sa.Column("tracking_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("tracking_subjects_n", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "tracking_status",
                sa.String(length=20),
                nullable=False,
                server_default="idle",
            )
        )
        batch_op.add_column(sa.Column("tracking_progress", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tracking_progress_message", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("tracking_start_time", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("tracking_end_time", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("edit_sessions") as batch_op:
        batch_op.drop_column("tracking_end_time")
        batch_op.drop_column("tracking_start_time")
        batch_op.drop_column("tracking_progress_message")
        batch_op.drop_column("tracking_progress")
        batch_op.drop_column("tracking_status")
        batch_op.drop_column("tracking_subjects_n")
        batch_op.drop_column("tracking_json")
