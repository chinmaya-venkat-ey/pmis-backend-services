"""SLA 006 (KT overlap) — classify PMC-SLA006 as LADDER + fix bounds.

RFP §5.28.3.d for SLA 006 is a single-band-hit rule:
    KT overlap >= 20 working days  →  Sev 0 (compliant)
    KT overlap  < 20 working days  →  Sev 4 (breach — 8 points, flat)

The existing LADDER dispatch in point_accumulation handles this shape
correctly, but the live data has two gaps:

  * PMC-SLA006 rows all have ``ld_formula_rule = NULL`` — falls out of
    the Track B whitelist, gets excluded from every settlement.

  * Band ``range_min`` / ``range_max`` were seeded with a boundary bug:
    the existing ``_value_in_band`` convention is ``min`` strict,
    ``max`` inclusive, so ``range_min=20 / range_max=20`` treats value=20
    as a breach (matches L4's ≤20) when it should be compliant (RFP:
    ">= 20 is compliant"). Using ``range_min=19 / range_max=19`` maps
    the strict-min / inclusive-max convention onto the RFP semantics
    cleanly for integer working-day counts.

This migration:

  1. Sets ``ld_formula_rule = 'LADDER'`` on canonical + variants of
     PMC-SLA006 (matches the value migration 0022 already set for
     PMU-SLA006).

  2. Patches PMU-SLA006 canonical bands from (20, 20) to (19, 19) so
     value=20 correctly falls under L0.

  3. Fills NULL bounds on every PMC-SLA006 row with (19, 19), applying
     the RFP-canonical threshold of 20 working days. Only fills where
     bounds are NULL — never overwrites an ops-configured value.

Variants that only have a single band (no escalation band) are left
alone — an UPDATE can't INSERT the missing L4 row without guessing
severity, and those SLAs need to be re-onboarded correctly by ops.

Revision ID: 0025_sla006_kt
Revises:     0024_sla005_puot
Create Date: 2026-07-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0025_sla006_kt"             # 14 chars — fits VARCHAR(32)
down_revision = "0024_sla005_puot"
branch_labels = None
depends_on = None


_SLA006_REGEX = r"^(PMU|PMC)[-_]SLA006([-_].*|_?)?$"
_PMC_SLA006_REGEX = r"^PMC[-_]SLA006([-_].*|_?)?$"


def upgrade() -> None:
    conn = op.get_bind()

    # 1. PMC-SLA006 rows had ld_formula_rule NULL — set them to LADDER
    #    (single-band-hit is the RFP semantic; no new evaluator needed).
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_definitions
               SET ld_formula_rule = 'LADDER'
             WHERE sla_ref ~ :regex
               AND status = 'ACTIVE'
               AND ld_formula_rule IS NULL
            """
        ),
        {"regex": _PMC_SLA006_REGEX},
    )

    # 2. Fix boundary bug on PMU-SLA006 canonical — 20-day threshold with
    #    strict-min / inclusive-max convention needs (19, 19) to make
    #    value=20 land compliant. Guarded WHERE range_min=20 so we don't
    #    touch rows an ops user may have already customized.
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_condition_bands b
               SET range_min = 19
              FROM contract.sla_definitions d
             WHERE d.id = b.sla_id
               AND d.sla_ref ~ :regex
               AND d.status = 'ACTIVE'
               AND COALESCE(b.severity_level, 0) = 0
               AND b.range_min = 20
            """
        ),
        {"regex": _SLA006_REGEX},
    )
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_condition_bands b
               SET range_max = 19
              FROM contract.sla_definitions d
             WHERE d.id = b.sla_id
               AND d.sla_ref ~ :regex
               AND d.status = 'ACTIVE'
               AND COALESCE(b.severity_level, 0) > 0
               AND b.range_max = 20
            """
        ),
        {"regex": _SLA006_REGEX},
    )

    # 3. Fill NULL bounds on any SLA006 band with the RFP-canonical
    #    threshold of 20 working days (represented as 19 per the
    #    convention noted above). Only touches NULL — never overrides
    #    a customized value.
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_condition_bands b
               SET range_min = 19
              FROM contract.sla_definitions d
             WHERE d.id = b.sla_id
               AND d.sla_ref ~ :regex
               AND d.status = 'ACTIVE'
               AND COALESCE(b.severity_level, 0) = 0
               AND b.range_min IS NULL
            """
        ),
        {"regex": _SLA006_REGEX},
    )
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_condition_bands b
               SET range_max = 19
              FROM contract.sla_definitions d
             WHERE d.id = b.sla_id
               AND d.sla_ref ~ :regex
               AND d.status = 'ACTIVE'
               AND COALESCE(b.severity_level, 0) > 0
               AND b.range_max IS NULL
            """
        ),
        {"regex": _SLA006_REGEX},
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Only revert the classifier we set — leave band bounds alone (as
    # with 0024, reverting would re-break the evaluator and we can't
    # distinguish rows we filled from rows that always had the value).
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_definitions
               SET ld_formula_rule = NULL
             WHERE sla_ref ~ :regex
               AND ld_formula_rule = 'LADDER'
            """
        ),
        {"regex": _PMC_SLA006_REGEX},
    )
