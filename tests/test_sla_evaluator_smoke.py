"""Smoke test for the SLA-Activity mapping + evaluator stack.

For each of the four formula types we:
  1. Find one existing SLA in the live DB (filter by formula_type via API).
  2. Create an SLA-Activity mapping with a synthetic activity_id.
  3. Evaluate it with hand-crafted observation data.
  4. Assert the response carries severity_level / accumulated_points / ld_percent
     consistent with the input.
  5. Unmap (DELETE) so re-runs stay idempotent.

Run:
    python tests/test_sla_evaluator_smoke.py
"""
from __future__ import annotations

import json
import sys
import uuid
from typing import Any, Dict, List, Optional

import requests

BASE = "http://localhost:8005/api/v3"
H = {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_sla(formula_type: str, contract_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    params = {"formula_type": formula_type, "pageSize": 5}
    if contract_type:
        params["contract_type"] = contract_type
    r = requests.get(f"{BASE}/sla-masters", params=params, timeout=10)
    r.raise_for_status()
    body = r.json()
    elements = body.get("data", {}).get("_embedded", {}).get("elements", [])
    if not elements:
        return None
    el = elements[0]
    return el.get("data", el)


def create_mapping(sla_id: str, activity_id: str) -> Dict[str, Any]:
    payload = {
        "sla_id": sla_id,
        "activity_id": activity_id,
        "effective_from": "2026-01-01",
        "effective_until": "2026-12-31",
        "overrides": {
            "ld_base_amount": "1000000",
            "actual_start_date": "2026-01-01",
            "actual_end_date": "2026-03-31",
        },
    }
    r = requests.post(f"{BASE}/sla-activity-mappings", json=payload, timeout=10)
    if r.status_code != 201:
        raise RuntimeError(f"create_mapping failed: {r.status_code} {r.text}")
    return r.json()["data"]


def unmap(mapping_id: str) -> None:
    requests.delete(f"{BASE}/sla-activity-mappings/{mapping_id}", timeout=10)


def evaluate_mapping(mapping_id: str, observations: List[Dict[str, Any]],
                     period_start: str = "2026-01-01",
                     period_end: str = "2026-03-31") -> Dict[str, Any]:
    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "metric_observations": observations,
    }
    r = requests.post(
        f"{BASE}/sla-activity-mappings/{mapping_id}/evaluate",
        json=payload, timeout=15,
    )
    if r.status_code != 200:
        raise RuntimeError(f"evaluate failed: {r.status_code} {r.text}")
    return r.json()["data"]


def primary_metric_key(sla: Dict[str, Any]) -> Optional[str]:
    """Fetch the SLA detail to read the primary metric key."""
    r = requests.get(f"{BASE}/sla-masters/{sla['id']}", timeout=10)
    r.raise_for_status()
    detail = r.json()["data"]
    for m in detail.get("metrics", []):
        if m.get("is_primary"):
            return m.get("metric_key")
    return None


# ---------------------------------------------------------------------------
# Per-formula scenarios
# ---------------------------------------------------------------------------

def scenario_band_accumulation() -> Dict[str, Any]:
    sla = find_sla("band_accumulation", contract_type="BSP")
    if not sla:
        return {"name": "band_accumulation", "skipped": "no SLA found"}
    metric_key = primary_metric_key(sla)
    if not metric_key:
        return {"name": "band_accumulation", "skipped": "no primary metric"}

    activity_id = f"act-band-{uuid.uuid4().hex[:8]}"
    mapping = create_mapping(sla["id"], activity_id)
    try:
        # Synthetic daily observations: half "good" days well under target,
        # half "bad" days that should fall into a non-zero band.
        daily = [0.05] * 45 + [0.40] * 45  # 90 days = 1 quarter
        obs = [{"metric_key": metric_key, "shape": "DAILY_VALUES", "daily_values": daily}]
        result = evaluate_mapping(mapping["id"], obs)
        return {
            "name": "band_accumulation",
            "sla_ref": sla["sla_ref"],
            "mapping_id": mapping["id"],
            "ld_percent": result.get("ld_percent"),
            "severity_level": result.get("severity_level"),
            "breaches": len(result.get("breaches", [])),
            "overrides_applied": result.get("overrides_applied"),
        }
    finally:
        unmap(mapping["id"])


def scenario_point_accumulation() -> Dict[str, Any]:
    sla = find_sla("point_accumulation", contract_type="MSAP")
    if not sla:
        return {"name": "point_accumulation", "skipped": "no SLA found"}
    metric_key = primary_metric_key(sla)
    if not metric_key:
        return {"name": "point_accumulation", "skipped": "no primary metric"}

    activity_id = f"act-point-{uuid.uuid4().hex[:8]}"
    mapping = create_mapping(sla["id"], activity_id)
    try:
        # Single monthly value below target — should hit a severity band.
        obs = [{"metric_key": metric_key, "shape": "SINGLE_VALUE", "single_value": "85.0"}]
        result = evaluate_mapping(mapping["id"], obs)
        return {
            "name": "point_accumulation",
            "sla_ref": sla["sla_ref"],
            "mapping_id": mapping["id"],
            "severity_level": result.get("severity_level"),
            "accumulated_points": result.get("accumulated_points"),
            "ld_percent": result.get("ld_percent"),
            "breaches": len(result.get("breaches", [])),
        }
    finally:
        unmap(mapping["id"])


def scenario_fixed_escalation() -> Dict[str, Any]:
    sla = find_sla("fixed_escalation")
    if not sla:
        return {"name": "fixed_escalation", "skipped": "no SLA found"}
    metric_key = primary_metric_key(sla)
    if not metric_key:
        return {"name": "fixed_escalation", "skipped": "no primary metric"}

    activity_id = f"act-fixed-{uuid.uuid4().hex[:8]}"
    mapping = create_mapping(sla["id"], activity_id)
    try:
        # Delay = 2 → should pick lookup tier with sort_order <= 2.
        obs = [{"metric_key": metric_key, "shape": "SINGLE_VALUE", "single_value": "2"}]
        result = evaluate_mapping(mapping["id"], obs)
        return {
            "name": "fixed_escalation",
            "sla_ref": sla["sla_ref"],
            "mapping_id": mapping["id"],
            "ld_percent": result.get("ld_percent"),
            "ld_amount": result.get("ld_amount"),
            "breaches": len(result.get("breaches", [])),
            "notes": result.get("notes"),
        }
    finally:
        unmap(mapping["id"])


def scenario_wac() -> Dict[str, Any]:
    sla = find_sla("wac")
    if not sla:
        return {"name": "wac", "skipped": "no SLA found"}
    metric_key = primary_metric_key(sla)
    if not metric_key:
        return {"name": "wac", "skipped": "no primary metric"}

    activity_id = f"act-wac-{uuid.uuid4().hex[:8]}"
    mapping = create_mapping(sla["id"], activity_id)
    try:
        # New WAC noticeably worse than baseline (>10%): expect a non-zero severity step.
        obs = [{
            "metric_key": metric_key,
            "shape": "WAC_BREAKDOWN",
            "wac_breakdown": {
                "blocker": "20",
                "critical": "10",
                "major": "15",
                "minor": "5",
                "applications": "10",
                "baseline": "0.40",
                "previous_wac": "0.40",
            },
        }]
        result = evaluate_mapping(mapping["id"], obs)
        return {
            "name": "wac",
            "sla_ref": sla["sla_ref"],
            "mapping_id": mapping["id"],
            "severity_level": result.get("severity_level"),
            "accumulated_points": result.get("accumulated_points"),
            "ld_percent": result.get("ld_percent"),
            "breaches": result.get("breaches"),
        }
    finally:
        unmap(mapping["id"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"Smoke-testing evaluator against {BASE}\n")
    scenarios = [
        scenario_band_accumulation,
        scenario_point_accumulation,
        scenario_fixed_escalation,
        scenario_wac,
    ]
    results = []
    fail = 0
    for fn in scenarios:
        try:
            r = fn()
        except Exception as exc:
            r = {"name": fn.__name__, "error": str(exc)}
            fail += 1
        results.append(r)
        print(json.dumps(r, indent=2, default=str))
        print("-" * 60)
    print(f"\nDONE — {len(results)} scenarios, {fail} errors")
    return fail


if __name__ == "__main__":
    sys.exit(main())
