"""Add expense-line fields to cost items (resource / transaction cost).

Revision ID: p1a000000020
Revises: p1a000000019
Create Date: 2026-07-01

Resource and transaction cost rows are standalone labelled expense lines added
to a phase (flat planned expenses, not billed by milestone % and not in
carry-forward):

  * transaction cost — ``per_transaction_cost`` × ``planned_transactions`` = total
  * resource cost     — value in the existing ``cost`` column
  * ``line_label``     — the display name of the expense line

All nullable / additive; fixed and one-time rows leave them NULL.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000020"
down_revision: str = "p1a000000019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_cost_items",
                  sa.Column("per_transaction_cost", sa.Numeric(18, 2), nullable=True),
                  schema="project")
    op.add_column("project_cost_items",
                  sa.Column("planned_transactions", sa.Integer(), nullable=True),
                  schema="project")
    op.add_column("project_cost_items",
                  sa.Column("line_label", sa.String(255), nullable=True),
                  schema="project")


def downgrade() -> None:
    op.drop_column("project_cost_items", "line_label", schema="project")
    op.drop_column("project_cost_items", "planned_transactions", schema="project")
    op.drop_column("project_cost_items", "per_transaction_cost", schema="project")
