"""Comprehensive SLA onboarding smoke test — all 4 contracts.

Usage:
    python tests/test_sla_onboard_all_contracts.py

Hits localhost:8005. Expects a clean DB (or uses ON CONFLICT-safe sla_refs).
Each case is independent; failures are collected and reported at the end.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

import requests

BASE = "http://localhost:8005/api/v3"
HEADERS = {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

@dataclass
class Case:
    sla_ref: str
    contract_type: str
    description: str
    payload: Dict[str, Any]
    expect_status: int = 201


@dataclass
class Result:
    sla_ref: str
    description: str
    ok: bool
    status: int
    body: Any
    error: Optional[str] = None


def run(cases: List[Case]) -> List[Result]:
    results: List[Result] = []
    for c in cases:
        try:
            resp = requests.post(
                f"{BASE}/sla-masters",
                headers=HEADERS,
                json=c.payload,
                timeout=10,
            )
            ok = resp.status_code == c.expect_status
            body = resp.json() if resp.content else {}
            results.append(Result(c.sla_ref, c.description, ok, resp.status_code, body))
        except Exception as exc:
            results.append(Result(c.sla_ref, c.description, False, 0, {}, str(exc)))
    return results


def print_report(results: List[Result]) -> int:
    passed = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    print(f"\n{'='*70}")
    print(f"SLA ONBOARD TEST REPORT — {len(results)} cases")
    print(f"  PASS: {len(passed)}   FAIL: {len(failed)}")
    print(f"{'='*70}")
    for r in failed:
        print(f"\n[FAIL] {r.sla_ref} — {r.description}")
        print(f"       HTTP {r.status}")
        if r.error:
            print(f"       Exception: {r.error}")
        else:
            body_str = json.dumps(r.body, indent=2, default=str)
            for line in body_str.splitlines()[:30]:
                print(f"       {line}")
    if not failed:
        print("\nAll cases passed.")
    return len(failed)


# ---------------------------------------------------------------------------
# Helper to build a common payload skeleton
# ---------------------------------------------------------------------------

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
) -> Dict[str, Any]:
    return {
        "sla_ref": sla_ref,
        "contract_type": contract_type,
        "formula_type": formula_type,
        "title": title,
        "description": description,
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


# ---------------------------------------------------------------------------
# BSP SLAs
# ---------------------------------------------------------------------------

BSP_CASES: List[Case] = [
    Case("BSP-SLA001", "BSP", "BSP FPIR band_accumulation",
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
              ])),
    Case("BSP-SLA002", "BSP", "BSP FIDR band_accumulation",
         _sla("BSP-SLA002", "BSP", "band_accumulation",
              "Failure to Identify Resident Rate (FIDR)",
              metrics=[{"metric_key": "fidr", "display_name": "FIDR (%)", "unit": "%",
                        "target_numeric": "0.05", "direction": "LOWER_BETTER", "is_primary": True}],
              condition_bands=[
                  {"metric_key": "fidr", "band_label": "Green", "range_min": None,
                   "range_max": "0.05", "range_unit": "%", "rate_percent": "0.00", "sort_order": 1},
                  {"metric_key": "fidr", "band_label": "Red", "range_min": "0.05",
                   "range_max": None, "range_unit": "%", "rate_percent": "1.00", "sort_order": 2},
              ])),
    Case("BSP-SLA003", "BSP", "BSP FTAR band_accumulation",
         _sla("BSP-SLA003", "BSP", "band_accumulation",
              "Failure to Acquire Rate (FTAR)",
              metrics=[{"metric_key": "ftar", "display_name": "FTAR (%)", "unit": "%",
                        "target_numeric": "0.10", "direction": "LOWER_BETTER", "is_primary": True}],
              condition_bands=[
                  {"metric_key": "ftar", "band_label": "Green", "range_min": None,
                   "range_max": "0.10", "range_unit": "%", "rate_percent": "0.00", "sort_order": 1},
                  {"metric_key": "ftar", "band_label": "Red", "range_min": "0.10",
                   "range_max": None, "range_unit": "%", "rate_percent": "0.75", "sort_order": 2},
              ])),
    Case("BSP-SLA004", "BSP", "BSP Authentication Success Rate band_accumulation",
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
              ])),
    Case("BSP-SLA005", "BSP", "BSP Throughput band_accumulation",
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
              ])),
    Case("BSP-SLA006", "BSP", "BSP Enrolment Rate band_accumulation",
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
              ])),
    Case("BSP-SLA007", "BSP", "BSP Operator Error Rate band_accumulation",
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
              ])),
    Case("BSP-SLA008", "BSP", "BSP Device Downtime band_accumulation",
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
              ])),
    Case("BSP-SLA009", "BSP", "BSP SDK FMR band_accumulation",
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
              ])),
    # Milestone SLA — ONE_TIME interval, fixed_escalation
    Case("BSP-SLA010", "BSP", "BSP Resource Onboarding Milestone fixed_escalation ONE_TIME",
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
              ])),
]

# ---------------------------------------------------------------------------
# MSAP SLAs
# ---------------------------------------------------------------------------

MSAP_CASES: List[Case] = [
    # Milestone SLAs using fixed_escalation ONE_TIME
    Case("MSAP-SLA001", "MSAP", "MSAP Project Kick-off Milestone fixed_escalation",
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
              ])),
    Case("MSAP-SLA002", "MSAP", "MSAP SRS Submission Milestone fixed_escalation",
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
              ])),
    # Operational SLAs using point_accumulation
    Case("MSAP-SLA014", "MSAP", "MSAP Key Resource Retention point_accumulation",
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
              ])),
    Case("MSAP-SLA015", "MSAP", "MSAP Test Automation Coverage point_accumulation",
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
              ])),
    # WAC SLAs — production and UAT (should NOT block each other)
    Case("MSAP-SLA016", "MSAP", "MSAP Production Defect WAC",
         _sla("MSAP-SLA016", "MSAP", "wac",
              "Production Defect Weighted Average Count (Production)",
              metrics=[{"metric_key": "defect_wac", "display_name": "Defect WAC (Production)",
                        "unit": "WAC", "target_numeric": "0.0", "direction": "LOWER_BETTER",
                        "is_primary": True}],
              parameters=[
                  {"param_key": "severity_weights", "param_value": "1:1,2:2,3:3,4:4"},
                  {"param_key": "variance_step_percent", "param_value": "10"},
                  {"param_key": "baseline_window_quarters", "param_value": "2"},
              ])),
    Case("MSAP-SLA017", "MSAP", "MSAP UAT Defect WAC (same metric as SLA016, must not 409)",
         _sla("MSAP-SLA017", "MSAP", "wac",
              "Production Defect Weighted Average Count (UAT)",
              metrics=[{"metric_key": "defect_wac", "display_name": "Defect WAC (UAT)",
                        "unit": "WAC", "target_numeric": "0.0", "direction": "LOWER_BETTER",
                        "is_primary": True}],
              parameters=[
                  {"param_key": "severity_weights", "param_value": "1:1,2:2,3:3,4:4"},
                  {"param_key": "variance_step_percent", "param_value": "10"},
                  {"param_key": "baseline_window_quarters", "param_value": "2"},
              ])),
    Case("MSAP-SLA018", "MSAP", "MSAP Tools Uptime band_accumulation",
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
              ])),
    Case("MSAP-SLA019", "MSAP", "MSAP Monitoring Coverage point_accumulation",
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
              ])),
    Case("MSAP-SLA020", "MSAP", "MSAP Project Docs Delay fixed_escalation",
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
              ])),
    # Site visit — shared field (PMU also uses it)
    Case("MSAP-SLA021", "MSAP", "MSAP Site Visit Compliance band_accumulation",
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
              ])),
]

# ---------------------------------------------------------------------------
# MSIP SLAs
# ---------------------------------------------------------------------------

MSIP_CASES: List[Case] = [
    Case("MSIP-SLA001", "MSIP", "MSIP Network Uptime band_accumulation",
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
              ])),
    Case("MSIP-SLA002", "MSIP", "MSIP MTTR fixed_escalation",
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
              ])),
    Case("MSIP-SLA003", "MSIP", "MSIP Server Availability band_accumulation",
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
              ])),
    Case("MSIP-SLA004", "MSIP", "MSIP Backup Compliance band_accumulation",
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
              ])),
    Case("MSIP-SLA005", "MSIP", "MSIP P1 Ticket Resolution fixed_escalation",
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
              ])),
    Case("MSIP-SLA006", "MSIP", "MSIP Patch Application Compliance band_accumulation",
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
              ])),
    Case("MSIP-SLA007", "MSIP", "MSIP Vulnerability Closure band_accumulation",
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
              ])),
    Case("MSIP-SLA008", "MSIP", "MSIP MTBF band_accumulation",
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
              ])),
    Case("MSIP-SLA009", "MSIP", "MSIP Incident Response band_accumulation",
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
              ])),
    # Multi-metric SLA with compound_metric_rule=COMBINED
    Case("MSIP-SLA010", "MSIP", "MSIP Network Quality (latency+loss) COMBINED band_accumulation",
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
              ])),
]

# ---------------------------------------------------------------------------
# PMU SLAs
# ---------------------------------------------------------------------------

PMU_CASES: List[Case] = [
    Case("PMU-SLA001", "PMU", "PMU Report Submission Delay fixed_escalation",
         _sla("PMU-SLA001", "PMU", "fixed_escalation",
              "Report Submission Delay",
              metrics=[{"metric_key": "report_submission_delay_days",
                        "display_name": "Report Submission Delay (days)", "unit": "days",
                        "target_numeric": "0", "direction": "LOWER_BETTER", "is_primary": True}],
              lookup_table=[
                  {"lookup_key": "on_time", "lookup_value": "0.00", "sort_order": 1},
                  {"lookup_key": "delay_1_3", "lookup_value": "0.10", "sort_order": 2},
                  {"lookup_key": "delay_4_7", "lookup_value": "0.25", "sort_order": 3},
                  {"lookup_key": "delay_8_plus", "lookup_value": "0.50", "sort_order": 4},
              ])),
    Case("PMU-SLA002", "PMU", "PMU Site Visit Compliance band_accumulation",
         _sla("PMU-SLA002", "PMU", "band_accumulation",
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
              ])),
    Case("PMU-SLA003", "PMU", "PMU Query Response Delay fixed_escalation",
         _sla("PMU-SLA003", "PMU", "fixed_escalation",
              "Query Response Delay",
              metrics=[{"metric_key": "query_response_delay_days",
                        "display_name": "Query Response Delay (days)", "unit": "days",
                        "target_numeric": "0", "direction": "LOWER_BETTER", "is_primary": True}],
              lookup_table=[
                  {"lookup_key": "on_time", "lookup_value": "0.00", "sort_order": 1},
                  {"lookup_key": "delay_1_2", "lookup_value": "0.10", "sort_order": 2},
                  {"lookup_key": "delay_3_plus", "lookup_value": "0.25", "sort_order": 3},
              ])),
    Case("PMU-SLA004", "PMU", "PMU MTTR fixed_escalation (shared field cross-contract)",
         _sla("PMU-SLA004", "PMU", "fixed_escalation",
              "Mean Time to Repair — PMU",
              metrics=[{"metric_key": "mttr_hours", "display_name": "MTTR (hours)",
                        "unit": "hours", "target_numeric": "4.0", "direction": "LOWER_BETTER",
                        "is_primary": True}],
              lookup_table=[
                  {"lookup_key": "within_4h", "lookup_value": "0.00", "sort_order": 1},
                  {"lookup_key": "4_8h", "lookup_value": "0.25", "sort_order": 2},
                  {"lookup_key": "8_plus", "lookup_value": "1.00", "sort_order": 3},
              ])),
    Case("PMU-SLA005", "PMU", "PMU Governance Tool Failures band_accumulation",
         _sla("PMU-SLA005", "PMU", "band_accumulation",
              "Governance Tool Failures",
              metrics=[{"metric_key": "governance_tool_failures_count",
                        "display_name": "Governance Tool Failures (count)", "unit": "count",
                        "target_numeric": "0", "direction": "LOWER_BETTER", "is_primary": True}],
              condition_bands=[
                  {"metric_key": "governance_tool_failures_count", "band_label": "Zero",
                   "range_min": None, "range_max": "0", "range_unit": "count",
                   "rate_percent": "0.00", "sort_order": 1},
                  {"metric_key": "governance_tool_failures_count", "band_label": "1-3",
                   "range_min": "1", "range_max": "3", "range_unit": "count",
                   "rate_percent": "0.50", "sort_order": 2},
                  {"metric_key": "governance_tool_failures_count", "band_label": "4-plus",
                   "range_min": "3", "range_max": None, "range_unit": "count",
                   "rate_percent": "1.00", "sort_order": 3},
              ])),
    Case("PMU-SLA006", "PMU", "PMU Incorrect Recommendations band_accumulation",
         _sla("PMU-SLA006", "PMU", "band_accumulation",
              "Incorrect Recommendations Count",
              metrics=[{"metric_key": "incorrect_recommendations_count",
                        "display_name": "Incorrect Recommendations (count)", "unit": "count",
                        "target_numeric": "0", "direction": "LOWER_BETTER", "is_primary": True}],
              condition_bands=[
                  {"metric_key": "incorrect_recommendations_count", "band_label": "Zero",
                   "range_min": None, "range_max": "0", "range_unit": "count",
                   "rate_percent": "0.00", "sort_order": 1},
                  {"metric_key": "incorrect_recommendations_count", "band_label": "1-2",
                   "range_min": "1", "range_max": "2", "range_unit": "count",
                   "rate_percent": "0.25", "sort_order": 2},
                  {"metric_key": "incorrect_recommendations_count", "band_label": "3-plus",
                   "range_min": "2", "range_max": None, "range_unit": "count",
                   "rate_percent": "0.75", "sort_order": 3},
              ])),
]

# ---------------------------------------------------------------------------
# Edge-case / validation tests
# ---------------------------------------------------------------------------

EDGE_CASES: List[Case] = [
    # Duplicate sla_ref — must be 409
    Case("BSP-SLA001", "BSP", "[EXPECTED 409] Duplicate sla_ref BSP-SLA001",
         _sla("BSP-SLA001", "BSP", "band_accumulation", "Some Other Title",
              metrics=[{"metric_key": "fpir", "display_name": "FPIR (%)", "unit": "%",
                        "target_numeric": "0.1", "direction": "LOWER_BETTER", "is_primary": True}],
              condition_bands=[
                  {"metric_key": "fpir", "band_label": "Green",
                   "range_min": None, "range_max": "0.1", "rate_percent": "0.0",
                   "sort_order": 1},
              ]),
         expect_status=409),
    # Duplicate title in same contract_type — must be 409
    Case("BSP-SLA001B", "BSP", "[EXPECTED 409] Duplicate title in same contract_type",
         _sla("BSP-SLA001B", "BSP", "band_accumulation",
              "Failure to Print Identification Rate (FPIR)",  # same as BSP-SLA001
              metrics=[{"metric_key": "fpir", "display_name": "FPIR (%)", "unit": "%",
                        "target_numeric": "0.1", "direction": "LOWER_BETTER", "is_primary": True}],
              condition_bands=[
                  {"metric_key": "fpir", "band_label": "Green",
                   "range_min": None, "range_max": "0.1", "rate_percent": "0.0",
                   "sort_order": 1},
              ]),
         expect_status=409),
    # Missing condition_bands for band_accumulation — must be 422
    Case("BSP-INVALID01", "BSP", "[EXPECTED 422] band_accumulation without condition_bands",
         _sla("BSP-INVALID01", "BSP", "band_accumulation", "Missing Bands Test",
              metrics=[{"metric_key": "fpir", "display_name": "FPIR (%)", "unit": "%",
                        "target_numeric": "0.1", "direction": "LOWER_BETTER", "is_primary": True}]),
         expect_status=422),
    # Missing lookup_table for fixed_escalation — must be 422
    Case("MSAP-INVALID01", "MSAP", "[EXPECTED 422] fixed_escalation without lookup_table",
         _sla("MSAP-INVALID01", "MSAP", "fixed_escalation", "Missing Lookup Test",
              metrics=[{"metric_key": "report_submission_delay_days",
                        "display_name": "Delay", "unit": "days", "target_numeric": "0",
                        "direction": "LOWER_BETTER", "is_primary": True}]),
         expect_status=422),
    # Invalid measurement_interval — must be 422
    Case("BSP-INVALID02", "BSP", "[EXPECTED 422] invalid measurement_interval",
         {**_sla("BSP-INVALID02", "BSP", "band_accumulation", "Bad Interval",
                 metrics=[{"metric_key": "fpir", "display_name": "FPIR", "unit": "%",
                           "target_numeric": "0.1", "direction": "LOWER_BETTER",
                           "is_primary": True}],
                 condition_bands=[
                     {"metric_key": "fpir", "band_label": "X",
                      "range_min": None, "range_max": "0.1", "rate_percent": "0.0",
                      "sort_order": 1},
                 ]),
          "measurement_interval": "BIWEEKLY"},
         expect_status=422),
    # ONE_TIME interval — valid, must be 201
    Case("BSP-MILE001", "BSP", "[EXPECTED 201] ONE_TIME measurement_interval on fixed_escalation",
         _sla("BSP-MILE001", "BSP", "fixed_escalation",
              "BSP Resource Onboarding Milestone ONE_TIME Test",
              measurement_interval="ONE_TIME",
              reporting_interval="MONTHLY",
              ld_computation_base="FIXED_AMOUNT",
              metrics=[{"metric_key": "resource_onboard_delay_days",
                        "display_name": "Onboarding Delay (days)", "unit": "days",
                        "target_numeric": "0", "direction": "LOWER_BETTER", "is_primary": True}],
              parameters=[{"param_key": "fixed_ld_amount", "param_value": "250000"}],
              lookup_table=[
                  {"lookup_key": "on_time", "lookup_value": "0.00", "sort_order": 1},
                  {"lookup_key": "delay_1_7", "lookup_value": "0.50", "sort_order": 2},
              ]),
         expect_status=201),
]

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    all_cases = BSP_CASES + MSAP_CASES + MSIP_CASES + PMU_CASES + EDGE_CASES
    print(f"Running {len(all_cases)} SLA onboarding test cases against {BASE}")
    results = run(all_cases)
    failures = print_report(results)
    sys.exit(failures)
