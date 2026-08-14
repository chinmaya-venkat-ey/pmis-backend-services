"""Correct 'NPQP' → 'PQP' in the stored SLA003 description text (corrigendum).

The corrigendum amended the LD base from NPQP to PQP; the settlement math already
uses PQP, but existing PMU-SLA003 rows still carry the old free-text description
("0.1% LD on NPQP …", "× NPQP") which is surfaced in the SLA-master UI. This
updates that text on the stored rows so the UI reads correctly. Scoped to the
PMU SLA003 family and to the two text columns only; no math/behaviour change.

Revision ID: 0035_sla003_pqp
Revises:     0034_fix_matchall
Create Date: 2026-08-14
"""
from __future__ import annotations

from alembic import op


revision = "0035_sla003_pqp"
down_revision = "0034_fix_matchall"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE contract.sla_definitions
           SET description = replace(description, 'NPQP', 'PQP'),
               calculation_method = replace(calculation_method, 'NPQP', 'PQP'),
               updated_at = now()
         WHERE sla_ref LIKE 'PMU-SLA003%'
           AND (description LIKE '%NPQP%' OR calculation_method LIKE '%NPQP%')
        """
    )


def downgrade() -> None:
    # Intentional no-op. The corrected 'PQP' text is what the corrigendum requires;
    # reverting would re-introduce the wrong base name. (Mirrors 0031/0032/0034.)
    pass
