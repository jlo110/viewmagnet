"""Add description column to studio_projects (Week 9 Connected Tools).

The Connected-Tools handoff from a StudioProject to the Distribution
Hub needs a project-level description to seed the publish caption /
post body. Today we only pass through the project title, so the
publish form always starts empty for the caption — defeating the
"pre-load everything we know" promise of the integration.

``description`` is TEXT (creators paste full long-form captions with
line breaks, hashtags inline, and emoji) and nullable so existing
projects continue to load unchanged.

Revision ID: 20260522_0013
Revises: 20260521_0012
Create Date: 2026-05-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_0013"
down_revision: str | None = "20260521_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("studio_projects") as batch_op:
        batch_op.add_column(
            sa.Column("description", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("studio_projects") as batch_op:
        batch_op.drop_column("description")
