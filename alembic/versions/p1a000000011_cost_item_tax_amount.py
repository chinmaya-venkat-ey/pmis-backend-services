"""Add tax_amount to project_cost_items (tax is now an exact amount).

Revision ID: p1a000000011
Revises: p1a000000010
Create Date: 2026-06-04

Why:
  The cost-row Tax column now takes the exact tax AMOUNT the user enters
  (e.g. 1000 on a 10000 cost) instead of a percentage; ``total`` =
  ``cost + tax_amount``. The legacy ``tax_percent`` column is kept (optional,
  unused) so nothing breaks. Nullable + additive — existing rows keep working
  (their total becomes ``cost`` until a tax_amount is set).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000011"
down_revision: str = "p1a000000010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_cost_items",
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=True),
        schema="project",
    )
    op.create_check_constraint(
        "ck_cost_items_tax_amount_nonneg", "project_cost_items",
        "tax_amount IS NULL OR tax_amount >= 0", schema="project",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_cost_items_tax_amount_nonneg", "project_cost_items",
        schema="project", type_="check",
    )
    op.drop_column("project_cost_items", "tax_amount", schema="project")
