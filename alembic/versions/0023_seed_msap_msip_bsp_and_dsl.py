"""Seed MSAP/MSIP/BSP configs + move carry-forward severity from code to DSL.

Two things bundled (both additive, no schema changes):

1. **Data-drive the carry-forward severity level** (RFP §5.28.3.f/g).
   Previously ``_CARRY_FORWARD_SEVERITY_BY_FAMILY = {8: 4, 9: 2}`` was
   hardcoded in ``sla_compliance_service.py``. This migration seeds the
   equivalent rows in ``contract_ld_rules``:
     PMU sla_008_carry_forward_severity = 4
     PMU sla_009_carry_forward_severity = 2
   The code fix (companion PR) reads these instead of the dict.

2. **Seed BSP / MSAP / MSIP** so all 4 contracts land on the same
   settlement/rollup machinery:
     * ``contract_ld_rules.quarterly_ld_cap_pct = 10`` per contract
       (RFP §5.27.6 in PMU; MSAP Annexure-3E; MSIP §1.5.5; BSP §22).
     * ``sla_definitions.phase = 'NONE'`` (SLAs apply contract-wide, not
       per-deliverable) and ``ld_formula_rule = 'LADDER'`` for every
       canonical + timestamped variant of MSAP/MSIP/BSP SLAs.
     * ``contract_phase_config`` intentionally left empty for these
       contracts — none of them use the D1..Dn deliverable phase model
       PMU uses. Phase-gate fails-open when no config row exists.

Not seeded here (deliberate deferrals — evaluator changes required):
  * BSP DAYS_WEIGHTED formula (Σ days_in_bracket × %rate / days_in_quarter)
    — the band_accumulation evaluator surfaces days-in-band and rates but
    the divide-by-quarter-days step isn't wired to _ld_money yet.
  * MSIP AVAILABILITY_UPTIME formula (1 − (downtime − planned_downtime)
    / total_time) — no evaluator exists; MSIP availability SLAs will
    stay unevaluated until that lands.

Both those SLAs still classify + participate in phase-gate, but their
per-observation LD % stays 0 until the evaluators ship. Marked in the
seed notes.

Idempotent: all inserts use ON CONFLICT DO NOTHING; UPDATEs COALESCE
on NULL so re-running never clobbers a value ops manually set.

Revision ID: 0023_seed_all_contracts
Revises: 0022_seed_pmu
Create Date: 2026-07-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0023_seed_all_contracts"    # 22 chars — fits VARCHAR(32)
down_revision = "0022_seed_pmu"
branch_labels = None
depends_on = None


# ── Per-contract LD-rule seeds ────────────────────────────────────────
# quarterly_ld_cap_pct is the RFP §5.27.6-equivalent cap for each contract.
# PMU carry-forward severities (SLA 008/009) — replace the hardcoded dict.
CONTRACT_LD_RULES = [
    # (contract_type, rule_key, rule_value, unit, description)
    ("PMU",  "sla_008_carry_forward_severity", 4,  "SEVERITY",
     "RFP §5.28.3.f — SLA 008 (onboarding of additional resources): severity 4 "
     "applied every quarter thereafter till actual onboarding."),
    ("PMU",  "sla_009_carry_forward_severity", 2,  "SEVERITY",
     "RFP §5.28.3.g — SLA 009 (delay in replacement onboarding): severity 2 "
     "applied every quarter till replacement is onboarded."),

    ("MSAP", "quarterly_ld_cap_pct",          10,  "PERCENT",
     "MSAP Annexure-3E — cumulative LD per quarter capped at 10% of PQP "
     "(Planned Quarterly Payment; no QGR concept in MSAP)."),

    ("MSIP", "quarterly_ld_cap_pct",          10,  "PERCENT",
     "MSIP §1.5.5 — quarterly LD cap 10%."),

    ("BSP",  "quarterly_ld_cap_pct",          10,  "PERCENT",
     "BSP contract §22 — quarterly LD cap 10%."),
]


# ── Per-contract SLA-family classifier backfill ───────────────────────
# All 3 non-PMU contracts have SLAs that apply contract-wide (phase=NONE)
# and use the standard LADDER dispatch. Regex matches both hyphen and
# underscore family separators, and both canonical (MSAP-SLA001) and
# timestamped (MSAP-SLA001-20260715...) variants.
SLA_BACKFILLS = [
    # (contract_type, regex, phase, ld_formula_rule, comment)
    ("MSAP", r"^MSAP[-_]SLA\d+",   "NONE", "LADDER",
     "MSAP SLAs — all points-ladder per MSAP Annexure-3E"),
    ("MSIP", r"^MSIP[-_]SLA\d+",   "NONE", "LADDER",
     "MSIP SLAs — availability SLAs default to LADDER until "
     "AVAILABILITY_UPTIME evaluator lands"),
    ("BSP",  r"^BSP[-_]SLA\d+",    "NONE", "LADDER",
     "BSP SLAs — days-weighted SLAs default to LADDER until "
     "DAYS_WEIGHTED evaluator lands"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. contract_ld_rules seeds ─────────────────────────────────
    conn.execute(
        sa.text("""
            INSERT INTO contract.contract_ld_rules
                (id, contract_type, rule_key, rule_value, unit, description)
            VALUES
                (gen_random_uuid()::text, :ct, :rk, :rv, :unit, :desc)
            ON CONFLICT (contract_type, rule_key) DO NOTHING
        """),
        [
            {"ct": ct, "rk": rk, "rv": rv, "unit": unit, "desc": desc}
            for (ct, rk, rv, unit, desc) in CONTRACT_LD_RULES
        ],
    )

    # ── 2. sla_definitions backfill for MSAP/MSIP/BSP ───────────────
    for (contract_type, regex, phase, rule, _comment) in SLA_BACKFILLS:
        conn.execute(
            sa.text("""
                UPDATE contract.sla_definitions
                   SET phase                  = COALESCE(phase, :phase),
                       ld_formula_rule        = COALESCE(ld_formula_rule, :rule)
                 WHERE contract_type = :ct
                   AND sla_ref ~ :regex
                   AND status = 'ACTIVE'
            """),
            {"ct": contract_type, "phase": phase, "rule": rule, "regex": regex},
        )


def downgrade() -> None:
    conn = op.get_bind()
    # Remove seeded rules
    conn.execute(sa.text("""
        DELETE FROM contract.contract_ld_rules
         WHERE (contract_type, rule_key) IN (
           ('PMU',  'sla_008_carry_forward_severity'),
           ('PMU',  'sla_009_carry_forward_severity'),
           ('MSAP', 'quarterly_ld_cap_pct'),
           ('MSIP', 'quarterly_ld_cap_pct'),
           ('BSP',  'quarterly_ld_cap_pct')
         )
    """))
    # Unset backfilled classifiers (only what we set; leave PMU untouched)
    for (contract_type, regex, _phase, _rule, _comment) in SLA_BACKFILLS:
        conn.execute(sa.text("""
            UPDATE contract.sla_definitions
               SET phase = NULL, ld_formula_rule = NULL
             WHERE contract_type = :ct
               AND sla_ref ~ :regex
        """), {"ct": contract_type, "regex": regex})
