"""Add render_progress + render_progress_message to edit_sessions

Lets the Studio render job emit coarse progress updates that the frontend
polls every 1.5s while a render is in flight (Week 2 of the Studio build).
Both columns are nullable so existing rows + idle sessions are fine.

Revision ID: 20260518_0007
Revises: 20260517_0006
Create Date: 2026-05-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260518_0007"
down_revision: str | None = "20260517_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("edit_sessions") as batch_op:
        batch_op.add_column(sa.Column("render_progress", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("render_progress_message", sa.String(length=200), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("edit_sessions") as batch_op:
        batch_op.drop_column("render_progress_message")
        batch_op.drop_column("render_progress")
