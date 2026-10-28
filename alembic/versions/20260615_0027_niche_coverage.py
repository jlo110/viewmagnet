"""stratification columns on tracked_channels + niche_coverage

Adds subscriber_count / category / size_tier / enrolled_via to tracked_channels
(stratified expansion) and creates the per-niche coverage table that measures
whether each niche is densely enough tracked to surface live signal.

Revision ID: 20260615_0027
Revises: 20260615_0026
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = "20260615_0027"
down_revision = "20260615_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tracked_channels", sa.Column("subscriber_count", sa.BigInteger(), nullable=True))
    op.add_column("tracked_channels", sa.Column("category", sa.String(length=8), nullable=True))
    op.add_column("tracked_channels", sa.Column("size_tier", sa.String(length=8), nullable=True))
    op.add_column("tracked_channels", sa.Column("enrolled_via", sa.String(length=20), nullable=True))
    op.create_index("ix_tracked_channels_category", "tracked_channels", ["category"])
    op.create_index("ix_tracked_channels_size_tier", "tracked_channels", ["size_tier"])

    op.create_table(
        "niche_coverage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("niche", sa.String(length=8), nullable=False),
        sa.Column("tracked_channels", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tier_mix", sa.Text(), nullable=True),
        sa.Column("breakouts_7d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_formats", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_channels", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deficit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("starved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_niche_coverage_niche", "niche_coverage", ["niche"])
    op.create_index("ix_niche_coverage_computed_at", "niche_coverage", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_niche_coverage_computed_at", table_name="niche_coverage")
    op.drop_index("ix_niche_coverage_niche", table_name="niche_coverage")
    op.drop_table("niche_coverage")
    op.drop_index("ix_tracked_channels_size_tier", table_name="tracked_channels")
    op.drop_index("ix_tracked_channels_category", table_name="tracked_channels")
    op.drop_column("tracked_channels", "enrolled_via")
    op.drop_column("tracked_channels", "size_tier")
    op.drop_column("tracked_channels", "category")
    op.drop_column("tracked_channels", "subscriber_count")
