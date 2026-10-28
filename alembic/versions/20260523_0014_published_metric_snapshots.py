"""Add published_metric_snapshots table + EditSession.cta_provenance (Week 10).

Week 10 closes the post-publish analytics loop. Once a creator
publishes a render through Distribution Hub we periodically capture
performance snapshots from each platform's analytics API and store
them keyed by ``(distribution_result_id, window_key)``. The fixed
window keys ("1h", "24h", "7d", "30d") let the dashboard show "vs.
T+24h baseline" comparisons cheaply and let a missed window gap
gracefully without backfill.

We also add ``EditSession.cta_provenance`` — a JSON column that
captures the LLM recommendation (if any) that drove the user into
the editor, so when the published video's metrics come back we can
attribute them to the originating recommendation and answer the
question "did following the Lead Magnet advice actually move the
needle?".

Revision ID: 20260523_0014
Revises: 20260522_0013
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260523_0014"
down_revision: str | None = "20260522_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "published_metric_snapshots",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "distribution_result_id",
            sa.Integer(),
            sa.ForeignKey(
                "distribution_results.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("posted_url", sa.String(length=500), nullable=True),
        sa.Column("window_key", sa.String(length=8), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column(
            "sampled_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("watch_time_seconds", sa.Float(), nullable=True),
        sa.Column("avg_view_percentage", sa.Float(), nullable=True),
        sa.Column("click_through_rate", sa.Float(), nullable=True),
        sa.Column("raw", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_pms_result_window",
        "published_metric_snapshots",
        ["distribution_result_id", "window_key"],
    )
    op.create_index(
        "idx_pms_user_sampled",
        "published_metric_snapshots",
        ["user_id", "sampled_at"],
    )
    op.create_index(
        "idx_pms_platform_published",
        "published_metric_snapshots",
        ["platform", "published_at"],
    )
    op.create_index(
        "ix_published_metric_snapshots_distribution_result_id",
        "published_metric_snapshots",
        ["distribution_result_id"],
    )
    op.create_index(
        "ix_published_metric_snapshots_user_id",
        "published_metric_snapshots",
        ["user_id"],
    )

    # Attribution: capture which LLM recommendation (if any) drove
    # the user into this edit session, so when the rendered video is
    # published and metrics come back we can roll up "videos that
    # followed recommendation X averaged +Y% engagement".
    with op.batch_alter_table("edit_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("cta_provenance", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("edit_sessions") as batch_op:
        batch_op.drop_column("cta_provenance")
    op.drop_index(
        "ix_published_metric_snapshots_user_id",
        table_name="published_metric_snapshots",
    )
    op.drop_index(
        "ix_published_metric_snapshots_distribution_result_id",
        table_name="published_metric_snapshots",
    )
    op.drop_index(
        "idx_pms_platform_published",
        table_name="published_metric_snapshots",
    )
    op.drop_index(
        "idx_pms_user_sampled",
        table_name="published_metric_snapshots",
    )
    op.drop_index(
        "idx_pms_result_window",
        table_name="published_metric_snapshots",
    )
    op.drop_table("published_metric_snapshots")
