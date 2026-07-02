"""Add billed split to expense cost rows (resource / transaction in carry-forward).

Revision ID: p1a000000022
Revises: p1a000000021
Create Date: 2026-07-01

Resource / transaction cost is billed 100% of its own value in its phase by
default; the user can reduce it to a percent or ₹ amount, and the unbilled
remainder carries forward with the phase's leftover.

  * ``billed_mode``  — 'percent' | 'amount'
  * ``billed_value`` — the % (of the line's value) or ₹ amount that is billed

NULL for fixed / one-time rows (and legacy expense rows → treated as fully billed).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000022"
down_revision: str = "p1a000000021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_cost_items",
                  sa.Column("billed_mode", sa.String(8), nullable=True), schema="project")
    op.add_column("project_cost_items",
                  sa.Column("billed_value", sa.Numeric(18, 2), nullable=True), schema="project")


def downgrade() -> None:
    op.drop_column("project_cost_items", "billed_value", schema="project")
    op.drop_column("project_cost_items", "billed_mode", schema="project")
