"""Backfill tax_amount for cost rows whose tax was entered as a percent.

Revision ID: p1a000000026
Revises: p1a000000025
Create Date: 2026-07-10

Rows created before the percent-mode tax fix stored ``tax_percent`` but left
``tax_amount`` NULL — so their percentage tax was silently dropped from every
total (the calc uses tax_amount only). This one-off data migration derives the
amount from the row's base and populates ``tax_amount`` for exactly those stale
rows, leaving ``tax_percent`` in place for the FE round-trip.

Base per cost type:
  * transaction_cost : per_transaction_cost * planned_transactions
  * everything else  : cost

Only touches rows with a positive ``tax_percent`` and a NULL ``tax_amount`` so
intentional zero-tax rows are untouched. Not reversible (the original NULLs are
unknown once filled), so downgrade is a no-op.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000026"
down_revision: str = "p1a000000025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        """
        UPDATE project.project_cost_items
        SET tax_amount = ROUND(
            (CASE
                WHEN cost_type_code = 'transaction_cost'
                    THEN COALESCE(per_transaction_cost, 0) * COALESCE(planned_transactions, 0)
                ELSE COALESCE(cost, 0)
             END) * tax_percent / 100.0,
            2)
        WHERE tax_percent IS NOT NULL
          AND tax_percent > 0
          AND tax_amount IS NULL
        """
    ))


def downgrade() -> None:
    # Not reversible — the original NULL tax_amount values are not recoverable.
    pass
