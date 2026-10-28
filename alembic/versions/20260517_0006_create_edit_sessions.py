"""Create edit_sessions table for the Studio editor

Adds the ``edit_sessions`` table that backs the in-browser video editor.
A single JSON ``spec`` column is the canonical source of truth for both
the browser preview (Remotion ``<Player />``) and the server-side render
job, so the user always sees exactly what gets rendered.

Revision ID: 20260517_0006
Revises: 20260517_0005
Create Date: 2026-05-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260517_0006"
down_revision: str | None = "a1c2d3e4f506"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edit_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("clip_key", sa.String(length=64), nullable=False),
        sa.Column("source_video_url", sa.String(length=500), nullable=False),
        sa.Column("source_clip_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_clip_path", sa.String(length=500), nullable=True),
        sa.Column("source_start_time", sa.Float(), nullable=True),
        sa.Column("source_end_time", sa.Float(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("spec", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_render_job_id", sa.String(length=128), nullable=True),
        sa.Column(
            "last_render_status",
            sa.String(length=32),
            nullable=False,
            server_default="idle",
        ),
        sa.Column("last_render_url", sa.String(length=500), nullable=True),
        sa.Column("last_render_error", sa.Text(), nullable=True),
        sa.Column("last_rendered_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("user_id", "clip_key", name="uq_edit_session_user_clip"),
    )
    op.create_index(
        "idx_edit_session_user_updated",
        "edit_sessions",
        ["user_id", "updated_at"],
    )
    op.create_index(
        "ix_edit_sessions_user_id",
        "edit_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_edit_sessions_clip_key",
        "edit_sessions",
        ["clip_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_edit_sessions_clip_key", table_name="edit_sessions")
    op.drop_index("ix_edit_sessions_user_id", table_name="edit_sessions")
    op.drop_index("idx_edit_session_user_updated", table_name="edit_sessions")
    op.drop_table("edit_sessions")
