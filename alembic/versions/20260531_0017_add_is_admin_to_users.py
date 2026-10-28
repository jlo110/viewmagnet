"""add is_admin to users

Revision ID: 20260531_0017
Revises: 20260530_0016
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa

revision = "20260531_0017"
down_revision = "20260530_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
