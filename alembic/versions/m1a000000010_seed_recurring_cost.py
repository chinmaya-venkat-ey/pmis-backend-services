"""Seed the ``recurring_cost`` cost type.

Revision ID: m1a000000010
Revises: m1a000000009
Create Date: 2026-07-09

A recurring cost is a project-level amount distributed across frequency periods
(e.g. yearly) from the start of the project's milestone timeline over the
project duration — it produces a payment SCHEDULE the way carry-forward does,
rather than binding milestones. Builtin + active; position 5 (after the four
existing types). Idempotent via ON CONFLICT.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000010"
down_revision = "m1a000000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("""
        INSERT INTO masters.cost_types (id, code, name, description, position, active, is_builtin)
        VALUES
            (gen_random_uuid()::text, 'recurring_cost', 'Recurring Cost',
             'Amount distributed across frequency periods (e.g. yearly) from the milestone-timeline start over the project duration',
             5, true, true)
        ON CONFLICT (code) DO NOTHING
        """)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM masters.cost_types WHERE code = 'recurring_cost'"))
