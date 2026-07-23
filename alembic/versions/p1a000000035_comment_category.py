"""#322 — add a classifier column to comments for special attachment rows.

Adds ``project.comments.category`` (nullable). NULL = a normal comment /
general attachment (unchanged). ``'actual_start_reason'`` tags the documents
that support a project's late-start remark so they live on their own endpoint
and are excluded from the general attachment list.

Revision ID: p1a000000035
Revises: p1a000000034
Create Date: 2026-07-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000035"
down_revision: str = "p1a000000034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "comments",
        sa.Column("category", sa.String(length=40), nullable=True),
        schema="project",
    )


def downgrade() -> None:
    op.drop_column("comments", "category", schema="project")
