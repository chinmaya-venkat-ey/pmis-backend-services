"""SLA 005 — reclassify to PER_UNIT_OVER_THRESHOLD + fix broken bands.

Migration 0022 set ``ld_formula_rule = 'LADDER'`` on PMU-SLA005 and every
onboarded PMC-SLA005 variant. LADDER routes the evaluator down the
single-band-hit path — observed=2 and observed=200 both produce the same
severity=4 / 8 points, which contradicts RFP §5.28.3.b ("every additional
replacement in the quarter is Sev 4"). Under LADDER the money never
scales with the number of replacements.

This migration:

  1. Adds ``PER_UNIT_OVER_THRESHOLD`` as the classifier on canonical +
     timestamped variants of PMU-SLA005 and PMC-SLA005 so the evaluator
     dispatches to the new per-unit-scaling branch shipped in
     ``point_accumulation.py::_per_unit_over_threshold``.

  2. Patches the broken condition_bands on PMC-SLA005 rows that were
     onboarded via the from-rfp wizard without proper range_min/max
     bounds. The evaluator's new branch requires:
        - a baseline band (severity=0) with ``range_max = threshold``
        - an escalation band (severity>0) missing ``range_min = threshold``
     Fills the RFP-canonical threshold of 1 replacement/quarter where
     either bound is NULL. Safe to re-run — WHERE clauses gate on NULL.

  3. Ships the same fix for PMU-SLA006 (KT overlap) — bands stay LADDER
     because "days below threshold" needs the mirror PER_UNIT_UNDER
     rule; not adding that rule here to keep the change tight. SLA 006
     stays on LADDER (which is at least idempotent, single-band-hit).

Revision ID: 0024_sla005_puot
Revises:     0023_seed_all_contracts
Create Date: 2026-07-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0024_sla005_puot"           # 16 chars — fits VARCHAR(32)
down_revision = "0023_seed_all_contracts"
branch_labels = None
depends_on = None


# Match canonical SLA rows AND every timestamped variant the onboarding
# wizard has created — both hyphen and underscore separators. Examples
# it must cover: "PMU-SLA005", "PMU-SLA005-20260715133100",
# "PMC-SLA005_", "PMC-SLA005-20260722132722".
_SLA005_REGEX = r"^(PMU|PMC)[-_]SLA005([-_].*|_?)?$"


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Set ld_formula_rule = 'PER_UNIT_OVER_THRESHOLD' on every SLA005
    #    variant. Unconditional SET (not COALESCE) because we're actively
    #    replacing the wrong 'LADDER' value migration 0022 left behind.
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_definitions
               SET ld_formula_rule = 'PER_UNIT_OVER_THRESHOLD'
             WHERE sla_ref ~ :regex
               AND status = 'ACTIVE'
            """
        ),
        {"regex": _SLA005_REGEX},
    )

    # 2. Patch broken bands on PMC-SLA005 variants — the wizard onboarded
    #    them with band labels like "L0 any" / "L4 any" and NULL range
    #    values, which the evaluator can't compare against. Fill the
    #    RFP-canonical threshold of 1 for both the baseline (sev=0 →
    #    range_max) and escalation (sev>0 → range_min) bands.
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_condition_bands b
               SET range_max = 1
              FROM contract.sla_definitions d
             WHERE d.id = b.sla_id
               AND d.sla_ref ~ :regex
               AND d.status = 'ACTIVE'
               AND COALESCE(b.severity_level, 0) = 0
               AND b.range_max IS NULL
            """
        ),
        {"regex": _SLA005_REGEX},
    )
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_condition_bands b
               SET range_min = 1
              FROM contract.sla_definitions d
             WHERE d.id = b.sla_id
               AND d.sla_ref ~ :regex
               AND d.status = 'ACTIVE'
               AND COALESCE(b.severity_level, 0) > 0
               AND b.range_min IS NULL
            """
        ),
        {"regex": _SLA005_REGEX},
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Revert to LADDER (matches migration 0022's original value).
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_definitions
               SET ld_formula_rule = 'LADDER'
             WHERE sla_ref ~ :regex
               AND ld_formula_rule = 'PER_UNIT_OVER_THRESHOLD'
            """
        ),
        {"regex": _SLA005_REGEX},
    )
    # Band range fixes are additive — leave them in place on downgrade.
    # (Reverting would re-break the evaluator for any variant that was
    # already NULL, and there's no way to distinguish rows we filled
    # from rows that always had range_max=1.)
