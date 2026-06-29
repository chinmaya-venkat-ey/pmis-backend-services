"""Carry-forward becomes master-driven: carry_forward_mode -> carry_forward_method_code.

Revision ID: p1a000000018
Revises: p1a000000017
Create Date: 2026-06-29

The per-phase carry-forward unit is no longer the local 'phase'|'milestone'
flag; it is a METHOD CODE referencing ``masters.carry_forward_methods.code``
(seeded by masters-svc migration m1a000000009). The legacy values map onto the
``*_evenly`` methods that reproduce today's equal-split behaviour:

    'phase'     -> 'phase_evenly'
    'milestone' -> 'milestone_evenly'

We widen 16 -> 40 chars (method codes like 'time_half_yearly' are longer),
backfill, then drop the old column. No FK constraint is added (cross-schema,
catalog is mirror-validated at the service layer, consistent with the other
``*_code`` columns on this table's siblings).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000018"
down_revision: str = "p1a000000017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_phase_qrg",
        sa.Column("carry_forward_method_code", sa.String(40), nullable=True),
        schema="project",
    )
    # Backfill the new code from the legacy distribution unit.
    op.execute(
        "UPDATE project.project_phase_qrg "
        "SET carry_forward_method_code = CASE carry_forward_mode "
        "    WHEN 'phase' THEN 'phase_evenly' "
        "    WHEN 'milestone' THEN 'milestone_evenly' "
        "    ELSE NULL END "
        "WHERE carry_forward_mode IS NOT NULL"
    )
    op.drop_column("project_phase_qrg", "carry_forward_mode", schema="project")


def downgrade() -> None:
    op.add_column(
        "project_phase_qrg",
        sa.Column("carry_forward_mode", sa.String(16), nullable=True),
        schema="project",
    )
    # Best-effort: map the evenly methods back to the legacy unit; non-evenly
    # methods (custom / time) have no legacy equivalent -> default to 'phase'.
    op.execute(
        "UPDATE project.project_phase_qrg "
        "SET carry_forward_mode = CASE "
        "    WHEN carry_forward_method_code = 'milestone_evenly' THEN 'milestone' "
        "    WHEN carry_forward_method_code IS NOT NULL THEN 'phase' "
        "    ELSE NULL END "
        "WHERE carry_forward_method_code IS NOT NULL"
    )
    op.drop_column("project_phase_qrg", "carry_forward_method_code", schema="project")
