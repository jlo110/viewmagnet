"""Add waveform-peaks cache to edit_sessions

Stores pre-computed audio peak amplitudes so the Studio timeline can render
the source-audio waveform without the browser re-decoding the full video on
every reload. Cache validity is keyed by bins + start/end (so trimming the
clip transparently invalidates the cache).

Revision ID: 20260518_0008
Revises: 20260518_0007
Create Date: 2026-05-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260518_0008"
down_revision: str | None = "20260518_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("edit_sessions") as batch_op:
        batch_op.add_column(sa.Column("peaks_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("peaks_bins", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("peaks_start_time", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("peaks_end_time", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("edit_sessions") as batch_op:
        batch_op.drop_column("peaks_end_time")
        batch_op.drop_column("peaks_start_time")
        batch_op.drop_column("peaks_bins")
        batch_op.drop_column("peaks_json")
