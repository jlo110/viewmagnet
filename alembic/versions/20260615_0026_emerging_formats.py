"""create emerging_formats (Format Radar)

Title/packaging formats mined daily from the live breakout window. ``momentum``
(recent vs prior occurrences) and ``openness`` (distinct channels) are the live
signals a static format archive can't produce. One row per (slug, niche), the
batch replaced wholesale each recompute.

Revision ID: 20260615_0026
Revises: 20260612_0025
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = "20260615_0026"
down_revision = "20260612_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "emerging_formats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("template", sa.String(length=300), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("psychology_type", sa.String(length=40), nullable=False, server_default="Pattern"),
        sa.Column("niche", sa.String(length=60), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_outlier", sa.Float(), nullable=False, server_default="0"),
        sa.Column("median_outlier", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_views", sa.Float(), nullable=False, server_default="0"),
        sa.Column("momentum", sa.Float(), nullable=False, server_default="1"),
        sa.Column("unique_channels", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("openness", sa.String(length=12), nullable=False, server_default="open"),
        sa.Column("reliability", sa.String(length=8), nullable=False, server_default="low"),
        sa.Column("examples", sa.Text(), nullable=True),
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="45"),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("slug", "niche", name="uq_emerging_format_slug_niche"),
    )
    op.create_index("ix_emerging_formats_slug", "emerging_formats", ["slug"])
    op.create_index("ix_emerging_formats_niche", "emerging_formats", ["niche"])
    op.create_index("ix_emerging_formats_computed_at", "emerging_formats", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_emerging_formats_computed_at", table_name="emerging_formats")
    op.drop_index("ix_emerging_formats_niche", table_name="emerging_formats")
    op.drop_index("ix_emerging_formats_slug", table_name="emerging_formats")
    op.drop_table("emerging_formats")
