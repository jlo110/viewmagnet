"""watchlist_alerts_sent: dedup ledger for emailed watchlist breakout alerts

Revision ID: 20260621_0030
Revises: 20260621_0029
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "20260621_0030"
down_revision = "20260621_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_alerts_sent",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.String(length=20), nullable=False),
        sa.Column("channel_id", sa.String(length=24), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "video_id", name="uq_watchlist_alert_user_video"),
    )
    op.create_index("ix_watchlist_alerts_sent_user_id", "watchlist_alerts_sent", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_alerts_sent_user_id", table_name="watchlist_alerts_sent")
    op.drop_table("watchlist_alerts_sent")
