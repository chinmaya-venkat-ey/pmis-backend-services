"""Round-7 Q8: add comments.moderation_reason for tombstone-delete audit trail.

When an admin/super_admin moderates a comment, the row stays but:
  - body is NULL
  - attachments is NULL
  - deleted_at + deleted_by + moderation_reason are set

author_user_id is preserved so the tombstone shows the original author.

Revision ID: p1a000000002
Revises: p1a000000001
Create Date: 2026-05-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "p1a000000002"
down_revision = "p1a000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "comments",
        sa.Column("moderation_reason", sa.Text(), nullable=True),
        schema="project",
    )


def downgrade() -> None:
    op.drop_column("comments", "moderation_reason", schema="project")
