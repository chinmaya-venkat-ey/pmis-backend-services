"""Seed remaining data fields for BSP, MSAP, MSIP, and PMU SLAs.

Covers all observable metric fields referenced in the full SLA catalogue
across all 4 contract types that were not present in the 0005 or 0009 seeds.

Revision ID: 0010_data_field_all_contracts_seeds
Revises: 0009_data_field_bsp_seeds
Create Date: 2026-05-28
"""
from __future__ import annotations

from alembic import op

revision = "0010_data_fields_all_contracts"
down_revision = "0009_data_field_bsp_seeds"
branch_labels = None
depends_on = None

# (field_name, display_name, data_type, unit, example_value, applicable_to)
_FIELDS = [
    # ---------------------------------------------------------------- BSP additional
    ("fpira",                      "FPIR Actual (%)",                                   "DECIMAL", "%",       "0.08",  ["BSP"]),
    ("fnira",                      "FNIR Actual (%)",                                   "DECIMAL", "%",       "0.09",  ["BSP"]),
    ("bpcer",                      "Bona-fide Presentation Classification Error Rate (%)","DECIMAL","%",      "0.05",  ["BSP"]),
    ("apcer",                      "Attack Presentation Classification Error Rate (%)", "DECIMAL", "%",       "0.01",  ["BSP"]),
    ("dedup_throughput_count",     "Deduplication Throughput (records/day)",            "DECIMAL", "records/day","100000",["BSP"]),
    ("business_days_logged",       "Business Days Logged (days)",                       "INTEGER", "days",    "22",    ["BSP"]),
    ("hours_logged",               "Hours Logged (hours)",                              "DECIMAL", "hours",   "176.0", ["BSP"]),
    ("resource_overlap_weeks",     "Resource Overlap Period (weeks)",                   "INTEGER", "weeks",   "4",     ["BSP"]),
    ("fmr_sdk",                    "SDK False Match Rate (%)",                          "DECIMAL", "%",       "0.01",  ["BSP"]),
    ("fnmr_sdk",                   "SDK False Non-Match Rate (%)",                      "DECIMAL", "%",       "0.10",  ["BSP"]),
    # ---------------------------------------------------------------- MSAP additional
    ("key_resources_onboarded",    "Key Resources Onboarded (count)",                  "INTEGER", "count",   "10",    ["MSAP"]),
    ("key_resources_retained_pct", "Key Resources Retention Rate (%)",                 "DECIMAL", "%",       "90.0",  ["MSAP"]),
    ("test_automation_pct",        "Test Automation Coverage (%)",                     "DECIMAL", "%",       "70.0",  ["MSAP"]),
    ("build_deploy_time_hours",    "Build & Deploy Time (hours)",                      "DECIMAL", "hours",   "2.0",   ["MSAP"]),
    ("monitoring_coverage_pct",    "Monitoring Coverage (%)",                          "DECIMAL", "%",       "95.0",  ["MSAP"]),
    ("tools_uptime_pct",           "Tools Uptime (%)",                                 "DECIMAL", "%",       "99.0",  ["MSAP"]),
    ("project_docs_delay_days",    "Project Documentation Submission Delay (days)",    "INTEGER", "days",    "0",     ["MSAP"]),
    ("non_key_resource_replacements","Non-Key Resource Replacements (count)",          "INTEGER", "count",   "0",     ["MSAP"]),
    ("tools_functional_failures",  "Tools Functional Failures (count)",                "INTEGER", "count",   "0",     ["MSAP"]),
    ("tech_upgrade_pct",           "Technology Upgrade Completion (%)",                "DECIMAL", "%",       "100.0", ["MSAP"]),
    ("defect_wac",                 "Defect Weighted Average Count",                    "DECIMAL", "WAC",     "0.0",   ["MSAP"]),
    # ---------------------------------------------------------------- MSIP additional
    ("server_availability_pct",    "Server Availability (%)",                          "DECIMAL", "%",       "99.5",  ["MSIP"]),
    ("backup_compliance_pct",      "Backup Compliance (%)",                            "DECIMAL", "%",       "100.0", ["MSIP"]),
    ("backup_throughput_tbph",     "Backup Throughput (TB/hour)",                      "DECIMAL", "TB/hour", "1.0",   ["MSIP"]),
    ("backup_time_hours",          "Backup Completion Time (hours)",                   "DECIMAL", "hours",   "4.0",   ["MSIP"]),
    ("storage_response_ms",        "Storage Response Time (ms)",                       "DECIMAL", "ms",      "10.0",  ["MSIP"]),
    ("storage_iops_deviation_pct", "Storage IOPS Deviation (%)",                       "DECIMAL", "%",       "5.0",   ["MSIP"]),
    ("data_loss_blocks",           "Data Loss (blocks)",                               "INTEGER", "blocks",  "0",     ["MSIP"]),
    ("replication_lag_seconds",    "Replication Lag (seconds)",                        "DECIMAL", "seconds", "30.0",  ["MSIP"]),
    ("network_packet_loss_pct",    "Network Packet Loss (%)",                          "DECIMAL", "%",       "0.1",   ["MSIP"]),
    ("network_latency_ms",         "Network Latency (ms)",                             "DECIMAL", "ms",      "5.0",   ["MSIP"]),
    ("vm_provisioning_minutes",    "VM Provisioning Time (minutes)",                   "DECIMAL", "minutes", "30.0",  ["MSIP"]),
    ("p1_resolution_pct",          "P1 Ticket Resolution Rate (%)",                   "DECIMAL", "%",       "95.0",  ["MSIP"]),
    ("p2_resolution_pct",          "P2 Ticket Resolution Rate (%)",                   "DECIMAL", "%",       "90.0",  ["MSIP"]),
    ("p3_resolution_pct",          "P3 Ticket Resolution Rate (%)",                   "DECIMAL", "%",       "85.0",  ["MSIP"]),
    ("p4_resolution_pct",          "P4 Ticket Resolution Rate (%)",                   "DECIMAL", "%",       "80.0",  ["MSIP"]),
    ("planned_downtime_hours",     "Planned Downtime (hours)",                         "DECIMAL", "hours",   "4.0",   ["MSIP"]),
    ("backup_tape_compliance_pct", "Backup Tape Compliance (%)",                       "DECIMAL", "%",       "100.0", ["MSIP"]),
    ("faulty_backup_retriggered_pct","Faulty Backup Retriggered (%)",                 "DECIMAL", "%",       "100.0", ["MSIP"]),
    ("imac_update_compliance_pct", "IMAC Update Compliance (%)",                       "DECIMAL", "%",       "95.0",  ["MSIP"]),
    ("asset_location_compliance_pct","Asset Location Compliance (%)",                 "DECIMAL", "%",       "95.0",  ["MSIP"]),
    ("patch_regression_pct",       "Patch Regression Rate (%)",                        "DECIMAL", "%",       "0.0",   ["MSIP"]),
    ("patch_application_pct",      "Patch Application Compliance (%)",                 "DECIMAL", "%",       "95.0",  ["MSIP"]),
    ("vulnerability_closure_pct",  "Vulnerability Closure Rate (%)",                   "DECIMAL", "%",       "90.0",  ["MSIP"]),
    ("endpoint_scan_pct",          "Endpoint Scan Coverage (%)",                       "DECIMAL", "%",       "100.0", ["MSIP"]),
    ("system_hygiene_coverage_pct","System Hygiene Coverage (%)",                      "DECIMAL", "%",       "95.0",  ["MSIP"]),
    ("access_violations_count",    "Access Violations (count)",                        "INTEGER", "count",   "0",     ["MSIP"]),
    ("incident_response_pct",      "Incident Response Rate (%)",                       "DECIMAL", "%",       "95.0",  ["MSIP"]),
    ("incident_resolution_pct",    "Incident Resolution Rate (%)",                     "DECIMAL", "%",       "90.0",  ["MSIP"]),
    ("problem_ticket_compliance_pct","Problem Ticket Compliance (%)",                  "DECIMAL", "%",       "90.0",  ["MSIP"]),
    # ---------------------------------------------------------------- PMU additional
    ("query_response_delay_days",  "Query Response Delay (days)",                      "INTEGER", "days",    "0",     ["PMU"]),
    ("incorrect_recommendations_count","Incorrect Recommendations (count)",            "INTEGER", "count",   "0",     ["PMU"]),
    ("governance_tool_failures_count","Governance Tool Failures (count)",              "INTEGER", "count",   "0",     ["PMU"]),
    ("resource_onboard_delay_days","Resource Onboarding Delay (days)",                 "INTEGER", "days",    "0",     ["PMU"]),
]


def upgrade() -> None:
    for field_name, display_name, data_type, unit, example_value, applicable_to in _FIELDS:
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
    field_names = ", ".join(f"'{f[0]}'" for f in _FIELDS)
    op.execute(
        f"DELETE FROM contract.data_field_master WHERE field_name IN ({field_names})"
    )
