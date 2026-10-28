"""Create user_render_usage table (monthly render-minute budget).

Week 8 introduces render-minute budgets: free plan = 30 minutes per
UTC month, Pro = unlimited. The render API pre-checks against this
table before enqueueing and rejects with HTTP 402 when the projected
work would push the user over.

One row per ``(user_id, month_start)`` so rollover is just a fresh
row on the first of each month. Old rows stay around for usage
history (visible in the Renders page quota card).

Revision ID: 20260521_0012
Revises: 20260520_0011
Create Date: 2026-05-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260521_0012"
down_revision: str | None = "20260520_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_render_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("month_start", sa.DateTime(), nullable=False),
        sa.Column("minutes_used", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "user_id", "month_start", name="uq_user_render_usage_period"
        ),
    )
    op.create_index(
        "idx_user_render_usage_user_month",
        "user_render_usage",
        ["user_id", "month_start"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_render_usage_user_month",
        table_name="user_render_usage",
    )
    op.drop_table("user_render_usage")
