"""create youtube_quota_usage (quota observability)

Durable per-key, per-operation, per-day YouTube API quota accounting so
"are our jobs running out of quota?" is answerable across restarts/processes.
Written by src.youtube.quota_store.flush_quota_usage (scheduler, every 5 min).

Revision ID: 20260610_0020
Revises: 20260608_0019
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = "20260610_0020"
down_revision = "20260608_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "youtube_quota_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usage_date", sa.String(length=10), nullable=False),
        sa.Column("key_index", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("usage_date", "key_index", "operation", name="uq_quota_usage"),
    )
    op.create_index(
        "ix_youtube_quota_usage_usage_date", "youtube_quota_usage", ["usage_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_youtube_quota_usage_usage_date", table_name="youtube_quota_usage")
    op.drop_table("youtube_quota_usage")
