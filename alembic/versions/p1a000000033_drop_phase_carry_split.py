"""Revert #326: drop the independent OPE / other-cost carry-forward percentages.

Revision ID: p1a000000033
Revises: p1a000000032
Create Date: 2026-07-22

The independent partial carry-forward split (bug #326, added in
p1a000000031) was reverted — carry-forward goes back to carrying a phase's
ENTIRE leftover (one-time + other costs clubbed). This forward migration drops
the two per-phase percentage columns; ``downgrade`` re-adds them (nullable) so
the change is reversible.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000033"
down_revision: str = "p1a000000032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("project_phase_qrg", "one_time_carry_percent", schema="project")
    op.drop_column("project_phase_qrg", "other_cost_carry_percent", schema="project")


def downgrade() -> None:
    op.add_column("project_phase_qrg",
                  sa.Column("other_cost_carry_percent", sa.Numeric(5, 2), nullable=True),
                  schema="project")
    op.add_column("project_phase_qrg",
                  sa.Column("one_time_carry_percent", sa.Numeric(5, 2), nullable=True),
                  schema="project")
