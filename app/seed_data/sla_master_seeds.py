"""Seed payloads for SLA masters — derived from the RFP for all 4 contract types.

Every entry is a dict in the exact shape POSTed to ``/api/v3/sla-masters``.
The seed endpoint feeds these directly into ``SlaService.create_from_form``,
which is the same code path the UI uses. So if the form accepts it, the seed
accepts it; if a band/lookup tweak is needed, change it in one place.

Numbers and bands track:
  * BSP    : 10 SLAs  — BSP-SLA001..010
  * MSAP   : 10 SLAs  — MSAP-SLA001, 002, 014..021
  * MSIP   : 10 SLAs  — MSIP-SLA001..010
  * PMU    : 11 SLAs  — PMU-SLA001..011 (verbatim from RFP §5.28; see file).

Total: 41.

PMU note: the 11 PMU SLAs are RFP-verbatim. Other contract families remain
RFP-adjacent placeholders pending the same treatment.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _sla(
    sla_ref: str,
    contract_type: str,
    formula_type: str,
    title: str,
    *,
    measurement_interval: str = "MONTHLY",
    reporting_interval: str = "QUARTERLY",
    baseline_type: str = "STATIC",
    compound_metric_rule: str = "INDEPENDENT",
    ld_aggregation_method: str = "SUM",
    ld_computation_base: str = "QUARTERLY_PAYMENT",
    effective_from: str = "2024-04-01",
    metrics: Optional[List[Dict]] = None,
    parameters: Optional[List[Dict]] = None,
    condition_bands: Optional[List[Dict]] = None,
    lookup_table: Optional[List[Dict]] = None,
    guard_conditions: Optional[List[Dict]] = None,
    description: Optional[str] = None,
    # ── RFP-native presentation fields (UIDAI RFP §5.28 row headers) ──
    category: Optional[str] = None,
    scope_text: Optional[str] = None,
    data_source: Optional[str] = None,
    calculation_method: Optional[str] = None,
    reports_submitted_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Helper mirroring tests/test_sla_onboard_all_contracts._sla.

    Single source of truth for payload shape. Keep in sync with the smoke test
    until that file is refactored to import from here.
    """
    return {
        "sla_ref": sla_ref,
        "contract_type": contract_type,
        "formula_type": formula_type,
        "title": title,
        "description": description,
        "category": category,
        "scope_text": scope_text,
        "data_source": data_source,
        "calculation_method": calculation_method,
        "reports_submitted_to": reports_submitted_to,
        "measurement_interval": measurement_interval,
        "reporting_interval": reporting_interval,
        "baseline_type": baseline_type,
        "compound_metric_rule": compound_metric_rule,
        "ld_aggregation_method": ld_aggregation_method,
        "ld_computation_base": ld_computation_base,
        "effective_from": effective_from,
        "metrics": metrics or [],
        "parameters": parameters or [],
        "condition_bands": condition_bands or [],
        "lookup_table": lookup_table or [],
        "guard_conditions": guard_conditions or [],
    }


# Reports authority used by every PMU SLA per the RFP table.
_PMU_TMD = "Technology Management Division, UIDAI HO"


# ---------------------------------------------------------------------------
# BSP — Biometric Solution Provider
# ---------------------------------------------------------------------------

