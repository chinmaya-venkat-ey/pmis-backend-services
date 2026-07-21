"""Independent partial carry-forward percentages per phase (bug #326).

Revision ID: p1a000000031
Revises: p1a000000030
Create Date: 2026-07-20

The one-time (OPE) stream and the other-cost stream now carry forward
SEPARATELY, each by its own percentage, instead of as one clubbed leftover:
  * other_cost_carry_percent — % of the phase's other-cost (fixed/resource/
    transaction) leftover to carry via the carry-forward method.
  * one_time_carry_percent   — % of the phase's OPE (allocation + carried-in)
    to carry forward phase-wise; the rest is retained in the phase.
Both nullable; read-time defaults preserve prior behaviour (other → 100 when
carry is enabled, one_time → 0).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000031"
down_revision: str = "p1a000000030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_phase_qrg",
                  sa.Column("other_cost_carry_percent", sa.Numeric(5, 2), nullable=True),
                  schema="project")
    op.add_column("project_phase_qrg",
                  sa.Column("one_time_carry_percent", sa.Numeric(5, 2), nullable=True),
                  schema="project")


def downgrade() -> None:
    op.drop_column("project_phase_qrg", "one_time_carry_percent", schema="project")
    op.drop_column("project_phase_qrg", "other_cost_carry_percent", schema="project")
