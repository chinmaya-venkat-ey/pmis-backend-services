"""SLA 010 (Governance tool deployment) — PMC row bounds + classifier fix.

Per RFP §5.28.4.a — SLA 010 is a tiered severity SLA on deployment-day
variance from the T0+6-month milestone:

    delay <= 0           →  Sev 0 (on time)
    delay in P+1..P+7    →  Sev 1
    delay in P+8..P+14   →  Sev 2
    delay in P+15..P+21  →  Sev 3
    delay > P+21         →  Sev 4

Canonical PMU-SLA010 is correctly configured (LADDER, proper bounds on
all 5 bands). The problem is on PMC-SLA010_ and its wizard-onboarded
variants:

  * ``ld_formula_rule`` is NULL on every PMC-SLA010 row — falls out
    of the Track B whitelist and gets excluded from every settlement.

  * PMC-SLA010_ canonical has the correct bounds on bands 2-5 but the
    first band ("<= T0 + 6 Months") has NULL range_min / range_max.
    Because ``_value_in_band`` short-circuits to True when both bounds
    are NULL, the baseline band matches EVERY observation → the
    evaluator picks it first (sort_order=1) → the SLA always returns
    sev=0 regardless of how late the deployment actually is.

Migration 0027:

  1. Sets ``ld_formula_rule = 'LADDER'`` on every ACTIVE PMC-SLA010 row
     whose classifier is NULL (canonical + timestamped variants).
     LADDER is the correct dispatch — the RFP semantic is single-band-hit
     per measurement, matching what the existing point_accumulation
     LADDER path already handles.

  2. Sets ``range_max = 0`` on PMC-SLA010_ canonical's L0 baseline
     band so that only observed <= 0 (on-time / early) matches the
     baseline. Guarded on ``range_min IS NULL AND range_max IS NULL``
     to avoid touching an ops-customised band.

Left alone (deliberate, per RFP verification):

  * PMC-SLA010 timestamped variants with generic "L0 any"/"L4 any"
    band labels — labels do NOT encode RFP thresholds, so patching
    bounds would require guessing intent. These SLAs need to be
    re-onboarded on the FE with proper values.

  * PMC-SLA002 reaching 20% at week 20 — verified against RFP §5.28.2.c
    (1%/week without an explicit per-SLA cap) and §5.27.6 (10% cap is
    on cumulative quarterly Track B LDs against NPQP, not per-deliverable
    Track A SLAs). 20% output is the literal RFP formula. Not a bug.

  * PMC-SLA001-20260715112620 configured at 1%/week (RFP §5.28.2.b says
    0.5%/week) — likely wizard mis-onboarding but could be an
    intentional custom SLA. Flagged for ops decision; no automated patch.

  * PMU-SLA009-20260715133105 with only an "L0 any" band — RFP §5.28.3.g
    wants sev=0/sev=2 tiers, but the variant only has the baseline. Fix
    requires INSERTING a missing L2 escalation band (UUID + sort order
    + severity mapping); risky to do blindly since the variant may be
    intentional. Flagged for ops decision.

Revision ID: 0027_sla010_pmc
Revises:     0026_sla005_rev
Create Date: 2026-07-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0027_sla010_pmc"           # 16 chars — fits VARCHAR(32)
down_revision = "0026_sla005_rev"
branch_labels = None
depends_on = None


_PMC_SLA010_REGEX = r"^PMC[-_]SLA010([-_].*|_?)?$"


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Set ld_formula_rule='LADDER' on every PMC-SLA010 row where NULL.
    #    Track B whitelist already includes LADDER — this makes PMC-SLA010
    #    participate in the quarter settlement.
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
        {"regex": _PMC_SLA010_REGEX},
    )

    # 2. Fix PMC-SLA010_ canonical: the first band ("<= T0+6 Months") has
    #    NULL bounds → matches every observation. Set range_max=0 so it
    #    only matches on-time / early observations. Only touches the
    #    canonical row (identified by sla_ref='PMC-SLA010_') and only
    #    when the band currently has both bounds NULL — safe against
    #    ops overrides. Bands 2-5 on this canonical already have proper
    #    RFP-correct bounds (7, 14, 21).
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_condition_bands b
               SET range_max = 0
              FROM contract.sla_definitions d
             WHERE d.id = b.sla_id
               AND d.sla_ref = 'PMC-SLA010_'
               AND d.status = 'ACTIVE'
               AND COALESCE(b.severity_level, 0) = 0
               AND b.range_max IS NULL
               AND b.range_min IS NULL
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Revert classifier only — leave the band fix in place (it's
    # RFP-correct and there's no way to distinguish rows we filled
    # from any that always had range_max=0).
    conn.execute(
        sa.text(
            """
            UPDATE contract.sla_definitions
               SET ld_formula_rule = NULL
             WHERE sla_ref ~ :regex
               AND ld_formula_rule = 'LADDER'
            """
        ),
        {"regex": _PMC_SLA010_REGEX},
    )
