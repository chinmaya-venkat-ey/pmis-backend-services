"""Phase 1 — create contract schema with all 17 tables + formula_library seed data.

Revision ID: 0001_phase1
Revises:
Create Date: 2026-05-26
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "0001_phase1"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# formula_library seed rows — 4 formula types
# ---------------------------------------------------------------------------

_BAND_ACCUMULATION_SCHEMA = {
    "type": "object",
    "required": ["count_unit", "period_unit", "aggregate_method"],
    "properties": {
        "count_unit": {
            "type": "string",
            "enum": ["DAY", "MONTH", "INSTANCE"],
        },
        "period_unit": {
            "type": "string",
            "enum": ["QUARTER", "MONTH", "YEAR"],
        },
        "aggregate_method": {
            "type": "string",
            "enum": ["RATE", "SUM"],
            "description": (
                "RATE = divide cumulative LD by period_units (BSP quarterly formula). "
                "SUM = add monthly LDs directly (MSIP)."
            ),
        },
        "cap_percent": {"type": "number", "minimum": 0},
    },
}

_POINT_ACCUMULATION_SCHEMA = {
    "type": "object",
    "required": ["period_unit"],
    "properties": {
        "period_unit": {"type": "string", "enum": ["MONTH", "QUARTER", "YEAR"]},
        "max_severity_per_interval": {"type": "integer", "default": 4},
        "escalation_rate_days": {
            "type": "integer",
            "description": "TAT SLAs: every N days beyond TAT, severity escalates.",
        },
        "escalation_amount": {
            "type": "integer",
            "description": "Severity increment per escalation period (general).",
        },
        "escalation_amount_blocker_critical": {
            "type": "integer",
            "description": "Severity increment per escalation for Blocker/Critical defects (MSAP SLA 015).",
        },
        "escalation_amount_major": {
            "type": "integer",
            "description": "Severity increment per escalation for Major defects (MSAP SLA 015).",
        },
        "cap_percent": {"type": "number", "minimum": 0},
    },
}

_FIXED_ESCALATION_SCHEMA = {
    "type": "object",
    "required": ["period_unit"],
    "properties": {
        "period_unit": {
            "type": "string",
            "enum": ["MONTH", "QUARTER", "YEAR", "ONE_TIME"],
        },
        "milestone_type": {
            "type": "string",
            "enum": ["DATE", "NUMERIC", "DELAY_DAYS"],
        },
        "cap_percent": {"type": "number", "minimum": 0},
    },
}

_WAC_SCHEMA = {
    "type": "object",
    "required": ["weights", "variation_percent_per_severity", "period_unit"],
    "properties": {
        "weights": {
            "type": "object",
            "required": ["blocker", "critical", "major", "minor"],
            "properties": {
                "blocker": {"type": "number", "default": 8},
                "critical": {"type": "number", "default": 4},
                "major": {"type": "number", "default": 2},
                "minor": {"type": "number", "default": 1},
            },
        },
        "variation_percent_per_severity": {
            "type": "number",
            "description": (
                "Every N% WAC above baseline increases severity by 1. "
                "MSAP SLA 016 = 5, MSAP SLA 017 = 10."
            ),
        },
        "exclusion_months": {
            "type": "integer",
            "default": 12,
            "description": "Ignore defects from incumbent MSP for first N months (MSAP 12-month rule).",
        },
        "min_sample_size": {
            "type": "integer",
            "description": "Minimum request count before defect classification applies (MSAP SLA 017 = 500).",
        },
        "period_unit": {"type": "string", "enum": ["MONTH", "QUARTER"]},
    },
}

_FORMULA_SEED = [
    {
        "formula_type": "band_accumulation",
        "display_name": "Band Accumulation",
        "description": (
            "Counts units (days/months/instances) in each severity band and computes "
            "LD as Σ(units × band_rate%). aggregate_method=RATE divides by period_units "
            "(BSP quarterly formula); SUM adds monthly LDs directly (MSIP)."
        ),
        "parameter_schema": _BAND_ACCUMULATION_SCHEMA,
        "requires_bands": True,
        "requires_lookup": False,
    },
    {
        "formula_type": "point_accumulation",
        "display_name": "Point Accumulation",
        "description": (
            "Maps each severity level to a points value (negative allowed for reward — "
            "MSAP severity 0 = -2 pts). Points accumulate over the reporting period; "
            "total points → LD% via contract_scoring_config.points_ld_map."
        ),
        "parameter_schema": _POINT_ACCUMULATION_SCHEMA,
        "requires_bands": True,
        "requires_lookup": False,
    },
    {
        "formula_type": "fixed_escalation",
        "display_name": "Fixed Escalation",
        "description": (
            "Maps a milestone delay tier or breach threshold to a fixed LD% via "
            "sla_lookup_rows. Used for MSAP milestone SLAs and BSP SLA 014."
        ),
        "parameter_schema": _FIXED_ESCALATION_SCHEMA,
        "requires_bands": False,
        "requires_lookup": True,
    },
    {
        "formula_type": "wac",
        "display_name": "Weighted Average Count (WAC)",
        "description": (
            "WAC = Σ(weight × defect_count_by_type) / (total_defects × num_applications). "
            "Severity = max(0, floor((WAC - baseline) / variation_percent_per_severity)). "
            "Rolling baseline updates monthly when WAC < current baseline. "
            "Used by MSAP SLA 016 (variation 5%) and SLA 017 (variation 10%)."
        ),
        "parameter_schema": _WAC_SCHEMA,
        "requires_bands": False,
        "requires_lookup": False,
    },
]


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # Create contract schema
    # -----------------------------------------------------------------------
    op.execute("CREATE SCHEMA IF NOT EXISTS contract")

    # -----------------------------------------------------------------------
    # 1. formula_library
    # -----------------------------------------------------------------------
    op.create_table(
        "formula_library",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("formula_type", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("parameter_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requires_bands", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("requires_lookup", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_formula_library_formula_type", "formula_library", ["formula_type"], unique=True, schema="contract")
    op.create_index("ix_formula_library_is_active", "formula_library", ["is_active"], schema="contract")

    # -----------------------------------------------------------------------
    # 2. contracts
    # -----------------------------------------------------------------------
    op.create_table(
        "contracts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("contract_ref", sa.String(100), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("vendor_name", sa.String(255), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date),
        sa.Column("total_value", sa.Numeric(18, 4)),
        sa.Column("currency", sa.String(10), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("quarterly_ld_cap_percent", sa.Numeric(5, 2)),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(36)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_contracts_contract_ref", "contracts", ["contract_ref"], unique=True, schema="contract")
    op.create_index("ix_contracts_status", "contracts", ["status"], schema="contract")
    op.create_index("ix_contracts_vendor_name", "contracts", ["vendor_name"], schema="contract")

    # -----------------------------------------------------------------------
    # 3. contract_scoring_config
    # -----------------------------------------------------------------------
    op.create_table(
        "contract_scoring_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "contract_id", sa.String(36),
            sa.ForeignKey("contract.contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("severity_points_map", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("points_ld_map", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "applies_to_formulas",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default=sa.text("ARRAY['point_accumulation','wac']::varchar[]"),
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_csc_contract_id", "contract_scoring_config", ["contract_id"], unique=True, schema="contract")

    # -----------------------------------------------------------------------
    # 4. contract_phases
    # -----------------------------------------------------------------------
    op.create_table(
        "contract_phases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "contract_id", sa.String(36),
            sa.ForeignKey("contract.contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phase_name", sa.String(255), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_contract_phases_contract_id", "contract_phases", ["contract_id"], schema="contract")
    op.create_index("ix_contract_phases_is_active", "contract_phases", ["is_active"], schema="contract")

    # -----------------------------------------------------------------------
    # 5. sla_definitions
    # -----------------------------------------------------------------------
    op.create_table(
        "sla_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "contract_id", sa.String(36),
            sa.ForeignKey("contract.contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "phase_id", sa.String(36),
            sa.ForeignKey("contract.contract_phases.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "formula_id", sa.String(36),
            sa.ForeignKey("contract.formula_library.id"),
            nullable=False,
        ),
        sa.Column("sla_ref", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("measurement_interval", sa.String(30), nullable=False, server_default="MONTHLY"),
        sa.Column("reporting_interval", sa.String(30), nullable=False, server_default="QUARTERLY"),
        sa.Column("baseline_type", sa.String(30), nullable=False, server_default="STATIC"),
        sa.Column("compound_metric_rule", sa.String(30), nullable=False, server_default="INDEPENDENT"),
        sa.Column("ld_aggregation_method", sa.String(20), nullable=False, server_default="SUM"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_until", sa.Date),
        sa.Column("dsl_source", sa.Text),
        sa.Column("dsl_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(36)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_sla_def_contract_id", "sla_definitions", ["contract_id"], schema="contract")
    op.create_index("ix_sla_def_contract_sla_ref", "sla_definitions", ["contract_id", "sla_ref"], unique=True, schema="contract")
    op.create_index("ix_sla_def_formula_id", "sla_definitions", ["formula_id"], schema="contract")
    op.create_index("ix_sla_def_status", "sla_definitions", ["status"], schema="contract")
    op.create_index("ix_sla_def_phase_id", "sla_definitions", ["phase_id"], schema="contract")

    # -----------------------------------------------------------------------
    # 6. sla_metrics
    # -----------------------------------------------------------------------
    op.create_table(
        "sla_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "sla_id", sa.String(36),
            sa.ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_key", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("target_numeric", sa.Numeric(18, 6)),
        sa.Column("target_date", sa.Date),
        sa.Column("direction", sa.String(20), nullable=False, server_default="LOWER_BETTER"),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_sla_metrics_sla_id", "sla_metrics", ["sla_id"], schema="contract")
    op.create_index("ix_sla_metrics_sla_metric_key", "sla_metrics", ["sla_id", "metric_key"], unique=True, schema="contract")

    # -----------------------------------------------------------------------
    # 7. sla_guard_conditions
    # -----------------------------------------------------------------------
    op.create_table(
        "sla_guard_conditions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "sla_id", sa.String(36),
            sa.ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_key", sa.String(100), nullable=False),
        sa.Column("operator", sa.String(10), nullable=False),
        sa.Column("threshold_value", sa.Numeric(18, 6), nullable=False),
        sa.Column("threshold_unit", sa.String(30)),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("action_description", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_sla_guard_conditions_sla_id", "sla_guard_conditions", ["sla_id"], schema="contract")

    # -----------------------------------------------------------------------
    # 8. sla_parameter_values
    # -----------------------------------------------------------------------
    op.create_table(
        "sla_parameter_values",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "sla_id", sa.String(36),
            sa.ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("param_key", sa.String(100), nullable=False),
        sa.Column("param_value", sa.String(500), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_sla_param_values_sla_id", "sla_parameter_values", ["sla_id"], schema="contract")
    op.create_index("ix_sla_param_values_sla_key", "sla_parameter_values", ["sla_id", "param_key"], unique=True, schema="contract")

    # -----------------------------------------------------------------------
    # 9. sla_condition_bands
    # -----------------------------------------------------------------------
    op.create_table(
        "sla_condition_bands",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "sla_id", sa.String(36),
            sa.ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_key", sa.String(100), nullable=False),
        sa.Column("band_label", sa.String(50), nullable=False),
        sa.Column("range_min", sa.Numeric(18, 6)),
        sa.Column("range_max", sa.Numeric(18, 6)),
        sa.Column("range_unit", sa.String(30)),
        sa.Column("rate_percent", sa.Numeric(8, 4)),
        sa.Column("points_contribution", sa.Numeric(6, 2)),
        sa.Column("fixed_amount", sa.Numeric(18, 4)),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_sla_cond_bands_sla_id", "sla_condition_bands", ["sla_id"], schema="contract")
    op.create_index("ix_sla_cond_bands_sla_metric", "sla_condition_bands", ["sla_id", "metric_key"], schema="contract")

    # -----------------------------------------------------------------------
    # 10. sla_lookup_rows
    # -----------------------------------------------------------------------
    op.create_table(
        "sla_lookup_rows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "sla_id", sa.String(36),
            sa.ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lookup_key", sa.String(200), nullable=False),
        sa.Column("lookup_value", sa.Numeric(18, 6), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_sla_lookup_rows_sla_id", "sla_lookup_rows", ["sla_id"], schema="contract")

    # -----------------------------------------------------------------------
    # 11. sla_dsl_versions
    # -----------------------------------------------------------------------
    op.create_table(
        "sla_dsl_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "sla_id", sa.String(36),
            sa.ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("dsl_text", sa.Text, nullable=False),
        sa.Column("change_reason", sa.Text),
        sa.Column("authored_by", sa.String(36)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_sla_dsl_versions_sla_id", "sla_dsl_versions", ["sla_id"], schema="contract")
    op.create_index("ix_sla_dsl_versions_sla_version", "sla_dsl_versions", ["sla_id", "version"], unique=True, schema="contract")

    # -----------------------------------------------------------------------
    # 12. sla_asl_snapshots
    # -----------------------------------------------------------------------
    op.create_table(
        "sla_asl_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "sla_id", sa.String(36),
            sa.ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dsl_version_id", sa.String(36),
            sa.ForeignKey("contract.sla_dsl_versions.id"),
            nullable=False,
        ),
        sa.Column("asl_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parser_version", sa.String(20), nullable=False),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_sla_asl_snapshots_sla_id", "sla_asl_snapshots", ["sla_id"], schema="contract")
    op.create_index("ix_sla_asl_snapshots_is_current", "sla_asl_snapshots", ["is_current"], schema="contract")

    # -----------------------------------------------------------------------
    # 13. metric_observations
    # -----------------------------------------------------------------------
    op.create_table(
        "metric_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "sla_id", sa.String(36),
            sa.ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_key", sa.String(100), nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("observed_value", sa.Numeric(18, 6), nullable=False),
        sa.Column("observed_unit", sa.String(30), nullable=False),
        sa.Column("baseline_used", sa.Numeric(18, 6)),
        sa.Column("excluded_from_sla", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("exclusion_reason", sa.String(100)),
        sa.Column("additional_inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("data_source", sa.String(30)),
        sa.Column("submitted_by", sa.String(36)),
        sa.Column("approved_by", sa.String(36)),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("sla_id", "metric_key", "period_start", "period_end", name="uq_metric_obs_sla_key_period"),
        schema="contract",
    )
    op.create_index("ix_metric_obs_sla_id", "metric_observations", ["sla_id"], schema="contract")
    op.create_index("ix_metric_obs_status", "metric_observations", ["status"], schema="contract")
    op.create_index("ix_metric_obs_period", "metric_observations", ["period_start", "period_end"], schema="contract")

    # -----------------------------------------------------------------------
    # 14. sla_observation_band_counts
    # -----------------------------------------------------------------------
    op.create_table(
        "sla_observation_band_counts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "observation_id", sa.String(36),
            sa.ForeignKey("contract.metric_observations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "band_id", sa.String(36),
            sa.ForeignKey("contract.sla_condition_bands.id"),
            nullable=False,
        ),
        sa.Column("band_label", sa.String(50), nullable=False),
        sa.Column("unit_count", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("observation_id", "band_id", name="uq_obs_band_count"),
        schema="contract",
    )
    op.create_index("ix_sla_obs_band_counts_observation_id", "sla_observation_band_counts", ["observation_id"], schema="contract")

    # -----------------------------------------------------------------------
    # 15. evaluation_results
    # -----------------------------------------------------------------------
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "contract_id", sa.String(36),
            sa.ForeignKey("contract.contracts.id"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("triggered_by", sa.String(36)),
        sa.Column("trigger_source", sa.String(20), nullable=False, server_default="MANUAL"),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("approved_by", sa.String(36)),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("rejection_reason", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_eval_results_contract_id", "evaluation_results", ["contract_id"], schema="contract")
    op.create_index("ix_eval_results_status", "evaluation_results", ["status"], schema="contract")
    op.create_index("ix_eval_results_period", "evaluation_results", ["period_start", "period_end"], schema="contract")

    # -----------------------------------------------------------------------
    # 16. evaluation_sla_results
    # -----------------------------------------------------------------------
    op.create_table(
        "evaluation_sla_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "evaluation_id", sa.String(36),
            sa.ForeignKey("contract.evaluation_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sla_id", sa.String(36),
            sa.ForeignKey("contract.sla_definitions.id"),
            nullable=False,
        ),
        sa.Column("is_breached", sa.Boolean, nullable=False),
        sa.Column("breach_severity", sa.String(20)),
        sa.Column("computed_ld_percent", sa.Numeric(8, 4)),
        sa.Column("computed_ld_amount", sa.Numeric(18, 4)),
        sa.Column("band_breakdown", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("formula_snapshot", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_index("ix_eval_sla_results_evaluation_id", "evaluation_sla_results", ["evaluation_id"], schema="contract")
    op.create_index("ix_eval_sla_results_sla_id", "evaluation_sla_results", ["sla_id"], schema="contract")
    op.create_index("ix_eval_sla_results_is_breached", "evaluation_sla_results", ["is_breached"], schema="contract")

    # -----------------------------------------------------------------------
    # 17. audit_log
    # -----------------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("table_name", sa.String(100), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("changed_by", sa.String(36)),
        sa.Column("changed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("old_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("new_data", postgresql.JSONB(astext_type=sa.Text())),
        schema="contract",
    )
    op.create_index("ix_audit_log_table_name", "audit_log", ["table_name"], schema="contract")
    op.create_index("ix_audit_log_record_id", "audit_log", ["record_id"], schema="contract")
    op.create_index("ix_audit_log_changed_by", "audit_log", ["changed_by"], schema="contract")
    op.create_index("ix_audit_log_changed_at", "audit_log", ["changed_at"], schema="contract")

    # -----------------------------------------------------------------------
    # Seed formula_library with 4 formula types
    # -----------------------------------------------------------------------
    from uuid import uuid4
    conn = op.get_bind()
    for row in _FORMULA_SEED:
        conn.execute(
            sa.text(
                "INSERT INTO contract.formula_library "
                "(id, formula_type, display_name, description, parameter_schema, requires_bands, requires_lookup, is_active) "
                "VALUES (:id, :ft, :dn, :desc, CAST(:ps AS jsonb), :rb, :rl, true)"
            ),
            {
                "id": str(uuid4()),
                "ft": row["formula_type"],
                "dn": row["display_name"],
                "desc": row["description"],
                "ps": json.dumps(row["parameter_schema"]),
                "rb": row["requires_bands"],
                "rl": row["requires_lookup"],
            },
        )


def downgrade() -> None:
    # Drop in reverse FK dependency order
    for table in [
        "audit_log",
        "evaluation_sla_results",
        "evaluation_results",
        "sla_observation_band_counts",
        "metric_observations",
        "sla_asl_snapshots",
        "sla_dsl_versions",
        "sla_lookup_rows",
        "sla_condition_bands",
        "sla_parameter_values",
        "sla_guard_conditions",
        "sla_metrics",
        "sla_definitions",
        "contract_phases",
        "contract_scoring_config",
        "contracts",
        "formula_library",
    ]:
        op.drop_table(table, schema="contract")

    op.execute("DROP SCHEMA IF EXISTS contract CASCADE")
