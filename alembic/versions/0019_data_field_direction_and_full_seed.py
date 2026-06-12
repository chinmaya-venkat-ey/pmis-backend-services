"""Add direction + description to data_field_master, seed all 4 RFPs.

Promotes data_field_master into the DSL measurement catalog the
``GET /api/v3/sla-input-variables`` endpoint surfaces to the FE
measurement picker.

Two structural columns added:

  direction     HIGHER_BETTER / LOWER_BETTER — drives severity-band
                interpretation. Inferred from the variable's name +
                unit (e.g. anything called *delay* / *failure* / *fpir*
                is LOWER_BETTER; anything called *availability* /
                *uptime* / *throughput* is HIGHER_BETTER). The
                migration sets this explicitly per row; the FE +
                evaluator just read it.
  description   one-line natural-language definition copied from the
                RFP. Surfaced as a tooltip in the FE picker.

Seed: every measurement variable that appears in PMU §5.28, MSAP,
BSP, MSIP. Per user direction (turn 2026-06-12), each contract gets
its OWN distinct variables — no cross-contract reuse — so the
prefixes encode the contract (``pmu_*``, ``msap_*``, ``bsp_*``,
``msip_*``). Future contracts add new prefixed rows; existing rows
never get renamed.

Revision ID: 0019_data_field_direction_and_full_seed
Revises: 0018_widen_attachment_file_id
Create Date: 2026-06-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0019_data_field_direction_and_full_seed"
down_revision = "0018_widen_attachment_file_id"
branch_labels = None
depends_on = None


# (field_name, display_name, data_type, unit, example_value,
#  applicable_to, direction, description)
_SEED_ROWS = [
    # ─────────────────────────────────────── PMU (UIDAI PMC for MSP)
    ("pmu_deliverable_delay_weeks",
     "Weeks delayed past deliverable due date",
     "INTEGER", "weeks", "0", ["PMU"], "LOWER_BETTER",
     "PMU §5.28.2.b — weeks elapsed between agreed delivery date and "
     "actual submission. Part weeks count as full weeks for LD."),

    ("pmu_rectification_delay_weeks",
     "Weeks delayed past defect rectification date",
     "INTEGER", "weeks", "0", ["PMU"], "LOWER_BETTER",
     "PMU §5.28.2.c — weeks past the deadline given for rectifying "
     "defects flagged on a deliverable."),

    ("pmu_query_resolution_delay_days",
     "Days delayed past query 3-day grace",
     "INTEGER", "days", "0", ["PMU"], "LOWER_BETTER",
     "PMU §5.28.3.a — days elapsed beyond the 3-day grace period for "
     "resolving contractual or technical queries to UIDAI."),

    ("pmu_incorrect_recommendations_count",
     "Incorrect recommendations occurrences",
     "INTEGER", "count", "0", ["PMU"], "LOWER_BETTER",
     "PMU §5.28.3.b — count of recommendations to UIDAI on acceptance "
     "of MSP deliverables that were later found incorrect."),

    ("pmu_resource_replacements_count",
     "Resource replacements initiated in quarter",
     "INTEGER", "count", "0", ["PMU"], "LOWER_BETTER",
     "PMU §5.28.3.c — count of resource replacements initiated by the "
     "consultant during one quarter."),

    ("pmu_kt_overlap_working_days",
     "Knowledge-transfer overlap during resource replacement",
     "INTEGER", "working_days", "20", ["PMU"], "HIGHER_BETTER",
     "PMU §5.28.3.d — working days the replacement resource overlapped "
     "with the resource being replaced (target ≥ 20)."),

    ("pmu_resource_business_days",
     "Business days logged per resource per month",
     "INTEGER", "days", "16", ["PMU"], "HIGHER_BETTER",
     "PMU §5.28.3.e — business days a resource was present in a month "
     "(target ≥ 16). Measured via UIDAI biometric attendance."),

    ("pmu_resource_logged_hours",
     "Hours logged per resource per month",
     "INTEGER", "hours", "144", ["PMU"], "HIGHER_BETTER",
     "PMU §5.28.3.e — total hours a resource logged in a month "
     "(target ≥ 144). Paired with business-days check."),

    ("pmu_onboarding_variance_days",
     "Onboarding variance (L − K days)",
     "INTEGER", "days", "0", ["PMU"], "LOWER_BETTER",
     "PMU §5.28.3.f — variance between actual onboarding date (L) and "
     "the approval date stamped by UIDAI (K)."),

    ("pmu_replacement_delay_days",
     "Days from replacement notification to onboarding",
     "INTEGER", "days", "21", ["PMU"], "LOWER_BETTER",
     "PMU §5.28.3.g — days elapsed between UIDAI notification of "
     "replacement and the replacement resource onboarding."),

    ("pmu_deployment_variance_days",
     "Days past T₀+6mo governance tool milestone",
     "INTEGER", "days", "0", ["PMU"], "LOWER_BETTER",
     "PMU §5.28.4.a — days the governance tool deployment was "
     "delivered past the T₀+6-month milestone."),

    ("pmu_governance_tool_failures_count",
     "Governance tool failures in quarter",
     "INTEGER", "count", "0", ["PMU"], "LOWER_BETTER",
     "PMU §5.28.4.b — count of governance tool failures / outages in "
     "one quarter."),

    # ─────────────────────────────────────── MSAP (Application Provider)
    ("msap_mobilization_delay_days_key",
     "Mobilization delay — key resources",
     "INTEGER", "days", "0", ["MSAP"], "LOWER_BETTER",
     "MSAP SLA 001 — days past T+14 for mobilization of selected "
     "'key' resources."),

    ("msap_mobilization_delay_days_50pct",
     "Mobilization delay — 50% resources",
     "INTEGER", "days", "0", ["MSAP"], "LOWER_BETTER",
     "MSAP SLA 002 — days past T+42 for 50% project resource "
     "mobilization."),

    ("msap_mobilization_delay_days_100pct",
     "Mobilization delay — 100% resources",
     "INTEGER", "days", "0", ["MSAP"], "LOWER_BETTER",
     "MSAP SLA 003 — days past T+70 for 100% project resource "
     "mobilization."),

    ("msap_key_resources_onboarded_count",
     "Key resources onboarded count",
     "INTEGER", "count", "28", ["MSAP"], "HIGHER_BETTER",
     "MSAP SLA 004 — count of 'key' resources from the bid evaluation "
     "actually onboarded (target = 28)."),

    ("msap_key_resources_retained_year1_count",
     "Key resources retained at end of year 1",
     "INTEGER", "count", "21", ["MSAP"], "HIGHER_BETTER",
     "MSAP SLA 005 — count of key resources still on project at the "
     "end of year 1 (target ≥ 21)."),

    ("msap_transition_plan_delay_days",
     "Transition plan submission delay",
     "INTEGER", "days", "0", ["MSAP"], "LOWER_BETTER",
     "MSAP SLA 006 — days past T+3 months for transition plan "
     "submission."),

    ("msap_g1_takeover_delay_days",
     "G1 application transition takeover delay",
     "INTEGER", "days", "0", ["MSAP"], "LOWER_BETTER",
     "MSAP SLA 007 — days past T+6 months for completion of transition "
     "and takeover for category G1 applications."),

    ("msap_project_tool_uptime_percent",
     "Project tool uptime",
     "DECIMAL", "%", "99", ["MSAP"], "HIGHER_BETTER",
     "MSAP SLA 014 — availability percentage of project tools per "
     "Volume-II §4.1.3."),

    # ─────────────────────────────────────── BSP (Biometric Service Provider)
    ("bsp_fpir_percent",
     "False Positive Identification Rate (FPIR)",
     "DECIMAL", "%", "0.5", ["BSP"], "LOWER_BETTER",
     "BSP SLA 001 — ratio of false positive de-duplication decisions "
     "to total de-duplication transactions for which no duplicate "
     "exists (target ≤ 0.5%)."),

    ("bsp_fnir_percent",
     "False Negative Identification Rate (FNIR)",
     "DECIMAL", "%", "0.1", ["BSP"], "LOWER_BETTER",
     "BSP SLA 001 — ratio of false negative de-duplication decisions "
     "to total de-duplication transactions for which a duplicate "
     "exists (target ≤ 0.1%)."),

    ("bsp_dedup_throughput_per_day",
     "De-duplication throughput per day",
     "INTEGER", "transactions/day", "350000", ["BSP"], "HIGHER_BETTER",
     "BSP SLA 003 — number of de-duplication transactions ABIS "
     "processes per day (target ≥ 350 000)."),

    ("bsp_fpira_percent",
     "FPIR for Anomalous matches (FPIRA)",
     "DECIMAL", "%", "5", ["BSP"], "LOWER_BETTER",
     "BSP SLA 004 — false positive identification rate for anomalous "
     "matches."),

    ("bsp_fnira_percent",
     "FNIR for Anomalous matches (FNIRA)",
     "DECIMAL", "%", "1", ["BSP"], "LOWER_BETTER",
     "BSP SLA 004 — false negative identification rate for anomalous "
     "matches."),

    ("bsp_abis_uptime_percent",
     "ABIS Solution uptime",
     "DECIMAL", "%", "99", ["BSP"], "HIGHER_BETTER",
     "BSP — uptime percentage of the ABIS solution (target ≥ 99%)."),

    # ─────────────────────────────────────── MSIP (Infrastructure Provider)
    ("msip_physical_server_availability_percent",
     "Physical server availability",
     "DECIMAL", "%", "99.95", ["MSIP"], "HIGHER_BETTER",
     "MSIP §1.5.4.1 — availability % of physical servers measured by "
     "SSH/healthcheck script every minute."),

    ("msip_vm_availability_percent",
     "Virtual machine availability",
     "DECIMAL", "%", "99.95", ["MSIP"], "HIGHER_BETTER",
     "MSIP §1.5.4.1 — availability % of virtual machines measured by "
     "SSH/healthcheck script every minute."),

    ("msip_container_availability_percent",
     "Container availability",
     "DECIMAL", "%", "99.95", ["MSIP"], "HIGHER_BETTER",
     "MSIP §1.5.4.1 — availability % of standalone containers via "
     "HEALTHCHECK probe every 60 s."),

    ("msip_paas_availability_percent",
     "PaaS service availability",
     "DECIMAL", "%", "99.95", ["MSIP"], "HIGHER_BETTER",
     "MSIP §1.5.4.1 — availability % of PaaS services via "
     "JDBC/HTTP probe."),

    ("msip_clustered_availability_percent",
     "Clustered service availability",
     "DECIMAL", "%", "99.99", ["MSIP"], "HIGHER_BETTER",
     "MSIP §1.5.4.2 — availability % of clustered groups (servers, "
     "VMs, containers, HA stacks)."),

    ("msip_ems_availability_percent",
     "EMS solution availability",
     "DECIMAL", "%", "99.5", ["MSIP"], "HIGHER_BETTER",
     "MSIP §1.5.4.3 — availability % of EMS + SLA monitoring tool "
     "dashboard."),

    ("msip_crm_availability_percent",
     "CRM and Contact Center availability",
     "DECIMAL", "%", "99.5", ["MSIP"], "HIGHER_BETTER",
     "MSIP §1.5.4.4 — availability % of CRM solution + contact-centre "
     "infrastructure."),

    ("msip_email_availability_percent",
     "Email service availability",
     "DECIMAL", "%", "99.5", ["MSIP"], "HIGHER_BETTER",
     "MSIP §1.5.4.5 — availability % of the email solution."),

    ("msip_sms_availability_percent",
     "SMS gateway availability",
     "DECIMAL", "%", "99.5", ["MSIP"], "HIGHER_BETTER",
     "MSIP §1.5.4.6 — availability % of the SMS gateway."),
]


def upgrade() -> None:
    # 1. New structural columns.
    op.add_column(
        "data_field_master",
        sa.Column("direction", sa.String(20), nullable=True),
        schema="contract",
    )
    op.add_column(
        "data_field_master",
        sa.Column("description", sa.Text(), nullable=True),
        schema="contract",
    )

    # 2. Seed every row. ON CONFLICT (field_name) DO UPDATE so reruns
    # refresh the catalog if descriptions are tweaked.
    # NOTE on naming: avoid bindparam names that collide with internal
    # SQLAlchemy decorator kwargs. ``fn`` is consumed by the
    # ``_generative`` decorator on ``TextClause.bindparams`` and ``dir``
    # shadows a Python builtin — both raise TypeError at runtime.
    for (
        field_name, display_name, data_type, unit, example_value,
        applicable_to, direction, description,
    ) in _SEED_ROWS:
        contracts_array = "ARRAY[" + ", ".join(f"'{c}'" for c in applicable_to) + "]"
        op.execute(sa.text("""
            INSERT INTO contract.data_field_master
                (field_name, display_name, data_type, unit, example_value,
                 applicable_to, direction, description, is_active)
            VALUES
                (:p_field_name, :p_display_name, :p_data_type, :p_unit, :p_example_value,
                 """ + contracts_array + """, :p_direction, :p_description, TRUE)
            ON CONFLICT (field_name) DO UPDATE
              SET display_name = EXCLUDED.display_name,
                  data_type    = EXCLUDED.data_type,
                  unit         = EXCLUDED.unit,
                  example_value= EXCLUDED.example_value,
                  direction    = EXCLUDED.direction,
                  description  = EXCLUDED.description,
                  is_active    = TRUE
        """).bindparams(
            p_field_name=field_name,
            p_display_name=display_name,
            p_data_type=data_type,
            p_unit=unit,
            p_example_value=example_value,
            p_direction=direction,
            p_description=description,
        ))


def downgrade() -> None:
    field_names = ", ".join(f"'{r[0]}'" for r in _SEED_ROWS)
    op.execute(
        f"DELETE FROM contract.data_field_master WHERE field_name IN ({field_names})"
    )
    op.drop_column("data_field_master", "description", schema="contract")
    op.drop_column("data_field_master", "direction", schema="contract")
