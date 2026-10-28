"""users.watchlist_email_alerts: opt-out flag for watchlist breakout emails

Revision ID: 20260621_0031
Revises: 20260621_0030
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "20260621_0031"
down_revision = "20260621_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "watchlist_email_alerts", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("users", "watchlist_email_alerts")
