"""Add is_resource_based / is_transaction_based flags to milestones.

Revision ID: p1a000000027
Revises: p1a000000026
Create Date: 2026-07-13

Why:
  Milestones gain two delivery-model booleans:
    * ``is_resource_based``  — resource / man-month driven milestone.
    * ``is_transaction_based`` — per-transaction driven milestone.
  Both are non-nullable and default to false. On the wire ``isResourceBased``
  is mandatory on create and ``isTransactionBased`` is optional; the DB
  default keeps existing rows valid (backfilled as false). Additive — no
  data migration beyond the server_default backfill.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000027"
down_revision: str = "p1a000000026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "milestones",
        sa.Column(
            "is_resource_based",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="project",
    )
    op.add_column(
        "milestones",
        sa.Column(
            "is_transaction_based",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="project",
    )


def downgrade() -> None:
    op.drop_column("milestones", "is_transaction_based", schema="project")
    op.drop_column("milestones", "is_resource_based", schema="project")
