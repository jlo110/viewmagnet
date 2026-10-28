"""users.alert_webhook_url: Slack/Discord war-room delivery (Phase 2.2)

Revision ID: 20260624_0034
Revises: 20260624_0033
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = "20260624_0034"
down_revision = "20260624_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("alert_webhook_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "alert_webhook_url")
