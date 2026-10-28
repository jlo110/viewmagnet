"""Add brand-voice fields (caption_signature, default_hashtags) to user_brand_kits

Brand voice completes the third leg of the brand-kit auto-apply story:

  - Visual: logo + colors + font already auto-apply to Studio renders.
  - Voice (this migration): caption sign-off + default hashtags auto-apply
    to every Distribution publish so creators don't retype their stock
    line for every cross-post.

``caption_signature`` is TEXT (creators use line breaks, emoji, links).
``default_hashtags`` is a comma-separated VARCHAR(1000) — large enough
to hold ~50 hashtags without overflowing.

Revision ID: 20260519_0010
Revises: 20260518_0009
Create Date: 2026-05-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260519_0010"
down_revision: str | None = "20260518_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_brand_kits") as batch_op:
        batch_op.add_column(
            sa.Column("caption_signature", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("default_hashtags", sa.String(length=1000), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("user_brand_kits") as batch_op:
        batch_op.drop_column("default_hashtags")
        batch_op.drop_column("caption_signature")
