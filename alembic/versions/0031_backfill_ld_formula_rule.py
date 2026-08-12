"""Backfill ld_formula_rule on existing ACTIVE SLA defs that have NULL rule.

Companion to the onboarding fix (sla_service now sets ld_formula_rule). Every SLA
onboarded before that fix has ld_formula_rule = NULL, so it falls out of BOTH
settlement tracks and produces no LD (quarterly_settlement_service _TRACK_B_RULES
+ Track-A PER_UNIT_TIME_DELIVERABLE; NULL = excluded). On the live server ~102 of
238 ACTIVE defs are affected, including SLAs mapped to real projects (PMC).

Sets a track-correct default from the (already-set) ld_computation_base, matching
_derive_ld_formula_rule in sla_service:
  * FIXED_AMOUNT              -> PER_UNIT_TIME_DELIVERABLE  (Track A, deliverable)
  * QUARTERLY/ANNUAL_PAYMENT  -> LADDER                    (Track B, resource/quarterly)

Only touches ACTIVE defs with a NULL rule. This restores the intended architecture
(every SLA is classified for settlement). NOTE: it also *exposes* pre-existing band
defects — a def with wrong/nonsensical bands (e.g. some wizard-mis-onboarded PMC
SLAs) was masked by its NULL rule and will now participate in settlement; those need
separate band remediation / re-onboarding (see doc 31). Settlement is currently
gated on leave-management NPQP anyway, so no LD computes until that + the band
remediation land.

Revision ID: 0031_backfill_rule
Revises:     0030_sla007_hours
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0031_backfill_rule"
down_revision = "0030_sla007_hours"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        """
        UPDATE contract.sla_definitions
           SET ld_formula_rule = 'PER_UNIT_TIME_DELIVERABLE'
         WHERE status = 'ACTIVE'
           AND ld_formula_rule IS NULL
           AND ld_computation_base = 'FIXED_AMOUNT'
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE contract.sla_definitions
           SET ld_formula_rule = 'LADDER'
         WHERE status = 'ACTIVE'
           AND ld_formula_rule IS NULL
           AND ld_computation_base IN ('QUARTERLY_PAYMENT', 'ANNUAL_PAYMENT')
        """
    ))


def downgrade() -> None:
    # Intentional no-op. The backfilled rules are track-correct; reverting them to
    # NULL would re-introduce the "excluded from settlement / no LD" defect, and a
    # backfilled row is indistinguishable from one that was legitimately set to the
    # same rule (so a blanket revert would also clobber correct rows). Mirrors the
    # 0027 policy of leaving RFP-correct data in place on downgrade.
    pass
