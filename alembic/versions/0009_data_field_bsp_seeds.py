"""Seed BSP-specific data fields missing from the initial 0005 seed.

BSP SLAs track biometric-specific metrics (FPIR, FIDR, throughput, auth rates)
that were not included in the original data_field_master seed which focused on
MSAP/PMU operational fields.

Revision ID: 0009_data_field_bsp_seeds
Revises: 0008_sla_master_contract_type
Create Date: 2026-05-28
"""
from __future__ import annotations

from alembic import op

revision = "0009_data_field_bsp_seeds"
down_revision = "0008_sla_master_contract_type"
branch_labels = None
depends_on = None

_BSP_FIELDS = [
    # Biometric failure rates
    ("fpir",                "Failure to Print Identification Rate (%)",  "DECIMAL", "%",     "0.10", ["BSP"]),
    ("fidr",                "Failure to Identify Resident Rate (%)",      "DECIMAL", "%",     "0.05", ["BSP"]),
    ("ftar",                "Failure to Acquire Rate (%)",                "DECIMAL", "%",     "0.10", ["BSP"]),
    ("fer",                 "False Enrolment Rate (%)",                   "DECIMAL", "%",     "0.01", ["BSP"]),
    ("fmr",                 "False Match Rate (%)",                       "DECIMAL", "%",     "0.01", ["BSP"]),
    ("fnmr",                "False Non-Match Rate (%)",                   "DECIMAL", "%",     "0.10", ["BSP"]),
    # Authentication / throughput
    ("auth_success_rate",   "Authentication Success Rate (%)",            "DECIMAL", "%",     "99.5", ["BSP"]),
    ("throughput_tps",      "Throughput (transactions per second)",       "DECIMAL", "tps",  "100.0", ["BSP"]),
    ("enrolment_rate_pct",  "Enrolment Completion Rate (%)",             "DECIMAL", "%",     "98.0", ["BSP"]),
    # Operator / device
    ("operator_error_pct",  "Operator Error Rate (%)",                   "DECIMAL", "%",     "0.5",  ["BSP"]),
    ("device_downtime_pct", "Device Downtime (%)",                       "DECIMAL", "%",     "1.0",  ["BSP"]),
    # MSIP-specific fields (infra & network)
    ("network_uptime_pct",  "Network Uptime (%)",                        "DECIMAL", "%",     "99.9", ["MSIP"]),
    ("mttr_hours",          "Mean Time to Repair (hours)",               "DECIMAL", "hours", "4.0",  ["MSIP", "MSAP"]),
    ("mtbf_hours",          "Mean Time Between Failures (hours)",        "DECIMAL", "hours", "720.0",["MSIP"]),
    # PMU deliverable tracking
    ("report_submission_delay_days", "Report Submission Delay (days)",   "INTEGER", "days",  "0",    ["PMU"]),
    ("site_visit_compliance_pct",    "Site Visit Compliance Rate (%)",   "DECIMAL", "%",     "95.0", ["PMU", "MSAP"]),
]


def upgrade() -> None:
    for field_name, display_name, data_type, unit, example_value, applicable_to in _BSP_FIELDS:
        codes = ", ".join(f"'{c}'" for c in applicable_to)
        op.execute(
            f"""
            INSERT INTO contract.data_field_master
                (field_name, display_name, data_type, unit, example_value, applicable_to)
            VALUES
                ('{field_name}', '{display_name}', '{data_type}', '{unit}',
                 '{example_value}', ARRAY[{codes}]::VARCHAR[])
            ON CONFLICT (field_name) DO NOTHING
            """
        )


def downgrade() -> None:
    field_names = ", ".join(f"'{f[0]}'" for f in _BSP_FIELDS)
    op.execute(
        f"DELETE FROM contract.data_field_master WHERE field_name IN ({field_names})"
    )
