"""niche_benchmarks: measured view-trajectory percentiles per niche/format

Revision ID: 20260805_0036
Revises: 20260625_0035
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = "20260805_0036"
down_revision = "20260625_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "niche_benchmarks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("niche", sa.String(length=8), nullable=True),
        sa.Column("is_short", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint", sa.String(length=8), nullable=False),
        sa.Column("n_videos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("p10", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p25", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p50", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p75", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p90", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p95", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p99", sa.Float(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_niche_benchmarks_computed_at", "niche_benchmarks", ["computed_at"])
    op.create_index("ix_niche_benchmarks_niche", "niche_benchmarks", ["niche"])
    op.create_index("idx_niche_benchmark_lookup", "niche_benchmarks",
                    ["niche", "is_short", "checkpoint"])


def downgrade() -> None:
    op.drop_index("idx_niche_benchmark_lookup", table_name="niche_benchmarks")
    op.drop_index("ix_niche_benchmarks_niche", table_name="niche_benchmarks")
    op.drop_index("ix_niche_benchmarks_computed_at", table_name="niche_benchmarks")
    op.drop_table("niche_benchmarks")
