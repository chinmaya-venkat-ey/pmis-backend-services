"""SLA 005 — revert PER_UNIT_OVER_THRESHOLD to LADDER (RFP §5.28.1.b).

Migration 0024 reclassified SLA 005 to PER_UNIT_OVER_THRESHOLD on the
assumption that "every additional replacement in the quarter is Sev 4"
meant per-unit cumulative points. That reading contradicts RFP §5.28.1.b:

    "Each SLA will be capped [referred to as 'SLA Cap' in the SLAs
    defined below] at 'Severity level = 4' within a measurement interval.
    The total points accumulated and the liquidated damages, per SLA,
    will also be capped for a reporting interval as per the table below."

The right reading: any measurement in a reporting interval that lands in
the escalation band produces a single severity=4 hit (max 8 points).
The LD ladder in §5.28.1.c is where that hit becomes LD %:

    points >= 8  →  4 %  (SLA Cap for the reporting interval)
    points  = 6  →  3 %
    points  = 4  →  2 %
    points  = 2  →  1 %
    points <= 0  →  0 %  (compliance credit)

For SLA 005 with the fixed bands from migration 0024 — L0 range_max=1
(sev=0), L4 range_min=1 (sev=4) — the LADDER dispatch now produces the
correct output for every observation:

    observed=1  →  L0 (1 ≤ 1)  →  sev=0, points=-2, LD=0%
    observed=2  →  L4 (2 > 1)  →  sev=4, points=8,  LD=4%
    observed=5  →  L4 (5 > 1)  →  sev=4, points=8,  LD=4%
    observed=100→  L4          →  sev=4, points=8,  LD=4%  (capped)

Reverts only ld_formula_rule. The band bounds patched in 0024 stay —
they were broken (NULL) before and LADDER also needs them to work.

The PER_UNIT_OVER_THRESHOLD evaluator branch + Track B whitelist entry
in the code are retained for future use (some SLA family may genuinely
need cumulative scaling), just not applied to any live SLA today.

Revision ID: 0026_sla005_rev
Revises:     0025_sla006_kt
Create Date: 2026-07-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0026_sla005_rev"            # 15 chars — fits VARCHAR(32)
down_revision = "0025_sla006_kt"
branch_labels = None
depends_on = None


_SLA005_REGEX = r"^(PMU|PMC)[-_]SLA005([-_].*|_?)?$"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE contract.sla_definitions
               SET ld_formula_rule = 'LADDER'
             WHERE sla_ref ~ :regex
               AND status = 'ACTIVE'
               AND ld_formula_rule = 'PER_UNIT_OVER_THRESHOLD'
            """
        ),
        {"regex": _SLA005_REGEX},
    )


def downgrade() -> None:
    # Revert to the (wrong) PER_UNIT_OVER_THRESHOLD state migration 0024
    # produced, so alembic history round-trips cleanly.
    op.get_bind().execute(
        sa.text(
            """
            UPDATE contract.sla_definitions
               SET ld_formula_rule = 'PER_UNIT_OVER_THRESHOLD'
             WHERE sla_ref ~ :regex
               AND ld_formula_rule = 'LADDER'
            """
        ),
        {"regex": _SLA005_REGEX},
    )
