"""Seed the resource_cost + transaction_cost cost types.

Revision ID: m1a000000016
Revises: m1a000000015
Create Date: 2026-07-28

Why:
  project-management treats ``resource_cost`` and ``transaction_cost`` as
  first-class cost types on the Finance page, but masters only seeded
  fixed / one_time / recurring_cost — so ``validate_cost_type_code`` rejected
  them. Seed both (positions 3 & 4, filling the gap before recurring_cost=5).
  Idempotent via ON CONFLICT.
"""
from __future__ import annotations

from alembic import op

revision = "m1a000000016"
down_revision = "m1a000000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO masters.cost_types (id, code, name, position, active, is_builtin)
        VALUES
          (gen_random_uuid()::text, 'resource_cost', 'Resource Cost', 3, true, true),
          (gen_random_uuid()::text, 'transaction_cost', 'Transaction Cost', 4, true, true)
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM masters.cost_types WHERE code IN ('resource_cost', 'transaction_cost')"
    )
