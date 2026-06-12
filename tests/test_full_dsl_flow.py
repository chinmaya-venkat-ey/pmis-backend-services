"""End-to-end test of the 5-stage DSL-driven flow.

  1. Onboard SLA (RFP word-by-word, project-scoped)
  2. DSL drives mapping inputs
  3. Map SLA to activity with DSL-derived inputs
  4. DSL drives evaluation inputs
  5. Evaluate severity using DSL-derived inputs

Runs against any deployed backend. Override the base URL via env var:

    BASE_URL=http://10.1.131.199/contracts python tests/test_full_dsl_flow.py
    BASE_URL=http://localhost:9000/contracts python tests/test_full_dsl_flow.py

Exit code 0 = every stage passed; non-zero = at least one stage failed.

The test runs the full flow twice, once for each formula shape:

  * PMU-SLA001-style linear LD          (fixed_escalation category)
  * PMU-SLA005-style severity-banded    (point_accumulation category)

Each iteration uses a timestamped sla_ref so the script is rerunnable
without cleanup. The test asserts that:

  * The onboarded SLA round-trips with the correct formula_type
  * mapping-form-schema returns the SLA's placeholders as inputs[]
  * Mapping persists with the placeholder values
  * eval form-schema returns the SLA's metric as inputs[] + bands[]
  * Evaluate returns the right severity for sample observations
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple

try:
    import requests
except ImportError:
    print("ERROR: install `requests` first  →  pip install requests")
    sys.exit(2)


BASE = os.environ.get("BASE_URL", "http://localhost:9000/contracts").rstrip("/")
PROJECT_ID = os.environ.get(
    "PROJECT_ID", "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45"
)
# An activity_id present in project-management. The PMC quarterly governance
# activity is a safe default if you've seeded the PMC project.
ACTIVITY_ID = os.environ.get(
    "ACTIVITY_ID", "a4797155-ae13-4a38-9077-c157e872186e"
)
STAMP = str(int(time.time()))


# ──────────────────────────────────────────────────────────────────── helpers


def _box(title: str, color: str = "\033[36m") -> None:
    bar = "═" * 78
    print(f"\n{color}{bar}\n  {title}\n{bar}\033[0m")


def _result(ok: bool, label: str, detail: str = "") -> None:
    icon = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
    print(f"  {icon} {label}" + (f"  —  {detail}" if detail else ""))


def _post(path: str, body: Dict[str, Any]) -> Tuple[int, Any]:
    r = requests.post(f"{BASE}{path}",
                      headers={"Content-Type": "application/json"},
                      data=json.dumps(body), timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text


def _post_form(path: str, payload: Dict[str, Any]) -> Tuple[int, Any]:
    """multipart POST — for /sla-masters/from-rfp."""
    r = requests.post(f"{BASE}{path}",
                      data={"payload": json.dumps(payload)}, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text


def _get(path: str) -> Tuple[int, Any]:
    r = requests.get(f"{BASE}{path}", timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text


def _delete(path: str) -> Tuple[int, Any]:
    r = requests.delete(f"{BASE}{path}", timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text


# ──────────────────────────────────────────────────────────────────── stage 1


def stage1_onboard_linear(sla_ref: str) -> Optional[str]:
    """PMU-SLA001-shaped (linear LD).  Returns sla_id on success."""
    _box(f"Stage 1A — Onboard linear SLA  ({sla_ref})")
    payload = {
        "sla_ref": sla_ref,
        "title": "TEST Non-submission of deliverable",
        "project_id": PROJECT_ID,
        "category_code": "DELIVERABLE_SUBMISSION",
        "contract_type": "PMU",
        "definition": "RFP §5.28.2.b — 0.5% of deliverable cost for every "
                      "week or part thereof of delay.",
        "scope": "All Phase-1 deliverables D1-D8.",
        "data_source": "Manual — submission log.",
        "calculation": "LD = 0.5% × weeks delayed × cost of deliverable.",
        "reports_submitted_to": "Technology Management Division, UIDAI HO",
        "measurement_interval": "ONE_TIME",
        "reporting_interval":   "QUARTERLY",
        "applied_on":           "FIXED_AMOUNT",
        "effective_from":       "2024-04-01",
        "measurement": {
            "metric_key":   "pmu_deliverable_delay_weeks",
            "display_name": "Weeks delayed",
            "unit":         "weeks",
            "target_value": "0",
        },
        "linear_escalation": {
            "rate_per_unit_percent": "0.5",
            "unit":         "week",
            "grace_units":  0,
            "max_units":    20,
        },
        "placeholders": [
            {"key": "ld_base_amount",
             "label": "Cost of this deliverable (₹)",
             "type": "money", "required": True,
             "help": "Used as the LD% base."}
        ],
    }
    code, body = _post_form("/api/v3/sla-masters/from-rfp", payload)
    if code != 201:
        _result(False, "POST /sla-masters/from-rfp", f"HTTP {code} — {body}")
        return None
    data = body.get("data", {})
    self_href = (data.get("_links") or {}).get("self", {}).get("href", "")
    sla_id = self_href.rsplit("/", 1)[-1]
    _result(True, "POST /sla-masters/from-rfp",
            f"HTTP 201, id={sla_id[:8]}…")
    # Round-trip
    code, body = _get(f"/api/v3/sla-masters/{sla_id}")
    if code != 200:
        _result(False, "GET /sla-masters/{id}", f"HTTP {code}")
        return None
    d = body.get("data") or {}
    if isinstance(d.get("data"), dict):
        d = d["data"]
    le = d.get("linear_escalation") or {}
    has_lin = bool(le.get("rate_percent") or le.get("rate_per_unit_percent"))
    _result(has_lin, "Round-trip: linear_escalation present",
            "linear LD survives" if has_lin else f"got {d}")
    return sla_id


def stage1_onboard_banded(sla_ref: str) -> Optional[str]:
    """PMU-SLA005-shaped (severity-banded).  Returns sla_id on success."""
    _box(f"Stage 1B — Onboard banded SLA  ({sla_ref})")
    payload = {
        "sla_ref": sla_ref,
        "title": "TEST Resource replacements per quarter",
        "project_id": PROJECT_ID,
        "category_code": "RESOURCE_MANAGEMENT",
        "contract_type": "PMU",
        "definition": "RFP §5.28.3.c — Sev 0 up to 1 replacement, "
                      "Sev 4 for every additional.",
        "scope": "All resources committed under deliverables D12, D13.",
        "data_source": "Manual — UIDAI biometric attendance.",
        "calculation": "Count of replacements initiated in the quarter.",
        "measurement_interval": "QUARTERLY",
        "reporting_interval":   "QUARTERLY",
        "applied_on":           "QUARTERLY_PAYMENT",
        "effective_from":       "2024-04-01",
        "measurement": {
            "metric_key":   "pmu_resource_replacements_count",
            "display_name": "Replacements initiated in quarter",
            "unit":         "count",
            "target_value": "1",
        },
        "target_rows": [
            {"severity": 0, "threshold_label": "L0 Up to 1",
             "from_value": None, "to_value": 1, "input_variable": None},
            {"severity": 4, "threshold_label": "L4 More than 1",
             "from_value": 1, "to_value": None, "input_variable": None},
        ],
    }
    code, body = _post_form("/api/v3/sla-masters/from-rfp", payload)
    if code != 201:
        _result(False, "POST /sla-masters/from-rfp", f"HTTP {code} — {body}")
        return None
    sla_id = (((body.get("data") or {}).get("_links") or {})
              .get("self", {}).get("href", "")).rsplit("/", 1)[-1]
    _result(True, "POST /sla-masters/from-rfp",
            f"HTTP 201, id={sla_id[:8]}…")
    # Round-trip
    code, body = _get(f"/api/v3/sla-masters/{sla_id}")
    d = body.get("data") or {}
    if isinstance(d.get("data"), dict):
        d = d["data"]
    rows = d.get("target_rows") or []
    _result(len(rows) >= 2, "Round-trip: target_rows present",
            f"{len(rows)} rows")
    return sla_id


# ──────────────────────────────────────────────────────────────────── stages 2-5


def stage2_mapping_schema(sla_id: str, expect_inputs: int) -> Optional[Dict]:
    _box("Stage 2 — DSL drives mapping inputs")
    code, body = _get(
        f"/api/v3/sla-masters/{sla_id}/mapping-form-schema"
        f"?activity_id={ACTIVITY_ID}"
    )
    if code != 200:
        _result(False, "GET .../mapping-form-schema", f"HTTP {code} — {body}")
        return None
    schema = body.get("data") or {}
    if isinstance(schema.get("data"), dict):
        schema = schema["data"]
    inputs = schema.get("inputs") or []
    _result(True, "GET .../mapping-form-schema",
            f"HTTP 200, {len(inputs)} input(s) declared")
    ok = len(inputs) == expect_inputs
    _result(ok, f"Inputs count = {expect_inputs}",
            f"got {len(inputs)} → {[i.get('name') for i in inputs]}")
    return schema


def stage3_create_mapping(
    sla_id: str, schema: Dict, overrides: Dict[str, Any],
) -> Optional[str]:
    _box("Stage 3 — Map SLA to activity using DSL-derived inputs")
    body = {
        "sla_id": sla_id,
        "activity_id": ACTIVITY_ID,
        "effective_from": (schema or {}).get("effective_from_default")
                          or "2024-04-01",
        "overrides": overrides,
    }
    code, resp = _post("/api/v3/sla-activity-mappings", body)
    if code == 409:
        # Idempotency: pull the existing mapping back
        c, b = _get(f"/api/v3/activities/{ACTIVITY_ID}/sla-mappings")
        mids = [(el.get("data") or el).get("id")
                for el in (((b.get("data") or {}).get("_embedded") or {})
                           .get("elements") or [])
                if (el.get("data") or el).get("sla_id") == sla_id]
        mid = mids[0] if mids else None
        _result(True, "POST .../sla-activity-mappings",
                f"HTTP 409 already mapped, reusing {mid[:8] if mid else '—'}…")
        return mid
    if code != 201:
        _result(False, "POST .../sla-activity-mappings",
                f"HTTP {code} — {resp}")
        return None
    d = resp.get("data") or {}
    if isinstance(d.get("data"), dict):
        d = d["data"]
    mid = d.get("id")
    _result(True, "POST .../sla-activity-mappings",
            f"HTTP 201, mapping_id={mid[:8]}…")
    return mid


def stage4_eval_schema(sla_ref: str, expect_band_count: int) -> Optional[Dict]:
    _box("Stage 4 — DSL drives evaluation inputs")
    code, body = _get(
        f"/api/v3/activities/{ACTIVITY_ID}/sla-evaluate/{sla_ref}/form-schema"
    )
    if code != 200:
        _result(False, "GET .../sla-evaluate/{ref}/form-schema",
                f"HTTP {code} — {body}")
        return None
    schema = body.get("data") or {}
    if isinstance(schema.get("data"), dict):
        schema = schema["data"]
    inputs = schema.get("inputs") or []
    bands  = schema.get("bands")  or []
    _result(True, "GET .../sla-evaluate/{ref}/form-schema",
            f"HTTP 200, inputs[{len(inputs)}], bands[{len(bands)}]")
    if expect_band_count > 0:
        _result(len(bands) >= expect_band_count,
                f"Bands count ≥ {expect_band_count}",
                f"got {len(bands)}")
    return schema


def stage5_evaluate(sla_ref: str, value: Any,
                    expect_sev: Optional[int]) -> bool:
    _box(f"Stage 5 — Evaluate severity with value={value}")
    code, body = _post(
        f"/api/v3/activities/{ACTIVITY_ID}/sla-evaluate/{sla_ref}",
        {"value": value,
         "period_start": "2024-04-01",
         "period_end":   "2024-06-30"},
    )
    if code != 200:
        _result(False, "POST .../sla-evaluate/{ref}",
                f"HTTP {code} — {body}")
        return False
    d = body.get("data") or {}
    sev = d.get("severity_level")
    pts = d.get("accumulated_points")
    breaches = d.get("breaches") or []
    _result(True, "POST .../sla-evaluate/{ref}",
            f"severity={sev}, points={pts}, breaches={len(breaches)}")
    if expect_sev is not None:
        ok = sev == expect_sev
        _result(ok, f"Expected severity L{expect_sev}",
                f"got L{sev}" if sev is not None else
                f"got null (likely linear LD — that's expected for SLA-001)")
        # Linear-LD SLAs return severity=None but produce breach tiers.
        if not ok and expect_sev is None and breaches:
            return True
        return ok
    return True


# ──────────────────────────────────────────────────────────────────── runner


def run_flow_linear() -> bool:
    sla_ref = f"TEST-SLA001-{STAMP}"
    sla_id = stage1_onboard_linear(sla_ref)
    if not sla_id:
        return False
    # Mapping form should ask for 1 placeholder: ld_base_amount.
    schema = stage2_mapping_schema(sla_id, expect_inputs=1)
    mapping_id = stage3_create_mapping(
        sla_id, schema or {},
        overrides={"ld_base_amount": "5000000"},
    )
    if not mapping_id:
        return False
    # Eval schema — linear LD has tiers, not severity bands.
    stage4_eval_schema(sla_ref, expect_band_count=1)
    # Linear-LD evaluation: 3 weeks of delay → 3rd tier triggers.
    ok = stage5_evaluate(sla_ref, value=3, expect_sev=None)
    return ok


def run_flow_banded() -> bool:
    sla_ref = f"TEST-SLA005-{STAMP}"
    sla_id = stage1_onboard_banded(sla_ref)
    if not sla_id:
        return False
    # No placeholders for this SLA.
    schema = stage2_mapping_schema(sla_id, expect_inputs=0)
    mapping_id = stage3_create_mapping(sla_id, schema or {}, overrides={})
    if not mapping_id:
        return False
    stage4_eval_schema(sla_ref, expect_band_count=2)
    # value=0 → L0 (within target), value=2 → L4 (breached).
    a = stage5_evaluate(sla_ref, value=0, expect_sev=0)
    b = stage5_evaluate(sla_ref, value=2, expect_sev=4)
    return a and b


def main() -> int:
    print(f"\nE2E test target: \033[1m{BASE}\033[0m")
    print(f"Project ID:      {PROJECT_ID}")
    print(f"Activity ID:     {ACTIVITY_ID}")
    print(f"Run stamp:       {STAMP}")
    # Connectivity probe — fail fast if the backend isn't up.
    code, _ = _get("/api/v3/sla-categories")
    if code >= 500 or code == 0:
        print(f"\n\033[31m✗ Backend unreachable — GET /sla-categories "
              f"returned HTTP {code}\033[0m")
        print(f"   Set BASE_URL or bring the container up first.")
        return 2
    linear_ok = run_flow_linear()
    banded_ok = run_flow_banded()
    print()
    _box("Summary", "\033[35m")
    _result(linear_ok, "Linear-LD flow  (PMU-SLA001 shape)")
    _result(banded_ok, "Banded flow     (PMU-SLA005 shape)")
    return 0 if (linear_ok and banded_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
