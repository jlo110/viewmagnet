"""Create studio_projects + studio_project_clips tables (multi-clip projects).

Week 7 introduces the Project entity: an ordered list of existing
``EditSession`` clips that the Studio stitches into a single long-form
render. See ``src/database/models.py`` (StudioProject / StudioProjectClip)
and ``src/features/studio/project_spec.py`` for the Pydantic shape.

Two tables:

* ``studio_projects``      — one row per project (title, defaults,
  brand kit JSON, render status).
* ``studio_project_clips`` — ordered join row between a project and an
  ``EditSession`` (position, per-clip trim, per-boundary transition
  override, cache-busting "last_used_session_render_at").

A clip can belong to multiple projects: we never duplicate
``EditSession``s; instead the project render job re-uses each session's
cached render unless the underlying session has been updated since the
last project render.

Revision ID: 20260520_0011
Revises: 20260519_0010
Create Date: 2026-05-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_0011"
down_revision: str | None = "20260519_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio_projects",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(length=500), nullable=False, server_default="Untitled project"),
        sa.Column("default_aspect", sa.String(length=8), nullable=False, server_default="9:16"),
        sa.Column("default_transition_type", sa.String(length=32), nullable=False, server_default="cut"),
        sa.Column("default_transition_ms", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("brand_kit_json", sa.Text(), nullable=True),
        sa.Column("last_render_job_id", sa.String(length=128), nullable=True),
        sa.Column("last_render_status", sa.String(length=32), nullable=False, server_default="idle"),
        sa.Column("last_render_url", sa.String(length=500), nullable=True),
        sa.Column("last_render_error", sa.Text(), nullable=True),
        sa.Column("last_rendered_at", sa.DateTime(), nullable=True),
        sa.Column("render_progress", sa.Integer(), nullable=True),
        sa.Column("render_progress_message", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index(
        "idx_studio_project_user_updated",
        "studio_projects",
        ["user_id", "updated_at"],
    )

    op.create_table(
        "studio_project_clips",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("studio_projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "edit_session_id",
            sa.Integer(),
            sa.ForeignKey("edit_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("trim_in_seconds", sa.Float(), nullable=True),
        sa.Column("trim_out_seconds", sa.Float(), nullable=True),
        sa.Column("transition_in_type", sa.String(length=32), nullable=True),
        sa.Column("transition_in_ms", sa.Integer(), nullable=True),
        sa.Column("last_used_session_render_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("project_id", "position", name="uq_studio_project_clip_position"),
    )
    op.create_index(
        "idx_studio_project_clip_project_position",
        "studio_project_clips",
        ["project_id", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_studio_project_clip_project_position",
        table_name="studio_project_clips",
    )
    op.drop_table("studio_project_clips")
    op.drop_index(
        "idx_studio_project_user_updated",
        table_name="studio_projects",
    )
    op.drop_table("studio_projects")
