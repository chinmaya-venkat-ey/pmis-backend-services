"""Phase A foundation — settlement/quarter aggregation + phase gating + contract-level rules.

Groundwork for the RFP-compliant SLA→LD→NPQP→AQP pipeline. All additive:
new columns are nullable, new tables are empty until Phase B/C/D populate
them. No existing data is touched.

Columns added to ``contract.sla_definitions``:

  * phase                     VARCHAR(24)   — classifies each SLA for phase
                                              gating per RFP §5.28.2.a (no
                                              resource SLA in Phase 1).
                                              Values: PHASE_1 / PHASE_2_3 /
                                              GOVERNANCE_TOOL / NONE.
  * carry_forward_severity    BOOLEAN       — RFP §5.28.3.f–g (SLA 008/009):
                                              severity persists across
                                              quarters until observation
                                              clears.
  * ld_formula_rule           VARCHAR(32)   — arithmetic family this SLA
                                              uses. Values (full set now so
                                              BSP/MSIP need no ALTER TYPE
                                              later): LADDER,
                                              PER_UNIT_TIME_DELIVERABLE,
                                              PER_UNIT_TIME_QUARTERLY,
                                              PER_OCCURRENCE, DAYS_WEIGHTED,
                                              AVAILABILITY_UPTIME. NULL
                                              during rollout — the evaluator
                                              falls back to today's behaviour
                                              until Step 2 backfills.

New tables (all in ``contract.*``):

  * sla_quarterly_aggregate   one row per (mapping, fiscal_year, quarter).
                              This is where "reset at end of reporting
                              interval" (RFP §5.28.1.c) actually happens:
                              per-SLA points sum → ladder lookup → single
                              LD % for the quarter.
  * sla_settlement_period     one row per (project, fiscal_year, quarter).
                              The quarter-close artifact: Σ LD % across
                              SLAs, capped at 10% × NPQP (§5.27.6),
                              multiplied to LD ₹, plus AQP = (PA − LD) +
                              QGR (§5.28.1.d.h). ``consequence_flags`` is
                              reserved for BSP probation / non-payable
                              flags — unused for PMU.
  * contract_phase_config     seed table mapping (contract_type,
                              deliverable_code) → phase. PMU rows are
                              seeded in the next migration; BSP/MSAP/MSIP
                              rows seeded when their configs land.
  * contract_ld_rules         per (contract_type, rule_key) parameter table
                              — LD %/week for SLA 001 (0.5), 002 (1.0), LD
                              %/day for SLA 003 (0.1), quarter cap (10.0),
                              etc. Data-driven so contract variations are
                              config, not code.

Revision ID: 0021_settlement_foundation
Revises: 0020_sla_automated_evaluation
Create Date: 2026-07-20

NOTE: the revision string must fit in ``alembic_version_contract.version_num``
which is VARCHAR(32). Descriptive filename is fine — alembic only reads the
``revision`` variable below. Prior migrations follow the same convention
(0019's file is ``0019_data_field_direction_and_full_seed.py`` but its
revision string is ``0019_dsl_seed``).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0021_settlement_foundation"       # 26 chars — fits VARCHAR(32)
down_revision = "0020_sla_automated_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. sla_definitions: 3 new columns ─────────────────────────────
    op.add_column(
        "sla_definitions",
        sa.Column("phase", sa.String(length=24), nullable=True),
        schema="contract",
    )
    op.add_column(
        "sla_definitions",
        sa.Column(
            "carry_forward_severity",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="contract",
    )
    op.add_column(
        "sla_definitions",
        sa.Column("ld_formula_rule", sa.String(length=32), nullable=True),
        schema="contract",
    )
    op.create_index(
        "ix_sla_def_phase",
        "sla_definitions", ["phase"],
        schema="contract",
    )
    op.create_index(
        "ix_sla_def_ld_formula_rule",
        "sla_definitions", ["ld_formula_rule"],
        schema="contract",
    )

    # ── 2. sla_quarterly_aggregate ────────────────────────────────────
    op.create_table(
        "sla_quarterly_aggregate",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "mapping_id", sa.String(36),
            sa.ForeignKey(
                "contract.sla_activity_mappings.id",
                ondelete="CASCADE",
                name="fk_sla_qtr_agg_mapping",
            ),
            nullable=False,
        ),
        sa.Column("sla_id", sa.String(36), nullable=False),
        sa.Column("sla_ref", sa.String(64)),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("fiscal_year", sa.Integer, nullable=False),
        sa.Column("quarter", sa.Integer, nullable=False),  # 1..4 calendar quarter
        sa.Column("quarter_start", sa.Date, nullable=False),
        sa.Column("quarter_end", sa.Date, nullable=False),
        # The three RFP roll-up outputs:
        sa.Column("accumulated_points", sa.Numeric(18, 4)),
        sa.Column("derived_severity", sa.Integer),
        sa.Column("ld_percent", sa.Numeric(9, 4)),
        # Audit trail — which evaluation_result rows fed this aggregate.
        sa.Column("source_result_ids", postgresql.ARRAY(sa.String(36))),
        # Carry-forward marker for SLA 008/009 — set when this row's
        # severity was inherited from the previous quarter's carry-forward,
        # not from observations in this quarter.
        sa.Column(
            "carried_forward",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("notes", postgresql.JSONB),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "mapping_id", "fiscal_year", "quarter",
            name="uq_sla_qtr_agg_mapping_quarter",
        ),
        schema="contract",
    )
    op.create_index(
        "ix_sla_qtr_agg_project_quarter",
        "sla_quarterly_aggregate",
        ["project_id", "fiscal_year", "quarter"],
        schema="contract",
    )
    op.create_index(
        "ix_sla_qtr_agg_sla_ref",
        "sla_quarterly_aggregate", ["sla_ref"],
        schema="contract",
    )

    # ── 3. sla_settlement_period ──────────────────────────────────────
    op.create_table(
        "sla_settlement_period",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("contract_type", sa.String(20)),
        sa.Column("fiscal_year", sa.Integer, nullable=False),
        sa.Column("quarter", sa.Integer, nullable=False),
        sa.Column("quarter_start", sa.Date, nullable=False),
        sa.Column("quarter_end", sa.Date, nullable=False),
        # Money layer — filled at quarter close.
        sa.Column("sum_ld_percent", sa.Numeric(9, 4)),      # Σ before cap
        sa.Column("capped_ld_percent", sa.Numeric(9, 4)),   # min(Σ, 10%)
        sa.Column("f_amount", sa.Numeric(18, 2)),           # planned quarterly staff payment
        sa.Column("qgr_amount", sa.Numeric(18, 2)),         # Phase 1 QGR
        sa.Column("npqp", sa.Numeric(18, 2)),               # F + QGR
        sa.Column("ld_amount", sa.Numeric(18, 2)),          # capped% × NPQP
        sa.Column("pa_amount", sa.Numeric(18, 2)),          # actual resource deployment payment
        sa.Column("aqp_amount", sa.Numeric(18, 2)),         # (PA − LD) + QGR
        # Lifecycle.
        sa.Column(
            "status", sa.String(24), nullable=False,
            server_default=sa.text("'open'"),
        ),  # open | auto_closed | overridden | invoiced
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_by", sa.String(36)),
        sa.Column("override_reason", sa.Text),
        sa.Column("source_aggregate_ids", postgresql.ARRAY(sa.String(36))),
        # BSP probation / non-payable / traffic-cap flags. Unused for PMU
        # today; the schema is here so BSP lands without a migration when
        # its evaluator is added. Shape: {"probation": true,
        # "since_quarter": "2026-Q3", "non_payable_txn_pct": 100}.
        sa.Column(
            "consequence_flags", postgresql.JSONB,
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "project_id", "fiscal_year", "quarter",
            name="uq_sla_settlement_project_quarter",
        ),
        schema="contract",
    )
    op.create_index(
        "ix_sla_settlement_status",
        "sla_settlement_period", ["status"],
        schema="contract",
    )
    op.create_index(
        "ix_sla_settlement_project",
        "sla_settlement_period", ["project_id"],
        schema="contract",
    )

    # ── 4. contract_phase_config ──────────────────────────────────────
    op.create_table(
        "contract_phase_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("contract_type", sa.String(20), nullable=False),
        sa.Column("deliverable_code", sa.String(32), nullable=False),  # 'D1'..'D13' etc.
        sa.Column("phase", sa.String(24), nullable=False),
        # Cadence / QGR eligibility hints so the settlement service knows
        # whether to expect QGR for this phase (Phase 1 = yes per RFP §5.23.2).
        sa.Column(
            "qgr_eligible", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        # 'MILESTONE' — pays on deliverable completion (Phase 1);
        # 'QUARTERLY' — pays on quarter close from staff cost (Phase 2/3);
        # 'ANNUAL'    — pays annually (Governance tool D11).
        sa.Column("payment_cadence", sa.String(16), nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "contract_type", "deliverable_code",
            name="uq_contract_phase_config",
        ),
        schema="contract",
    )
    op.create_index(
        "ix_contract_phase_config_type",
        "contract_phase_config", ["contract_type"],
        schema="contract",
    )

    # ── 5. contract_ld_rules ──────────────────────────────────────────
    op.create_table(
        "contract_ld_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("contract_type", sa.String(20), nullable=False),
        sa.Column("rule_key", sa.String(64), nullable=False),   # e.g. 'sla_001_rate_pct_per_week'
        sa.Column("rule_value", sa.Numeric(12, 4), nullable=False),
        sa.Column("unit", sa.String(16)),                       # 'PERCENT' | 'DAYS' | 'WEEKS' | 'INR'
        sa.Column("description", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "contract_type", "rule_key",
            name="uq_contract_ld_rules",
        ),
        schema="contract",
    )
    op.create_index(
        "ix_contract_ld_rules_type",
        "contract_ld_rules", ["contract_type"],
        schema="contract",
    )


def downgrade() -> None:
    op.drop_index("ix_contract_ld_rules_type", table_name="contract_ld_rules", schema="contract")
    op.drop_table("contract_ld_rules", schema="contract")

    op.drop_index("ix_contract_phase_config_type", table_name="contract_phase_config", schema="contract")
    op.drop_table("contract_phase_config", schema="contract")

    op.drop_index("ix_sla_settlement_project", table_name="sla_settlement_period", schema="contract")
    op.drop_index("ix_sla_settlement_status", table_name="sla_settlement_period", schema="contract")
    op.drop_table("sla_settlement_period", schema="contract")

    op.drop_index("ix_sla_qtr_agg_sla_ref", table_name="sla_quarterly_aggregate", schema="contract")
    op.drop_index("ix_sla_qtr_agg_project_quarter", table_name="sla_quarterly_aggregate", schema="contract")
    op.drop_table("sla_quarterly_aggregate", schema="contract")

    op.drop_index("ix_sla_def_ld_formula_rule", table_name="sla_definitions", schema="contract")
    op.drop_index("ix_sla_def_phase", table_name="sla_definitions", schema="contract")
    op.drop_column("sla_definitions", "ld_formula_rule", schema="contract")
    op.drop_column("sla_definitions", "carry_forward_severity", schema="contract")
    op.drop_column("sla_definitions", "phase", schema="contract")
