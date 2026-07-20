"""Seed PMU phase / LD-rule config + backfill sla_definitions classifiers.

Fills the three empty seed tables from migration 0021 for PMU only:

  * contract_phase_config   PMU deliverable D1..D13 → phase + payment_cadence
  * contract_ld_rules       PMU per-week / per-day rates + 10% cap
  * sla_definitions         .phase / .ld_formula_rule / .carry_forward_severity
                            classified per RFP §5.28.2-§5.28.4 for every
                            active PMU SLA row (canonical + timestamped
                            variants — matched via regex on ``sla_ref``).

BSP / MSAP / MSIP configs land in later migrations (per the roadmap).

Backwards-compatible: everything is INSERT ... ON CONFLICT DO NOTHING and
UPDATE ... WHERE column IS NULL, so re-running is a no-op and does not
clobber values another migration or ops may have set.

Revision ID: 0022_seed_pmu
Revises: 0021_settlement_foundation
Create Date: 2026-07-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0022_seed_pmu"                    # 13 chars — well under VARCHAR(32)
down_revision = "0021_settlement_foundation"
branch_labels = None
depends_on = None


# ── PMU deliverable → phase map (RFP §5.28.2 / §5.28.3 / §5.28.4) ──────
# qgr_eligible marks deliverables whose phase originates QGR under
# RFP §5.23.2. NpqpService reads project_qgr_config only for
# deliverables belonging to a qgr_eligible phase.
PMU_PHASE_CONFIG = [
    # (deliverable_code, phase, qgr_eligible, payment_cadence, notes)
    ("D1", "PHASE_1", True, "MILESTONE", "Project Init / Governance framework"),
    ("D2", "PHASE_1", True, "MILESTONE", "Assessment & baseline"),
    ("D3", "PHASE_1", True, "MILESTONE", "Roadmap / architecture"),
    ("D4", "PHASE_1", True, "MILESTONE", "Governance tool blueprint"),
    ("D5", "PHASE_1", True, "MILESTONE", "Change management plan"),
    ("D6", "PHASE_1", True, "MILESTONE", "Vendor selection support"),
    ("D7", "PHASE_1", True, "MILESTONE", "Procurement support"),
    ("D8", "PHASE_1", True, "MILESTONE", "MSP selection / D8 milestone"),
    ("D9", "PHASE_2_3", False, "QUARTERLY", "Transition & Takeover — staff-cost quarterly"),
    ("D10", "PHASE_2_3", False, "QUARTERLY", "Project Management — staff-cost quarterly"),
    ("D11", "GOVERNANCE_TOOL", False, "ANNUAL", "Governance tool — annual disbursal"),
    ("D12", "NONE", False, "QUARTERLY", "Resource contract — spans all phases"),
    ("D13", "NONE", False, "QUARTERLY", "Resource contract — spans all phases"),
]

# ── PMU LD parameters (RFP §5.27.6, §5.28.2–4) ────────────────────────
PMU_LD_RULES = [
    # (rule_key, rule_value, unit, description)
    ("sla_001_rate_pct_per_week", 0.5,  "PERCENT",
     "RFP §5.28.2.b — 0.5% of deliverable cost per week of delay (SLA 001 non-submission)"),
    ("sla_002_rate_pct_per_week", 1.0,  "PERCENT",
     "RFP §5.28.2.c — 1.0% of deliverable cost per week of delay (SLA 002 defects)"),
    ("sla_003_rate_pct_per_day",  0.1,  "PERCENT",
     "RFP §5.28.3.a — 0.1% of NPQP per day of delay (SLA 003 query resolution)"),
    ("quarterly_ld_cap_pct",     10.0,  "PERCENT",
     "RFP §5.27.6 — cumulative LD per quarter capped at 10% of NPQP"),
]

# ── PMU sla_definitions classifier backfill ───────────────────────────
# sla_ref may be canonical ('PMU-SLA001') or timestamped
# ('PMU-SLA001-20260715...' / 'PMU_SLA001_20260717...'). Regex captures
# both hyphen and underscore separators after PMU and the SLA number.
# (phase, ld_formula_rule, carry_forward, ref_regex, comment)
PMU_SLA_CLASSIFIERS = [
    ("PHASE_1",         "PER_UNIT_TIME_DELIVERABLE", False,
     r"^PMU[-_]SLA001", "SLA 001 — non-submission of deliverable"),
    ("PHASE_1",         "PER_UNIT_TIME_DELIVERABLE", False,
     r"^PMU[-_]SLA002", "SLA 002 — deliverable defects not rectified"),
    ("PHASE_2_3",       "PER_UNIT_TIME_QUARTERLY",   False,
     r"^PMU[-_]SLA003", "SLA 003 — query resolution beyond 3 days"),
    ("PHASE_2_3",       "PER_OCCURRENCE",            False,
     r"^PMU[-_]SLA004", "SLA 004 — incorrect recommendation on MSP deliverables"),
    ("NONE",            "LADDER",                    False,
     r"^PMU[-_]SLA005", "SLA 005 — resource replacements per quarter"),
    ("NONE",            "LADDER",                    False,
     r"^PMU[-_]SLA006", "SLA 006 — KT overlap on replacement"),
    ("NONE",            "LADDER",                    False,
     r"^PMU[-_]SLA007", "SLA 007 — minimum resource availability"),
    ("NONE",            "LADDER",                    True,   # ← carry-forward
     r"^PMU[-_]SLA008", "SLA 008 — onboarding of additional resources (carries SL4 fwd)"),
    ("NONE",            "LADDER",                    True,   # ← carry-forward
     r"^PMU[-_]SLA009", "SLA 009 — replacement onboarding delay (carries SL2 fwd)"),
    ("GOVERNANCE_TOOL", "LADDER",                    False,
     r"^PMU[-_]SLA010", "SLA 010 — Governance tool deployment"),
    ("GOVERNANCE_TOOL", "LADDER",                    False,
     r"^PMU[-_]SLA011", "SLA 011 — Governance tool uptime"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. contract_phase_config seed (PMU) ─────────────────────────
    conn.execute(
        sa.text("""
            INSERT INTO contract.contract_phase_config
                (id, contract_type, deliverable_code, phase, qgr_eligible,
                 payment_cadence, notes)
            VALUES
                (gen_random_uuid()::text, 'PMU', :dc, :ph, :qgr, :cad, :notes)
            ON CONFLICT (contract_type, deliverable_code) DO NOTHING
        """),
        [
            {"dc": dc, "ph": ph, "qgr": qgr, "cad": cad, "notes": notes}
            for (dc, ph, qgr, cad, notes) in PMU_PHASE_CONFIG
        ],
    )

    # ── 2. contract_ld_rules seed (PMU) ─────────────────────────────
    conn.execute(
        sa.text("""
            INSERT INTO contract.contract_ld_rules
                (id, contract_type, rule_key, rule_value, unit, description)
            VALUES
                (gen_random_uuid()::text, 'PMU', :rk, :rv, :unit, :desc)
            ON CONFLICT (contract_type, rule_key) DO NOTHING
        """),
        [
            {"rk": rk, "rv": rv, "unit": unit, "desc": desc}
            for (rk, rv, unit, desc) in PMU_LD_RULES
        ],
    )

    # ── 3. sla_definitions classifier backfill (PMU) ────────────────
    # Only sets NULL cells — never clobbers a value already stored.
    for (phase, rule, carry_fwd, regex, _comment) in PMU_SLA_CLASSIFIERS:
        conn.execute(
            sa.text("""
                UPDATE contract.sla_definitions
                   SET phase                  = COALESCE(phase, :phase),
                       ld_formula_rule        = COALESCE(ld_formula_rule, :rule),
                       carry_forward_severity = CASE
                           WHEN carry_forward_severity IS TRUE THEN TRUE
                           ELSE :carry_fwd
                       END
                 WHERE contract_type = 'PMU'
                   AND sla_ref ~ :regex
                   AND status = 'ACTIVE'
            """),
            {"phase": phase, "rule": rule, "carry_fwd": carry_fwd, "regex": regex},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM contract.contract_ld_rules WHERE contract_type='PMU'"))
    conn.execute(sa.text("DELETE FROM contract.contract_phase_config WHERE contract_type='PMU'"))
    conn.execute(sa.text("""
        UPDATE contract.sla_definitions
           SET phase = NULL,
               ld_formula_rule = NULL,
               carry_forward_severity = FALSE
         WHERE contract_type = 'PMU'
    """))
