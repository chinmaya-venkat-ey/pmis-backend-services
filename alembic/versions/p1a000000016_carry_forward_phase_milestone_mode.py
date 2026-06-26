"""Carry-forward redesign: always-full-leftover + phase|milestone equal split.

Revision ID: p1a000000016
Revises: p1a000000015
Create Date: 2026-06-26

The partial-carry options (percent-of-leftover / fixed amount) are dropped — a
carrying phase now ALWAYS carries its entire leftover. ``carry_forward_mode``
is repurposed from 'percent'|'amount' to the DISTRIBUTION unit
'phase'|'milestone' (the leftover is split equally across all SUBSEQUENT phases
or all subsequent milestones). The ``carry_forward_percent`` /
``carry_forward_amount`` columns are removed. Any previously-enabled row with a
legacy mode is defaulted to 'phase'.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000016"
down_revision: str = "p1a000000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Repurpose existing mode values to the new distribution unit.
    op.execute(
        "UPDATE project.project_phase_qrg "
        "SET carry_forward_mode = 'phase' "
        "WHERE carry_forward_mode IN ('percent', 'amount')"
    )
    op.drop_column("project_phase_qrg", "carry_forward_percent", schema="project")
    op.drop_column("project_phase_qrg", "carry_forward_amount", schema="project")


def downgrade() -> None:
    op.add_column(
        "project_phase_qrg",
        sa.Column("carry_forward_percent", sa.Numeric(5, 2), nullable=True),
        schema="project",
    )
    op.add_column(
        "project_phase_qrg",
        sa.Column("carry_forward_amount", sa.Numeric(18, 2), nullable=True),
        schema="project",
    )
    # Best-effort: map the distribution unit back to a legacy mode.
    op.execute(
        "UPDATE project.project_phase_qrg "
        "SET carry_forward_mode = 'percent' "
        "WHERE carry_forward_mode IN ('phase', 'milestone')"
    )
