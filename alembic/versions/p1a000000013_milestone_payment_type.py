"""Add payment_type to milestones (logical FK to masters.payment_types.code).

Revision ID: p1a000000013
Revises: p1a000000012
Create Date: 2026-06-17

Why:
  Milestones gain an optional "Payment Type" selector driven from the new
  masters.payment_types catalog (built-ins: partial_payment,
  complete_payment). Additive + nullable — existing rows keep working with
  payment_type = NULL. Stored as the lowercase code string (cross-schema
  logical FK; not a hard DB FK, matching status/priority).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000013"
down_revision: str = "p1a000000012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "milestones",
        sa.Column("payment_type", sa.String(32), nullable=True),
        schema="project",
    )
    op.create_index(
        "ix_milestones_payment_type", "milestones", ["payment_type"],
        schema="project",
    )


def downgrade() -> None:
    op.drop_index("ix_milestones_payment_type", table_name="milestones", schema="project")
    op.drop_column("milestones", "payment_type", schema="project")
