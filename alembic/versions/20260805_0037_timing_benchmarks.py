"""timing_benchmarks: measured publish-hour / day-of-week hit rates

Revision ID: 20260805_0037
Revises: 20260805_0036
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = "20260805_0037"
down_revision = "20260805_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "timing_benchmarks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("dimension", sa.String(length=8), nullable=False),
        sa.Column("bucket", sa.Integer(), nullable=False),
        sa.Column("niche", sa.String(length=8), nullable=True),
        sa.Column("is_short", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("n_videos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hit_rate", sa.Float(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_timing_benchmarks_computed_at", "timing_benchmarks", ["computed_at"])
    op.create_index("ix_timing_benchmarks_niche", "timing_benchmarks", ["niche"])
    op.create_index("idx_timing_benchmark_lookup", "timing_benchmarks",
                    ["dimension", "niche", "is_short"])


def downgrade() -> None:
    op.drop_index("idx_timing_benchmark_lookup", table_name="timing_benchmarks")
    op.drop_index("ix_timing_benchmarks_niche", table_name="timing_benchmarks")
    op.drop_index("ix_timing_benchmarks_computed_at", table_name="timing_benchmarks")
    op.drop_table("timing_benchmarks")
