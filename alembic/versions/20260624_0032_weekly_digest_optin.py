"""users.weekly_digest: opt-in flag for the weekly niche digest email

Revision ID: 20260624_0032
Revises: 20260621_0031
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = "20260624_0032"
down_revision = "20260621_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "weekly_digest", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("users", "weekly_digest")
