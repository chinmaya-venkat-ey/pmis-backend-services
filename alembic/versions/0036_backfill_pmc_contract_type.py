"""Backfill contract_type='PMU' on blank PMC/PMU SLA defs (unblock settlement).

The settlement resolves the quarterly LD cap from contract.contract_ld_rules keyed
on the def's contract_type; a NULL/blank type → no cap → status='blocked_missing_cap'
and EVERY money field (f_amount/npqp/ld_amount/pa_amount/aqp_amount) is written NULL.

The live PMC-SLA* defs (mirrors of the PMU templates, on the PMU-for-MSP consultant
projects) onboarded with contract_type=NULL because their ref prefix "PMC" was not a
recognised contract type (only BSP/MSAP/MSIP/PMU are). This backfills them — and any
underscore-ref PMU variant that also missed derivation — to PMU (confirmed by the
user: all five affected projects run under PMU). Onboarding is also fixed so new
PMC-* defs derive PMU (sla_service._CONTRACT_TYPE_ALIASES).

Downgrade is an intentional no-op — reverting to NULL would re-break settlement.

Revision ID: 0036_backfill_pmc_ct
Revises:     0035_sla003_pqp
Create Date: 2026-08-14
"""
from __future__ import annotations

from alembic import op


revision = "0036_backfill_pmc_ct"
down_revision = "0035_sla003_pqp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE contract.sla_definitions
           SET contract_type = 'PMU', updated_at = now()
         WHERE (contract_type IS NULL OR contract_type = '')
           AND (sla_ref LIKE 'PMC%' OR sla_ref LIKE 'PMU%')
        """
    )


def downgrade() -> None:
    # Intentional no-op. A blank contract_type is the bug (it blocks settlement);
    # reverting would re-introduce it. Mirrors 0031/0035.
    pass