BSP_SEEDS: List[Dict[str, Any]] = [
    _sla("BSP-SLA001", "BSP", "band_accumulation",
         "Failure to Print Identification Rate (FPIR)",
         metrics=[{"metric_key": "fpir", "display_name": "FPIR (%)", "unit": "%",
                   "target_numeric": "0.10", "direction": "LOWER_BETTER", "is_primary": True}],
         condition_bands=[
             {"metric_key": "fpir", "band_label": "Green", "range_min": None,
              "range_max": "0.10", "range_unit": "%", "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "fpir", "band_label": "Yellow", "range_min": "0.10",
              "range_max": "0.50", "range_unit": "%", "rate_percent": "0.50", "sort_order": 2},
             {"metric_key": "fpir", "band_label": "Red", "range_min": "0.50",
              "range_max": None, "range_unit": "%", "rate_percent": "1.00", "sort_order": 3},
         ]),
    _sla("BSP-SLA002", "BSP", "band_accumulation",
         "Failure to Identify Resident Rate (FIDR)",
         metrics=[{"metric_key": "fidr", "display_name": "FIDR (%)", "unit": "%",
                   "target_numeric": "0.05", "direction": "LOWER_BETTER", "is_primary": True}],
         condition_bands=[
             {"metric_key": "fidr", "band_label": "Green", "range_min": None,
              "range_max": "0.05", "range_unit": "%", "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "fidr", "band_label": "Red", "range_min": "0.05",
              "range_max": None, "range_unit": "%", "rate_percent": "1.00", "sort_order": 2},
         ]),
    _sla("BSP-SLA003", "BSP", "band_accumulation",
         "Failure to Acquire Rate (FTAR)",
         metrics=[{"metric_key": "ftar", "display_name": "FTAR (%)", "unit": "%",
                   "target_numeric": "0.10", "direction": "LOWER_BETTER", "is_primary": True}],
         condition_bands=[
             {"metric_key": "ftar", "band_label": "Green", "range_min": None,
              "range_max": "0.10", "range_unit": "%", "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "ftar", "band_label": "Red", "range_min": "0.10",
              "range_max": None, "range_unit": "%", "rate_percent": "0.75", "sort_order": 2},
         ]),
    _sla("BSP-SLA004", "BSP", "band_accumulation",
         "Authentication Success Rate",
         metrics=[{"metric_key": "auth_success_rate", "display_name": "Auth Success Rate (%)",
                   "unit": "%", "target_numeric": "99.5", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "auth_success_rate", "band_label": "Green",
              "range_min": "99.5", "range_max": None, "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "auth_success_rate", "band_label": "Yellow",
              "range_min": "99.0", "range_max": "99.5", "range_unit": "%",
              "rate_percent": "0.50", "sort_order": 2},
             {"metric_key": "auth_success_rate", "band_label": "Red",
              "range_min": None, "range_max": "99.0", "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 3},
         ]),
    _sla("BSP-SLA005", "BSP", "band_accumulation",
         "Biometric Authentication Throughput",
         metrics=[{"metric_key": "throughput_tps", "display_name": "Throughput (TPS)",
                   "unit": "tps", "target_numeric": "100.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "throughput_tps", "band_label": "Green",
              "range_min": "100.0", "range_max": None, "range_unit": "tps",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "throughput_tps", "band_label": "Red",
              "range_min": None, "range_max": "100.0", "range_unit": "tps",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
    _sla("BSP-SLA006", "BSP", "band_accumulation",
         "Enrolment Completion Rate",
         metrics=[{"metric_key": "enrolment_rate_pct",
                   "display_name": "Enrolment Completion Rate (%)",
                   "unit": "%", "target_numeric": "98.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "enrolment_rate_pct", "band_label": "Green",
              "range_min": "98.0", "range_max": None, "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "enrolment_rate_pct", "band_label": "Red",
              "range_min": None, "range_max": "98.0", "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
    _sla("BSP-SLA007", "BSP", "band_accumulation",
         "Operator Error Rate",
         metrics=[{"metric_key": "operator_error_pct",
                   "display_name": "Operator Error Rate (%)",
                   "unit": "%", "target_numeric": "0.5", "direction": "LOWER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "operator_error_pct", "band_label": "Green",
              "range_min": None, "range_max": "0.5", "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "operator_error_pct", "band_label": "Red",
              "range_min": "0.5", "range_max": None, "range_unit": "%",
              "rate_percent": "0.75", "sort_order": 2},
         ]),
    _sla("BSP-SLA008", "BSP", "band_accumulation",
         "Device Downtime",
         metrics=[{"metric_key": "device_downtime_pct",
                   "display_name": "Device Downtime (%)", "unit": "%",
                   "target_numeric": "1.0", "direction": "LOWER_BETTER", "is_primary": True}],
         condition_bands=[
             {"metric_key": "device_downtime_pct", "band_label": "Green",
              "range_min": None, "range_max": "1.0", "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "device_downtime_pct", "band_label": "Red",
              "range_min": "1.0", "range_max": None, "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
    _sla("BSP-SLA009", "BSP", "band_accumulation",
         "SDK False Match Rate",
         metrics=[{"metric_key": "fmr_sdk", "display_name": "SDK FMR (%)",
                   "unit": "%", "target_numeric": "0.01", "direction": "LOWER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "fmr_sdk", "band_label": "Pass",
              "range_min": None, "range_max": "0.01", "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "fmr_sdk", "band_label": "Fail",
              "range_min": "0.01", "range_max": None, "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
    _sla("BSP-SLA010", "BSP", "fixed_escalation",
         "Key Resource Onboarding Milestone",
         measurement_interval="ONE_TIME",
         reporting_interval="MONTHLY",
         ld_computation_base="FIXED_AMOUNT",
         metrics=[{"metric_key": "resource_onboard_delay_days",
                   "display_name": "Resource Onboarding Delay (days)",
                   "unit": "days", "target_numeric": "0", "direction": "LOWER_BETTER",
                   "is_primary": True}],
         parameters=[{"param_key": "fixed_ld_amount", "param_value": "500000"}],
         lookup_table=[
             {"lookup_key": "delay_0", "lookup_value": "0.00", "sort_order": 1},
             {"lookup_key": "delay_1_7", "lookup_value": "0.50", "sort_order": 2},
             {"lookup_key": "delay_8_plus", "lookup_value": "1.00", "sort_order": 3},
         ]),
]


# ---------------------------------------------------------------------------
# MSAP — Managed Services Application Provider
# ---------------------------------------------------------------------------

MSAP_SEEDS: List[Dict[str, Any]] = [
    _sla("MSAP-SLA001", "MSAP", "fixed_escalation",
         "Project Kick-off Milestone",
         measurement_interval="ONE_TIME",
         reporting_interval="MONTHLY",
         ld_computation_base="FIXED_AMOUNT",
         metrics=[{"metric_key": "report_submission_delay_days",
                   "display_name": "Kick-off Delay (days)", "unit": "days",
                   "target_numeric": "0", "direction": "LOWER_BETTER", "is_primary": True}],
         parameters=[{"param_key": "fixed_ld_amount", "param_value": "100000"}],
         lookup_table=[
             {"lookup_key": "on_time", "lookup_value": "0.00", "sort_order": 1},
             {"lookup_key": "delay_1_7", "lookup_value": "0.25", "sort_order": 2},
             {"lookup_key": "delay_8_plus", "lookup_value": "0.50", "sort_order": 3},
         ]),
    _sla("MSAP-SLA002", "MSAP", "fixed_escalation",
         "SRS Submission Milestone",
         measurement_interval="ONE_TIME",
         reporting_interval="MONTHLY",
         ld_computation_base="FIXED_AMOUNT",
         metrics=[{"metric_key": "report_submission_delay_days",
                   "display_name": "SRS Submission Delay (days)", "unit": "days",
                   "target_numeric": "0", "direction": "LOWER_BETTER", "is_primary": True}],
         parameters=[{"param_key": "fixed_ld_amount", "param_value": "200000"}],
         lookup_table=[
             {"lookup_key": "on_time", "lookup_value": "0.00", "sort_order": 1},
             {"lookup_key": "delay_1_14", "lookup_value": "0.50", "sort_order": 2},
             {"lookup_key": "delay_15_plus", "lookup_value": "1.00", "sort_order": 3},
         ]),
    _sla("MSAP-SLA014", "MSAP", "point_accumulation",
         "Key Resource Retention Rate",
         metrics=[{"metric_key": "key_resources_retained_pct",
                   "display_name": "Key Resource Retention (%)", "unit": "%",
                   "target_numeric": "90.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "key_resources_retained_pct", "band_label": "Exceptional",
              "range_min": "95.0", "range_max": None, "range_unit": "%",
              "severity_level": 0, "sort_order": 1},
             {"metric_key": "key_resources_retained_pct", "band_label": "On Target",
              "range_min": "90.0", "range_max": "95.0", "range_unit": "%",
              "severity_level": 1, "sort_order": 2},
             {"metric_key": "key_resources_retained_pct", "band_label": "Below Target",
              "range_min": "80.0", "range_max": "90.0", "range_unit": "%",
              "severity_level": 2, "sort_order": 3},
             {"metric_key": "key_resources_retained_pct", "band_label": "Critical",
              "range_min": None, "range_max": "80.0", "range_unit": "%",
              "severity_level": 3, "sort_order": 4},
         ]),
    _sla("MSAP-SLA015", "MSAP", "point_accumulation",
         "Test Automation Coverage",
         metrics=[{"metric_key": "test_automation_pct",
                   "display_name": "Test Automation Coverage (%)", "unit": "%",
                   "target_numeric": "70.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "test_automation_pct", "band_label": "Excellent",
              "range_min": "80.0", "range_max": None, "range_unit": "%",
              "severity_level": 0, "sort_order": 1},
             {"metric_key": "test_automation_pct", "band_label": "Target",
              "range_min": "70.0", "range_max": "80.0", "range_unit": "%",
              "severity_level": 1, "sort_order": 2},
             {"metric_key": "test_automation_pct", "band_label": "Below",
              "range_min": "60.0", "range_max": "70.0", "range_unit": "%",
              "severity_level": 2, "sort_order": 3},
             {"metric_key": "test_automation_pct", "band_label": "Critical",
              "range_min": None, "range_max": "60.0", "range_unit": "%",
              "severity_level": 3, "sort_order": 4},
         ]),
    _sla("MSAP-SLA016", "MSAP", "wac",
         "Production Defect Weighted Average Count (Production)",
         metrics=[{"metric_key": "defect_wac", "display_name": "Defect WAC (Production)",
                   "unit": "WAC", "target_numeric": "0.0", "direction": "LOWER_BETTER",
                   "is_primary": True}],
         parameters=[
             {"param_key": "severity_weights", "param_value": "1:1,2:2,3:3,4:4"},
             {"param_key": "variance_step_percent", "param_value": "10"},
             {"param_key": "baseline_window_quarters", "param_value": "2"},
         ]),
    _sla("MSAP-SLA017", "MSAP", "wac",
         "Production Defect Weighted Average Count (UAT)",
         metrics=[{"metric_key": "defect_wac", "display_name": "Defect WAC (UAT)",
                   "unit": "WAC", "target_numeric": "0.0", "direction": "LOWER_BETTER",
                   "is_primary": True}],
         parameters=[
             {"param_key": "severity_weights", "param_value": "1:1,2:2,3:3,4:4"},
             {"param_key": "variance_step_percent", "param_value": "10"},
             {"param_key": "baseline_window_quarters", "param_value": "2"},
         ]),
    _sla("MSAP-SLA018", "MSAP", "band_accumulation",
         "Tools Uptime",
         metrics=[{"metric_key": "tools_uptime_pct", "display_name": "Tools Uptime (%)",
                   "unit": "%", "target_numeric": "99.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "tools_uptime_pct", "band_label": "Green",
              "range_min": "99.0", "range_max": None, "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "tools_uptime_pct", "band_label": "Red",
              "range_min": None, "range_max": "99.0", "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
    _sla("MSAP-SLA019", "MSAP", "point_accumulation",
         "Application Monitoring Coverage",
         metrics=[{"metric_key": "monitoring_coverage_pct",
                   "display_name": "Monitoring Coverage (%)", "unit": "%",
                   "target_numeric": "95.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "monitoring_coverage_pct", "band_label": "Excellent",
              "range_min": "98.0", "range_max": None, "range_unit": "%",
              "severity_level": 0, "sort_order": 1},
             {"metric_key": "monitoring_coverage_pct", "band_label": "Target",
              "range_min": "95.0", "range_max": "98.0", "range_unit": "%",
              "severity_level": 1, "sort_order": 2},
             {"metric_key": "monitoring_coverage_pct", "band_label": "Below",
              "range_min": "90.0", "range_max": "95.0", "range_unit": "%",
              "severity_level": 2, "sort_order": 3},
             {"metric_key": "monitoring_coverage_pct", "band_label": "Critical",
              "range_min": None, "range_max": "90.0", "range_unit": "%",
              "severity_level": 3, "sort_order": 4},
         ]),
    _sla("MSAP-SLA020", "MSAP", "fixed_escalation",
         "Project Documentation Submission Delay",
         metrics=[{"metric_key": "project_docs_delay_days",
                   "display_name": "Docs Submission Delay (days)", "unit": "days",
                   "target_numeric": "0", "direction": "LOWER_BETTER", "is_primary": True}],
         lookup_table=[
             {"lookup_key": "on_time", "lookup_value": "0.00", "sort_order": 1},
             {"lookup_key": "delay_1_7", "lookup_value": "0.25", "sort_order": 2},
             {"lookup_key": "delay_8_14", "lookup_value": "0.50", "sort_order": 3},
             {"lookup_key": "delay_15_plus", "lookup_value": "1.00", "sort_order": 4},
         ]),
    _sla("MSAP-SLA021", "MSAP", "band_accumulation",
         "Site Visit Compliance Rate",
         metrics=[{"metric_key": "site_visit_compliance_pct",
                   "display_name": "Site Visit Compliance (%)", "unit": "%",
                   "target_numeric": "95.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "site_visit_compliance_pct", "band_label": "Green",
              "range_min": "95.0", "range_max": None, "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "site_visit_compliance_pct", "band_label": "Red",
              "range_min": None, "range_max": "95.0", "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
]


# ---------------------------------------------------------------------------
# MSIP — Managed Services Infrastructure Provider
# ---------------------------------------------------------------------------

MSIP_SEEDS: List[Dict[str, Any]] = [
    _sla("MSIP-SLA001", "MSIP", "band_accumulation",
         "Network Uptime",
         metrics=[{"metric_key": "network_uptime_pct", "display_name": "Network Uptime (%)",
                   "unit": "%", "target_numeric": "99.9", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "network_uptime_pct", "band_label": "Green",
              "range_min": "99.9", "range_max": None, "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "network_uptime_pct", "band_label": "Yellow",
              "range_min": "99.0", "range_max": "99.9", "range_unit": "%",
              "rate_percent": "0.50", "sort_order": 2},
             {"metric_key": "network_uptime_pct", "band_label": "Red",
              "range_min": None, "range_max": "99.0", "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 3},
         ]),
    _sla("MSIP-SLA002", "MSIP", "fixed_escalation",
         "Mean Time to Repair (MTTR)",
         metrics=[{"metric_key": "mttr_hours", "display_name": "MTTR (hours)",
                   "unit": "hours", "target_numeric": "4.0", "direction": "LOWER_BETTER",
                   "is_primary": True}],
         lookup_table=[
             {"lookup_key": "within_sla", "lookup_value": "0.00", "sort_order": 1},
             {"lookup_key": "4_8_hours", "lookup_value": "0.25", "sort_order": 2},
             {"lookup_key": "8_24_hours", "lookup_value": "0.50", "sort_order": 3},
             {"lookup_key": "24_plus_hours", "lookup_value": "1.00", "sort_order": 4},
         ]),
    _sla("MSIP-SLA003", "MSIP", "band_accumulation",
         "Server Availability",
         metrics=[{"metric_key": "server_availability_pct",
                   "display_name": "Server Availability (%)", "unit": "%",
                   "target_numeric": "99.5", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "server_availability_pct", "band_label": "Green",
              "range_min": "99.5", "range_max": None, "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "server_availability_pct", "band_label": "Red",
              "range_min": None, "range_max": "99.5", "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
    _sla("MSIP-SLA004", "MSIP", "band_accumulation",
         "Backup Compliance",
         metrics=[{"metric_key": "backup_compliance_pct",
                   "display_name": "Backup Compliance (%)", "unit": "%",
                   "target_numeric": "100.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "backup_compliance_pct", "band_label": "Green",
              "range_min": "100.0", "range_max": None, "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "backup_compliance_pct", "band_label": "Red",
              "range_min": None, "range_max": "100.0", "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
    _sla("MSIP-SLA005", "MSIP", "fixed_escalation",
         "P1 Critical Ticket Resolution Rate",
         metrics=[{"metric_key": "p1_resolution_pct",
                   "display_name": "P1 Resolution Rate (%)", "unit": "%",
                   "target_numeric": "95.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         lookup_table=[
             {"lookup_key": "gte_95", "lookup_value": "0.00", "sort_order": 1},
             {"lookup_key": "90_95", "lookup_value": "0.25", "sort_order": 2},
             {"lookup_key": "lt_90", "lookup_value": "1.00", "sort_order": 3},
         ]),
    _sla("MSIP-SLA006", "MSIP", "band_accumulation",
         "Patch Application Compliance",
         metrics=[{"metric_key": "patch_application_pct",
                   "display_name": "Patch Application (%)", "unit": "%",
                   "target_numeric": "95.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "patch_application_pct", "band_label": "Green",
              "range_min": "95.0", "range_max": None, "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "patch_application_pct", "band_label": "Red",
              "range_min": None, "range_max": "95.0", "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
    _sla("MSIP-SLA007", "MSIP", "band_accumulation",
         "Vulnerability Closure Rate",
         metrics=[{"metric_key": "vulnerability_closure_pct",
                   "display_name": "Vulnerability Closure (%)", "unit": "%",
                   "target_numeric": "90.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "vulnerability_closure_pct", "band_label": "Green",
              "range_min": "90.0", "range_max": None, "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "vulnerability_closure_pct", "band_label": "Red",
              "range_min": None, "range_max": "90.0", "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
    _sla("MSIP-SLA008", "MSIP", "band_accumulation",
         "Mean Time Between Failures (MTBF)",
         metrics=[{"metric_key": "mtbf_hours", "display_name": "MTBF (hours)",
                   "unit": "hours", "target_numeric": "720.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "mtbf_hours", "band_label": "Green",
              "range_min": "720.0", "range_max": None, "range_unit": "hours",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "mtbf_hours", "band_label": "Red",
              "range_min": None, "range_max": "720.0", "range_unit": "hours",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
    _sla("MSIP-SLA009", "MSIP", "band_accumulation",
         "Incident Response Rate",
         metrics=[{"metric_key": "incident_response_pct",
                   "display_name": "Incident Response Rate (%)", "unit": "%",
                   "target_numeric": "95.0", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "incident_response_pct", "band_label": "Green",
              "range_min": "95.0", "range_max": None, "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "incident_response_pct", "band_label": "Red",
              "range_min": None, "range_max": "95.0", "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 2},
         ]),
    # Multi-metric SLA with compound_metric_rule=COMBINED
    _sla("MSIP-SLA010", "MSIP", "band_accumulation",
         "Network Quality — Latency and Packet Loss",
         compound_metric_rule="COMBINED",
         metrics=[
             {"metric_key": "network_latency_ms", "display_name": "Network Latency (ms)",
              "unit": "ms", "target_numeric": "5.0", "direction": "LOWER_BETTER",
              "is_primary": True},
             {"metric_key": "network_packet_loss_pct",
              "display_name": "Packet Loss (%)", "unit": "%",
              "target_numeric": "0.1", "direction": "LOWER_BETTER", "is_primary": False},
         ],
         condition_bands=[
             {"metric_key": "network_latency_ms", "band_label": "Green",
              "range_min": None, "range_max": "5.0", "range_unit": "ms",
              "rate_percent": "0.00", "sort_order": 1},
             {"metric_key": "network_latency_ms", "band_label": "Red",
              "range_min": "5.0", "range_max": None, "range_unit": "ms",
              "rate_percent": "1.00", "sort_order": 2},
             {"metric_key": "network_packet_loss_pct", "band_label": "Green",
              "range_min": None, "range_max": "0.1", "range_unit": "%",
              "rate_percent": "0.00", "sort_order": 3},
             {"metric_key": "network_packet_loss_pct", "band_label": "Red",
              "range_min": "0.1", "range_max": None, "range_unit": "%",
              "rate_percent": "1.00", "sort_order": 4},
         ]),
]


# ---------------------------------------------------------------------------
# PMU — Programme Management Unit
# ---------------------------------------------------------------------------

PMU_SEEDS: List[Dict[str, Any]] = [
    # ── Phase 1 — deliverable-based SLAs (D1-D8) ──────────────────────────
    #
    # SLA 001 / 002 are linear-per-week LDs computed against deliverable cost.
    # They have NO severity component in the RFP — LD% rises 0.5% (SLA 001)
    # or 1% (SLA 002) for every week of delay. Until the linear_per_period
    # evaluator is introduced (Phase 2 of this roadmap), we model the first
    # 20 weeks of escalation as a fixed_escalation lookup. The cap is
    # implicit via the per-quarter LD cap on project_ld_bands.

    # RFP §5.28.2.b
    _sla("PMU-SLA001", "PMU", "fixed_escalation",
         "Non-submission of deliverable",
         description="Per RFP §5.28.2.b — 0.5% of deliverable cost for every "
                     "week or part thereof of delay attributable to the consultant.",
         category="Deliverable Submission",
         scope_text="Applies to every deliverable D1-D8 in Phase 1, where the "
                    "agreed submission schedule is missed for reasons "
                    "attributable to the consultant.",
         data_source="Manual — submission log maintained by UIDAI Project Office",
         calculation_method="LD = 0.5% × weeks delayed × cost of deliverable. "
                            "A part-week counts as a full week.",
         reports_submitted_to=_PMU_TMD,
         measurement_interval="ONE_TIME",
         reporting_interval="QUARTERLY",
         ld_computation_base="FIXED_AMOUNT",
         metrics=[{"metric_key": "deliverable_delay_weeks",
                   "display_name": "Weeks delayed", "unit": "weeks",
                   "target_numeric": "0", "direction": "LOWER_BETTER",
                   "is_primary": True}],
         parameters=[
             {"param_key": "ld_rate_per_week_percent", "param_value": "0.5"},
             {"param_key": "ld_base", "param_value": "DELIVERABLE_COST"},
         ],
         lookup_table=[
             {"lookup_key": f"week_{i}", "lookup_value": f"{i * 0.5:.2f}",
              "sort_order": i + 1}
             for i in range(0, 21)  # 0..20 weeks → 0%..10%
         ]),

    # RFP §5.28.2.c
    _sla("PMU-SLA002", "PMU", "fixed_escalation",
         "Deliverable not acceptable / defects not rectified",
         description="Per RFP §5.28.2.c — 1% of deliverable cost for every "
                     "week or part thereof of delay until defects are rectified.",
         category="Deliverable Submission",
         scope_text="Applies to every deliverable D1-D8 in Phase 1 once the "
                    "purchaser has identified defects and the consultant has "
                    "missed the stipulated rectification window.",
         data_source="Manual — defect register reviewed by UIDAI Project Office",
         calculation_method="LD = 1% × weeks delayed × cost of deliverable, "
                            "starting from the rectification deadline. A "
                            "part-week counts as a full week.",
         reports_submitted_to=_PMU_TMD,
         measurement_interval="ONE_TIME",
         reporting_interval="QUARTERLY",
         ld_computation_base="FIXED_AMOUNT",
         metrics=[{"metric_key": "rectification_delay_weeks",
                   "display_name": "Weeks delayed in rectification", "unit": "weeks",
                   "target_numeric": "0", "direction": "LOWER_BETTER",
                   "is_primary": True}],
         parameters=[
             {"param_key": "ld_rate_per_week_percent", "param_value": "1.0"},
             {"param_key": "ld_base", "param_value": "DELIVERABLE_COST"},
         ],
         lookup_table=[
             {"lookup_key": f"week_{i}", "lookup_value": f"{i * 1.0:.2f}",
              "sort_order": i + 1}
             for i in range(0, 11)  # 0..10 weeks → 0%..10%
         ]),

    # ── Phase 2 & 3 — D9, D10 ────────────────────────────────────────────

    # RFP §5.28.3.a
    _sla("PMU-SLA003", "PMU", "fixed_escalation",
         "Resolution of contract / technical queries beyond 3 working days",
         description="Per RFP §5.28.3.a — 0.1% LD on NPQP per day of delay "
                     "beyond the 3 working day SLA, until resolved.",
         category="Query Resolution",
         scope_text="Applies to contractual or technical queries initiated by "
                    "UIDAI under deliverable D10 (Phase 2 & Phase 3).",
         data_source="Manual — query register tracked by UIDAI",
         calculation_method="LD = 0.1% × days delayed beyond 3 working days × NPQP. "
                            "The 3-day grace window is excluded from the count.",
         reports_submitted_to=_PMU_TMD,
         measurement_interval="MONTHLY",
         reporting_interval="QUARTERLY",
         ld_computation_base="QUARTERLY_PAYMENT",
         metrics=[{"metric_key": "query_resolution_delay_days",
                   "display_name": "Days delayed beyond 3 working days", "unit": "days",
                   "target_numeric": "0", "direction": "LOWER_BETTER",
                   "is_primary": True}],
         parameters=[
             {"param_key": "grace_days", "param_value": "3"},
             {"param_key": "ld_rate_per_day_percent", "param_value": "0.1"},
         ],
         lookup_table=[
             {"lookup_key": f"day_{i}", "lookup_value": f"{i * 0.1:.2f}",
              "sort_order": i + 1}
             for i in range(0, 101)  # 0..100 days → 0%..10%
         ]),

    # RFP §5.28.3.b — severity-banded by occurrence count
    _sla("PMU-SLA004", "PMU", "point_accumulation",
         "Incorrect recommendation on acceptance of MSP deliverables",
         description="Per RFP §5.28.3.b — severity escalates with the number "
                     "of incorrect recommendations identified in the quarter.",
         category="Recommendation Quality",
         scope_text="Applies whenever it is identified that the consultant has "
                    "given UIDAI an incorrect recommendation on the acceptance "
                    "of any deliverable of an MSP.",
         data_source="Manual — identified during UIDAI review of MSP deliverables",
         calculation_method="Severity assigned by the count of incorrect "
                            "recommendations in the quarter: 1 occurrence → Sev 2, "
                            "2 → Sev 3, more than 2 → Sev 4.",
         reports_submitted_to=_PMU_TMD,
         measurement_interval="QUARTERLY",
         reporting_interval="QUARTERLY",
         ld_computation_base="QUARTERLY_PAYMENT",
         metrics=[{"metric_key": "incorrect_recommendations_count",
                   "display_name": "Incorrect recommendations (count)",
                   "unit": "count", "target_numeric": "0",
                   "direction": "LOWER_BETTER", "is_primary": True}],
         condition_bands=[
             {"metric_key": "incorrect_recommendations_count",
              "band_label": "L0 None", "range_min": None, "range_max": "0",
              "range_unit": "count", "severity_level": 0, "sort_order": 1},
             {"metric_key": "incorrect_recommendations_count",
              "band_label": "L2 One occurrence", "range_min": "0", "range_max": "1",
              "range_unit": "count", "severity_level": 2, "sort_order": 2},
             {"metric_key": "incorrect_recommendations_count",
              "band_label": "L3 Two occurrences", "range_min": "1", "range_max": "2",
              "range_unit": "count", "severity_level": 3, "sort_order": 3},
             {"metric_key": "incorrect_recommendations_count",
              "band_label": "L4 More than two", "range_min": "2", "range_max": None,
              "range_unit": "count", "severity_level": 4, "sort_order": 4},
         ]),

    # ── D12 & D13 — Resource SLAs ────────────────────────────────────────

    # RFP §5.28.3.c
    _sla("PMU-SLA005", "PMU", "point_accumulation",
         "Resource replacements per quarter",
         description="Per RFP §5.28.3.c — Sev 0 up to 1 replacement; Sev 4 "
                     "for every additional replacement in the quarter.",
         category="Resource Management",
         scope_text="Applies to all resources committed under deliverables D12 "
                    "and D13 for whom a replacement is initiated by the consultant.",
         data_source="Manual — UIDAI biometric attendance system",
         calculation_method="Count of resource replacements initiated by the "
                            "consultant in the quarter. Up to 1 replacement is "
                            "Sev 0; any increase beyond 1 is Sev 4.",
         reports_submitted_to=_PMU_TMD,
         measurement_interval="QUARTERLY",
         reporting_interval="QUARTERLY",
         ld_computation_base="QUARTERLY_PAYMENT",
         metrics=[{"metric_key": "resource_replacements_count",
                   "display_name": "Replacements initiated in quarter",
                   "unit": "count", "target_numeric": "1",
                   "direction": "LOWER_BETTER", "is_primary": True}],
         condition_bands=[
             {"metric_key": "resource_replacements_count",
              "band_label": "L0 Up to 1 replacement",
              "range_min": None, "range_max": "1",
              "range_unit": "count", "severity_level": 0, "sort_order": 1},
             {"metric_key": "resource_replacements_count",
              "band_label": "L4 More than 1 replacement",
              "range_min": "1", "range_max": None,
              "range_unit": "count", "severity_level": 4, "sort_order": 2},
         ]),

    # RFP §5.28.3.d
    _sla("PMU-SLA006", "PMU", "point_accumulation",
         "Minimum knowledge-transfer overlap during resource replacement",
         description="Per RFP §5.28.3.d — Sev 0 when overlap KT period "
                     ">=20 working days; Sev 4 otherwise.",
         category="Resource Management",
         scope_text="Applies to every resource for whom a replacement is "
                    "initiated by either the consultant or UIDAI.",
         data_source="Manual — UIDAI biometric attendance system. Working days "
                     "counted at the UIDAI office where the outgoing resource "
                     "is attached.",
         calculation_method="Overlap = number of working days where both "
                            "outgoing and incoming resources are present on the "
                            "UIDAI premises during knowledge transfer.",
         reports_submitted_to=_PMU_TMD,
         measurement_interval="QUARTERLY",
         reporting_interval="QUARTERLY",
         ld_computation_base="QUARTERLY_PAYMENT",
         metrics=[{"metric_key": "kt_overlap_working_days",
                   "display_name": "KT overlap (working days)", "unit": "days",
                   "target_numeric": "20", "direction": "HIGHER_BETTER",
                   "is_primary": True}],
         condition_bands=[
             {"metric_key": "kt_overlap_working_days",
              "band_label": "L0 >=20 working days",
              "range_min": "20", "range_max": None,
              "range_unit": "days", "severity_level": 0, "sort_order": 1},
             {"metric_key": "kt_overlap_working_days",
              "band_label": "L4 <20 working days",
              "range_min": None, "range_max": "20",
              "range_unit": "days", "severity_level": 4, "sort_order": 2},
         ]),

    # RFP §5.28.3.e — primary metric is business days. The "hours per month"
    # arm of the AND condition is captured as a secondary metric and a guard
    # so the FE can still collect both values; evaluator treats business
    # days as authoritative until the per-band compound-condition table
    # (Phase 2) lands.
    _sla("PMU-SLA007", "PMU", "point_accumulation",
         "Minimum resource availability per month",
         description="Per RFP §5.28.3.e — Sev 0 when business days >=16 AND "
                     "hours >=144; Sev 2 for 12-15 BD AND 108-135 hrs; Sev 4 "
                     "when below either threshold. Hours captured separately "
                     "until per-band AND-conditions are added.",
         category="Resource Management",
         scope_text="Applies to all resources deployed by the consultant under "
                    "the contract. Resources whose replacement was initiated by "
                    "UIDAI are excluded from the calculation.",
         data_source="Manual — UIDAI biometric attendance system",
         calculation_method="Per resource per month: count business days and "
                            "total hours logged. Sev 0 when business days ≥ 16 "
                            "AND hours ≥ 144. Sev 2 when both are in the 12-15 "
                            "BD AND 108-135 hrs range. Sev 4 when below either.",
         reports_submitted_to=_PMU_TMD,
         measurement_interval="MONTHLY",
         reporting_interval="QUARTERLY",
         ld_computation_base="QUARTERLY_PAYMENT",
         compound_metric_rule="COMBINED",
         metrics=[
             {"metric_key": "resource_business_days",
              "display_name": "Business days logged (per resource per month)",
              "unit": "days", "target_numeric": "16",
              "direction": "HIGHER_BETTER", "is_primary": True},
             {"metric_key": "resource_logged_hours",
              "display_name": "Hours logged (per resource per month)",
              "unit": "hours", "target_numeric": "144",
              "direction": "HIGHER_BETTER", "is_primary": False},
         ],
         condition_bands=[
             {"metric_key": "resource_business_days",
              "band_label": "L0 >=16 BD",
              "range_min": "16", "range_max": None,
              "range_unit": "days", "severity_level": 0, "sort_order": 1},
             {"metric_key": "resource_business_days",
              "band_label": "L2 12-15 BD",
              "range_min": "12", "range_max": "16",
              "range_unit": "days", "severity_level": 2, "sort_order": 2},
             {"metric_key": "resource_business_days",
              "band_label": "L4 <12 BD",
              "range_min": None, "range_max": "12",
              "range_unit": "days", "severity_level": 4, "sort_order": 3},
         ],
         guard_conditions=[
             # Informational guard: if hours don't meet the AND-threshold,
             # this flags the period for manual review. Evaluator picks up
             # the guard result and surfaces it in the response.
             {"metric_key": "resource_logged_hours",
              "operator": "LT", "threshold_value": "144",
              "action": "EXCLUDE",
              "action_description":
                  "Hours below 144 — verify business-day severity with manual review (Phase 2 will replace this with per-band AND-conditions)."}
         ]),

    # RFP §5.28.3.f — onboarding variance L-K (K = approval date, L = actual)
    _sla("PMU-SLA008", "PMU", "point_accumulation",
         "Onboarding of additional resources within agreed timeline",
         description="Per RFP §5.28.3.f — variance = (actual onboarding date) "
                     "- (approval date). Sev 0 if <=21 days; Sev 2 if 22-28; "
                     "Sev 4 if >28. Continuing-quarter rule applies; not modelled "
                     "in v1 (manual re-evaluation per quarter).",
         category="Resource Management",
         scope_text="Applies to the onboarding of additional resources mutually "
                    "agreed by both parties.",
         data_source="Manual — UIDAI biometric attendance system",
         calculation_method="Daily variance = actual onboarding date − approval "
                            "date. Sev 0 if variance ≤ 21 days; Sev 2 if 22-28 "
                            "days; Sev 4 if > 28 days. If not onboarded in the "
                            "planned quarter, Sev 4 is applicable every "
                            "subsequent quarter until onboarding occurs.",
         reports_submitted_to=_PMU_TMD,
         measurement_interval="QUARTERLY",
         reporting_interval="QUARTERLY",
         ld_computation_base="QUARTERLY_PAYMENT",
         metrics=[{"metric_key": "onboarding_variance_days",
                   "display_name": "Onboarding variance (L - K, days)",
                   "unit": "days", "target_numeric": "21",
                   "direction": "LOWER_BETTER", "is_primary": True}],
         condition_bands=[
             {"metric_key": "onboarding_variance_days",
              "band_label": "L0 <=K+21",
              "range_min": None, "range_max": "21",
              "range_unit": "days", "severity_level": 0, "sort_order": 1},
             {"metric_key": "onboarding_variance_days",
              "band_label": "L2 K+22 to K+28",
              "range_min": "21", "range_max": "28",
              "range_unit": "days", "severity_level": 2, "sort_order": 2},
             {"metric_key": "onboarding_variance_days",
              "band_label": "L4 >K+28",
              "range_min": "28", "range_max": None,
              "range_unit": "days", "severity_level": 4, "sort_order": 3},
         ]),

    # RFP §5.28.3.g
    _sla("PMU-SLA009", "PMU", "point_accumulation",
         "Delay onboarding replacement resource",
         description="Per RFP §5.28.3.g — Sev 0 if replacement onboarded "
                     "within 21 days of notification; Sev 2 if later. "
                     "Continuing-quarter rule applies; not modelled in v1.",
         category="Resource Management",
         scope_text="Applies to onboarding of replacement resources within 21 "
                    "days of the date of notification.",
         data_source="Manual — UIDAI biometric attendance system",
         calculation_method="Daily variance = actual onboarding date − date of "
                            "notification. Sev 0 if ≤ 21 days; Sev 2 if > 21. "
                            "Sev 2 is applicable every quarter until the "
                            "replacement is onboarded.",
         reports_submitted_to=_PMU_TMD,
         measurement_interval="QUARTERLY",
         reporting_interval="QUARTERLY",
         ld_computation_base="QUARTERLY_PAYMENT",
         metrics=[{"metric_key": "replacement_delay_days",
                   "display_name": "Days from notification to onboarding",
                   "unit": "days", "target_numeric": "21",
                   "direction": "LOWER_BETTER", "is_primary": True}],
         condition_bands=[
             {"metric_key": "replacement_delay_days",
              "band_label": "L0 <=21 days",
              "range_min": None, "range_max": "21",
              "range_unit": "days", "severity_level": 0, "sort_order": 1},
             {"metric_key": "replacement_delay_days",
              "band_label": "L2 >21 days",
              "range_min": "21", "range_max": None,
              "range_unit": "days", "severity_level": 2, "sort_order": 2},
         ]),

    # ── D11 — Governance Tool ────────────────────────────────────────────

    # RFP §5.28.4.a — milestone tied to T0+6 months, bound at mapping time
    _sla("PMU-SLA010", "PMU", "point_accumulation",
         "Deployment & configuration of Governance tool (T0+6 months)",
         description="Per RFP §5.28.4.a — variance vs the planned milestone "
                     "P=T0+6 months. Sev levels: 0 at <=P, 1 at P+1..7d, 2 at "
                     "P+8..14d, 3 at P+15..21d, 4 at >P+21d. T anchor is bound "
                     "per mapping via overrides.t_anchor_date.",
         category="Governance Tool",
         scope_text="Applies to the consultant's obligation to deploy and "
                    "configure the Governance tool (deliverable D11) within "
                    "the T0+6 month milestone.",
         data_source="Manual — verified by UIDAI",
         calculation_method="Variance = actual completion date of governance "
                            "tool deployment − planned completion date "
                            "(T0+6 months). Sev 0 at on-time; Sev 1, 2, 3, 4 "
                            "for each successive 7-day slip past the milestone.",
         reports_submitted_to="Concerned UIDAI Stakeholders",
         measurement_interval="ONE_TIME",
         reporting_interval="QUARTERLY",
         ld_computation_base="QUARTERLY_PAYMENT",
         metrics=[{"metric_key": "deployment_variance_days",
                   "display_name": "Days past T0+6 month milestone",
                   "unit": "days", "target_numeric": "0",
                   "direction": "LOWER_BETTER", "is_primary": True}],
         condition_bands=[
             {"metric_key": "deployment_variance_days",
              "band_label": "L0 On time (<=P)",
              "range_min": None, "range_max": "0",
              "range_unit": "days", "severity_level": 0, "sort_order": 1},
             {"metric_key": "deployment_variance_days",
              "band_label": "L1 P+1..7d",
              "range_min": "0", "range_max": "7",
              "range_unit": "days", "severity_level": 1, "sort_order": 2},
             {"metric_key": "deployment_variance_days",
              "band_label": "L2 P+8..14d",
              "range_min": "7", "range_max": "14",
              "range_unit": "days", "severity_level": 2, "sort_order": 3},
             {"metric_key": "deployment_variance_days",
              "band_label": "L3 P+15..21d",
              "range_min": "14", "range_max": "21",
              "range_unit": "days", "severity_level": 3, "sort_order": 4},
             {"metric_key": "deployment_variance_days",
              "band_label": "L4 >P+21d",
              "range_min": "21", "range_max": None,
              "range_unit": "days", "severity_level": 4, "sort_order": 5},
         ]),

    # RFP §5.28.4.b
    _sla("PMU-SLA011", "PMU", "point_accumulation",
         "Governance tool failures / uptime",
         description="Per RFP §5.28.4.b — failures per quarter. Sev 2 for "
                     "1-2; Sev 3 for 3-4; Sev 4 for >4.",
         category="Governance Tool",
         scope_text="Applies to events of failure identified by UIDAI in the "
                    "performance or deliverable of the Governance tool. "
                    "Examples include out-of-date Minutes of Meetings, dashboard "
                    "showing incorrect data, missed obligations or alerts, and "
                    "stakeholder activities not assigned in a timely manner.",
         data_source="Manual — verified by UIDAI",
         calculation_method="Count of failure occurrences observed in the "
                            "quarter. 1-2 failures → Sev 2; 3-4 failures → "
                            "Sev 3; more than 4 failures → Sev 4.",
         reports_submitted_to=_PMU_TMD,
         measurement_interval="QUARTERLY",
         reporting_interval="QUARTERLY",
         ld_computation_base="QUARTERLY_PAYMENT",
         metrics=[{"metric_key": "governance_tool_failures_count",
                   "display_name": "Failure occurrences per quarter",
                   "unit": "count", "target_numeric": "0",
                   "direction": "LOWER_BETTER", "is_primary": True}],
         condition_bands=[
             {"metric_key": "governance_tool_failures_count",
              "band_label": "L0 No failures",
              "range_min": None, "range_max": "0",
              "range_unit": "count", "severity_level": 0, "sort_order": 1},
             {"metric_key": "governance_tool_failures_count",
              "band_label": "L2 1-2 failures",
              "range_min": "0", "range_max": "2",
              "range_unit": "count", "severity_level": 2, "sort_order": 2},
             {"metric_key": "governance_tool_failures_count",
              "band_label": "L3 3-4 failures",
              "range_min": "2", "range_max": "4",
              "range_unit": "count", "severity_level": 3, "sort_order": 3},
             {"metric_key": "governance_tool_failures_count",
              "band_label": "L4 >4 failures",
              "range_min": "4", "range_max": None,
              "range_unit": "count", "severity_level": 4, "sort_order": 4},
         ]),
]


# ---------------------------------------------------------------------------
# Aggregated views consumed by the seed endpoint and tests.
# ---------------------------------------------------------------------------

SEEDS_BY_CONTRACT: Dict[str, List[Dict[str, Any]]] = {
    "BSP":  BSP_SEEDS,
    "MSAP": MSAP_SEEDS,
    "MSIP": MSIP_SEEDS,
    "PMU":  PMU_SEEDS,
}

ALL_SEED_SLAS: List[Dict[str, Any]] = (
    BSP_SEEDS + MSAP_SEEDS + MSIP_SEEDS + PMU_SEEDS
)
