"""Named request / response examples surfaced in the Swagger UI.

Every business route in this service references one or more of these
constants via ``responses=`` (for response bodies) or ``examples=`` (for
multipart form fields). Keeping them in one module avoids drift between
the docs and the code, and means a schema-shape change is updated in
exactly one place.

Two helpers at the bottom (``ok`` and ``err``) wrap a sample body in the
HAL+JSON envelope so the example shown in Swagger matches what callers
actually receive.
"""
from __future__ import annotations

from typing import Any, Dict


# ----------------------------------------------------------------------------
# Envelope helpers
# ----------------------------------------------------------------------------

def ok(data: Any, *, message: str = "OK") -> Dict[str, Any]:
    """Wrap a body in the success envelope used by ``api_response(...)``."""
    return {
        "success": True,
        "message": message,
        "data": data,
    }


def err(message: str, *, code: str = "validation_error", status: int = 422) -> Dict[str, Any]:
    """Standard failure shape — matches the error middleware's output."""
    return {
        "success": False,
        "message": message,
        "error": {"code": code, "status": status},
    }


def hal(element_type: str, data: Dict[str, Any], self_url: str) -> Dict[str, Any]:
    """A single HAL resource — what every detail endpoint returns inside ``data``."""
    return {
        "_type": element_type,
        "data": data,
        "_links": {"self": {"href": self_url}},
    }


def hal_collection(elements: list, total: int | None = None) -> Dict[str, Any]:
    """A HAL collection — wraps the elements + pagination metadata."""
    return {
        "_embedded": {"elements": elements},
        "total": total if total is not None else len(elements),
        "page_size": max(len(elements), 1),
    }


# ----------------------------------------------------------------------------
# Domain objects (the raw shapes; envelopes are added at route time)
# ----------------------------------------------------------------------------

SAMPLE_SLA_FROM_RFP_PAYLOAD: Dict[str, Any] = {
    "sla_ref": "PMU-SLA001",
    "title": "Non-submission of deliverable",
    "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
    "contract_type": "PMU",
    "category_code": "DELIVERABLE_SUBMISSION",
    "definition": "Failure to submit the deliverable on or before the agreed date.",
    "scope": "Applies to all Phase-1 deliverables D1 through D8.",
    "data_source": "Project Tracker — deliverable submission timestamps.",
    "calculation": "LD = 0.5% of deliverable cost per week of delay; part-weeks count as full weeks.",
    "reports_submitted_to": "Concerned UIDAI Stakeholders",
    "measurement_interval": "ONE_TIME",
    "reporting_interval": "QUARTERLY",
    "applied_on": "FIXED_AMOUNT",
    "effective_from": "2024-04-01",
    "effective_until": None,
    "measurement": {"display_name": "Weeks delayed", "unit": "weeks"},
    "secondary_measurement": None,
    "target_rows": [],
    "linear_escalation": {"rate_per_unit_percent": "0.5", "unit": "week", "grace_units": 0, "max_units": 20},
    "placeholders": [
        {
            "key": "ld_base_amount",
            "label": "Cost of this deliverable (₹)",
            "type": "money",
            "required": True,
            "default_from": None,
            "help": "Used as the LD% base for this deliverable.",
        }
    ],
}


SAMPLE_SLA_JSON_PAYLOAD: Dict[str, Any] = {
    "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
    "contract_type": "PMU",
    "formula_type": "point_accumulation",
    "sla_ref": "PMU-SLA005",
    "title": "Resource Replacements per quarter",
    "description": "Number of contracted resources replaced during the quarter.",
    "category": "Resource Management",
    "scope_text": "Applies across all resources deployed under the PMC contract.",
    "data_source": "HR Onboarding Tracker",
    "calculation_method": "Count of replacements during the quarter.",
    "reports_submitted_to": "Concerned UIDAI Stakeholders",
    "measurement_interval": "QUARTERLY",
    "reporting_interval": "QUARTERLY",
    "baseline_type": "STATIC",
    "compound_metric_rule": "INDEPENDENT",
    "ld_aggregation_method": "SUM",
    "ld_computation_base": "QUARTERLY_PAYMENT",
    "effective_from": "2024-04-01",
    "metrics": [
        {
            "metric_key": "replacements_per_quarter",
            "display_name": "Replacements / quarter",
            "unit": "count",
            "target_numeric": "1",
            "direction": "LOWER_BETTER",
            "is_primary": True,
        }
    ],
    "condition_bands": [
        {
            "metric_key": "replacements_per_quarter",
            "band_label": "Sev 0 (within target)",
            "range_min": None,
            "range_max": "1",
            "range_unit": "count",
            "severity_level": 0,
            "sort_order": 1,
        },
        {
            "metric_key": "replacements_per_quarter",
            "band_label": "Sev 4 (exceeded target)",
            "range_min": "1",
            "range_max": None,
            "range_unit": "count",
            "severity_level": 4,
            "sort_order": 2,
        },
    ],
    "placeholders": [],
}


SAMPLE_SLA_DETAIL_DATA: Dict[str, Any] = {
    "id": "a3e1b2c4-1111-2222-3333-444455556666",
    "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
    "contract_type": "PMU",
    "formula_type": "point_accumulation",
    "sla_ref": "PMU-SLA005",
    "title": "Resource Replacements per quarter",
    "category": "Resource Management",
    "status": "ACTIVE",
    "effective_from": "2024-04-01",
    "effective_until": None,
    "placeholders": [],
    "metrics": [
        {"metric_key": "replacements_per_quarter", "display_name": "Replacements / quarter",
         "unit": "count", "is_primary": True, "direction": "LOWER_BETTER",
         "target_numeric": "1", "target_date": None},
    ],
    "condition_bands": [
        {"band_label": "Sev 0 (within target)", "severity_level": 0,
         "range_min": None, "range_max": "1", "range_unit": "count"},
        {"band_label": "Sev 4 (exceeded target)", "severity_level": 4,
         "range_min": "1", "range_max": None, "range_unit": "count"},
    ],
}


SAMPLE_MAPPING_CREATE_PAYLOAD: Dict[str, Any] = {
    "activity_id": "act-d11-governance-tool",
    "sla_id": "a3e1b2c4-1111-2222-3333-444455556666",
    "effective_from": "2026-04-01",
    "effective_until": None,
    "overrides": {
        "t_anchor_date": "2026-04-01",
        "ld_base_amount": "1000000",
    },
}


SAMPLE_MAPPING_DATA: Dict[str, Any] = {
    "id": "m-9999-9999",
    "activity_id": "act-d11-governance-tool",
    "sla_id": "a3e1b2c4-1111-2222-3333-444455556666",
    "sla_ref": "PMU-SLA005",
    "sla_title": "Resource Replacements per quarter",
    "contract_type": "PMU",
    "formula_type": "point_accumulation",
    "category": "Resource Management",
    "status": "ACTIVE",
    "effective_from": "2026-04-01",
    "effective_until": None,
    "overrides": {
        "t_anchor_date": "2026-04-01",
        "ld_base_amount": "1000000",
    },
}


SAMPLE_MAPPING_EVALUATE_PAYLOAD: Dict[str, Any] = {
    "period_start": "2026-04-01",
    "period_end": "2026-06-30",
    "metric_observations": [
        {
            "metric_key": "replacements_per_quarter",
            "shape": "SINGLE_VALUE",
            "single_value": "2",
        }
    ],
}


SAMPLE_MAPPING_EVALUATE_RESPONSE_DATA: Dict[str, Any] = {
    "mapping_id": "m-9999-9999",
    "activity_id": "act-d11-governance-tool",
    "sla_id": "a3e1b2c4-1111-2222-3333-444455556666",
    "sla_ref": "PMU-SLA005",
    "contract_type": "PMU",
    "formula_type": "point_accumulation",
    "period_start": "2026-04-01",
    "period_end": "2026-06-30",
    "severity_level": 4,
    "accumulated_points": "8",
    "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
    "severity_master_source": "project",
    "breaches": [
        {
            "metric_key": "replacements_per_quarter",
            "band_label": "Sev 4 (exceeded target)",
            "observed_value": "2",
            "severity_level": 4,
            "points_contribution": "8",
            "rate_percent": None,
        }
    ],
    "guards": [],
    "notes": [],
    "overrides_applied": {"t_anchor_date": "2026-04-01"},
}


SAMPLE_ACTIVITY_EVALUATE_PAYLOAD: Dict[str, Any] = {
    "period_start": "2026-04-01",
    "period_end": "2026-06-30",
    "observations_by_sla_ref": {
        "PMU-SLA005": [
            {"metric_key": "replacements_per_quarter", "shape": "SINGLE_VALUE",
             "single_value": "2"}
        ]
    },
}


SAMPLE_ACTIVITY_EVALUATE_RESPONSE_DATA: Dict[str, Any] = {
    "activity_id": "act-d11-governance-tool",
    "period_start": "2026-04-01",
    "period_end": "2026-06-30",
    "mapping_results": [SAMPLE_MAPPING_EVALUATE_RESPONSE_DATA],
    "summary": {
        "mappings_evaluated": 1,
        "mappings_skipped": 0,
        "severity_breakdown": {"L4": 1},
        "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
        "severity_master_source": "project",
    },
}


SAMPLE_ATTACHMENT_DATA: Dict[str, Any] = {
    "id": "att-1234-5678",
    "sla_id": "a3e1b2c4-1111-2222-3333-444455556666",
    "file_id": "f8d4e5b1-9c2a-4cdc-bfa6-8e9f7d6a5b4c",
    "file_url": (
        "http://10.1.131.199/files/sla-attachments/"
        "f8d4e5b1-9c2a-4cdc-bfa6-8e9f7d6a5b4c-pmu-sla-001-evidence.png?Signature=..."
    ),
    "original_filename": "pmu-sla-001-evidence.png",
    "mime_type": "image/png",
    "size_bytes": 248123,
    "caption": "RFP §5.28.2.b — deliverable submission rule",
    "uploaded_by": "user-uuid-abc",
    "uploaded_at": "2026-06-10T11:22:33+00:00",
}


SAMPLE_SLA_CATEGORY_DATA: Dict[str, Any] = {
    "code": "RESOURCE_MANAGEMENT",
    "display_name": "Resource Management",
    "formula_type": "point_accumulation",
    "description": "Severity bands per occurrence count — replacements, KT overlap, etc.",
    "is_active": True,
}


SAMPLE_SEVERITY_LEVEL_DATA: Dict[str, Any] = {
    "id": "sm-1111",
    "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
    "level": 0,
    "points": -2,
    "label": "Sev 0 — on target / better than target",
}


SAMPLE_LD_BAND_DATA: Dict[str, Any] = {
    "id": "ld-1111",
    "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
    "points_threshold": 0,
    "ld_percent": "0",
    "label": "0 points — no LD",
}


SAMPLE_SEED_DEFAULTS_PAYLOAD: Dict[str, Any] = {
    "contract_types": ["PMU"],
    "overwrite": True,
    "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
}


SAMPLE_SEED_DEFAULTS_RESPONSE_DATA: Dict[str, Any] = {
    "seeded": 6,
    "overwritten": 5,
    "skipped": 0,
    "failed": [],
}


# ----------------------------------------------------------------------------
# Response example builders — bundled with the right envelope so route
# decorators only need a single import.
# ----------------------------------------------------------------------------

def _wrap_one(
    element_type: str, data: Dict[str, Any], self_url: str,
    *, message: str = "OK",
) -> Dict[str, Any]:
    return ok(hal(element_type, data, self_url), message=message)


def _wrap_many(element_type: str, datas: list[Dict[str, Any]], self_url: str) -> Dict[str, Any]:
    elements = [hal(element_type, d, f"{self_url}/{d.get('id', '?')}") for d in datas]
    return ok(hal_collection(elements))


# SLA Master
RESP_SLA_DETAIL = _wrap_one(
    "SlaMaster", SAMPLE_SLA_DETAIL_DATA,
    "/api/v3/sla-masters/a3e1b2c4-1111-2222-3333-444455556666",
    message="SLA loaded.",
)
RESP_SLA_LIST = _wrap_many(
    "SlaMaster", [SAMPLE_SLA_DETAIL_DATA], "/api/v3/sla-masters",
)
RESP_SLA_DSL = ok(
    {"sla_id": "a3e1b2c4-1111-2222-3333-444455556666",
     "dsl_version": 1,
     "dsl_source": "identification:\n  sla_ref: PMU-SLA005\n  title: Resource Replacements per quarter\n  category: Resource Management\n  contract_type: PMU\n# … truncated …\n"},
)
RESP_SLA_DELETED = ok({"id": "a3e1b2c4-1111-2222-3333-444455556666",
                      "status": "DELETED"},
                     message="SLA 'PMU-SLA005' deleted")

RESP_SEED_DEFAULTS = ok(SAMPLE_SEED_DEFAULTS_RESPONSE_DATA,
                       message="Seeded 6 new, refreshed 5 existing.")

# Mapping
RESP_MAPPING_DETAIL = _wrap_one(
    "SlaActivityMapping", SAMPLE_MAPPING_DATA,
    "/api/v3/sla-activity-mappings/m-9999-9999",
    message="SLA 'PMU-SLA005' mapped to activity 'act-d11-governance-tool'",
)
RESP_MAPPING_LIST = _wrap_many(
    "SlaActivityMapping", [SAMPLE_MAPPING_DATA], "/api/v3/sla-activity-mappings",
)
RESP_MAPPING_RETIRED = _wrap_one(
    "SlaActivityMapping",
    {**SAMPLE_MAPPING_DATA, "status": "RETIRED"},
    "/api/v3/sla-activity-mappings/m-9999-9999",
    message="Mapping 'm-9999-9999' retired",
)

# Evaluate
RESP_MAPPING_EVALUATE = ok(
    hal("MappingEvaluation", SAMPLE_MAPPING_EVALUATE_RESPONSE_DATA,
        "/api/v3/sla-activity-mappings/m-9999-9999/evaluate"),
)
RESP_ACTIVITY_EVALUATE = ok(
    hal("ActivityEvaluation", SAMPLE_ACTIVITY_EVALUATE_RESPONSE_DATA,
        "/api/v3/activities/act-d11-governance-tool/evaluate"),
)

# Attachment
RESP_ATTACHMENT_DETAIL = _wrap_one(
    "SlaAttachment", SAMPLE_ATTACHMENT_DATA,
    f"/api/v3/sla-masters/{SAMPLE_ATTACHMENT_DATA['sla_id']}/attachments/{SAMPLE_ATTACHMENT_DATA['id']}",
    message=f"Uploaded '{SAMPLE_ATTACHMENT_DATA['original_filename']}' to SLA",
)
RESP_ATTACHMENT_LIST = _wrap_many(
    "SlaAttachment", [SAMPLE_ATTACHMENT_DATA],
    f"/api/v3/sla-masters/{SAMPLE_ATTACHMENT_DATA['sla_id']}/attachments",
)
RESP_ATTACHMENT_REFRESH = ok({
    "id": SAMPLE_ATTACHMENT_DATA["id"],
    "file_url": SAMPLE_ATTACHMENT_DATA["file_url"] + "&fresh=1",
    "expires_in_seconds": 3600,
})
RESP_ATTACHMENT_DELETED = ok(
    {"id": SAMPLE_ATTACHMENT_DATA["id"], "filestore_removed": True},
    message="Attachment removed",
)

# Master catalogues
RESP_SLA_CATEGORIES = _wrap_many(
    "SlaCategory",
    [SAMPLE_SLA_CATEGORY_DATA,
     {"code": "DELIVERABLE_SUBMISSION", "display_name": "Deliverable Submission",
      "formula_type": "fixed_escalation",
      "description": "Linear LD per week / day until the deliverable is submitted.",
      "is_active": True}],
    "/api/v3/sla-categories",
)
RESP_SEVERITY_MASTER = _wrap_many(
    "SeverityLevel",
    [SAMPLE_SEVERITY_LEVEL_DATA,
     {**SAMPLE_SEVERITY_LEVEL_DATA, "id": "sm-2222", "level": 4, "points": 8,
      "label": "Sev 4 — significant breach"}],
    "/api/v3/severity-master/31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
)
RESP_LD_BANDS = _wrap_many(
    "ProjectLdBand",
    [SAMPLE_LD_BAND_DATA,
     {**SAMPLE_LD_BAND_DATA, "id": "ld-2222", "points_threshold": 8,
      "ld_percent": "4", "label": "8+ points — 4% LD"}],
    "/api/v3/ld-bands/31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
)

# Smaller catalogs — contract types, data fields, formula library, enums
SAMPLE_CONTRACT_TYPE_DATA: Dict[str, Any] = {
    "code": "PMU",
    "display_name": "Programme Management Unit",
    "description": "Consultancy services for PMC contracts under UIDAI.",
    "is_active": True,
}
RESP_CONTRACT_TYPE_DETAIL = _wrap_one(
    "ContractType", SAMPLE_CONTRACT_TYPE_DATA, "/api/v3/contract-types/PMU",
    message="Contract type 'PMU' created",
)
RESP_CONTRACT_TYPE_LIST = _wrap_many(
    "ContractType",
    [SAMPLE_CONTRACT_TYPE_DATA,
     {"code": "MSAP", "display_name": "Managed Services for Applications",
      "description": "Managed services contract type.", "is_active": True}],
    "/api/v3/contract-types",
)

SAMPLE_DATA_FIELD_DATA: Dict[str, Any] = {
    "field_name": "weeks_delayed",
    "display_name": "Weeks Delayed",
    "data_type": "INTEGER",
    "unit": "weeks",
    "description": "Number of full or part weeks past the agreed deliverable date.",
    "is_active": True,
}
RESP_DATA_FIELD_DETAIL = _wrap_one(
    "DataField", SAMPLE_DATA_FIELD_DATA,
    "/api/v3/data-fields/weeks_delayed",
    message="Data field 'weeks_delayed' created",
)
RESP_DATA_FIELD_LIST = _wrap_many(
    "DataField",
    [SAMPLE_DATA_FIELD_DATA,
     {"field_name": "replacements_per_quarter", "display_name": "Replacements / quarter",
      "data_type": "INTEGER", "unit": "count",
      "description": "Number of replacements in the quarter.", "is_active": True}],
    "/api/v3/data-fields",
)

RESP_SLA_ENUMS = ok({
    "contract_types": ["BSP", "MSAP", "MSIP", "PMU"],
    "formula_types": ["band_accumulation", "point_accumulation", "fixed_escalation", "wac"],
    "measurement_intervals": ["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "ONE_TIME"],
    "reporting_intervals": ["WEEKLY", "MONTHLY", "QUARTERLY", "ANNUAL"],
    "ld_computation_bases": ["QUARTERLY_PAYMENT", "ANNUAL_PAYMENT", "FIXED_AMOUNT"],
    "metric_directions": ["LOWER_BETTER", "HIGHER_BETTER"],
    "observation_shapes": ["SINGLE_VALUE", "DAILY_VALUES", "BAND_COUNTS", "WAC_BREAKDOWN"],
})

RESP_FORMULA_LIBRARY = _wrap_many(
    "FormulaType",
    [{"formula_type": "point_accumulation",
      "display_name": "Severity points (banded)",
      "description": "Each band carries a severity_level and points; points sum across the period.",
      "parameter_schema": {}},
     {"formula_type": "fixed_escalation",
      "display_name": "Linear LD (per unit)",
      "description": "Rate × delay-units. Used for deliverable / query SLAs.",
      "parameter_schema": {}}],
    "/api/v3/formula-library",
)


# Common error envelopes
RESP_NOT_FOUND = err("Resource not found", code="not_found", status=404)
RESP_VALIDATION_FAIL = err(
    "Field 'sla_ref' is required and must match ^[A-Z0-9_-]+$",
    code="validation_error", status=422,
)
RESP_CONFLICT = err(
    "SLA 'PMU-SLA005' already exists for project 31eefb48-…",
    code="duplicate_sla_ref", status=409,
)
RESP_SERVICE_DOWN = err(
    "file-store unavailable: HTTPConnectionError",
    code="file_store_unavailable", status=503,
)


def with_examples(*pairs: tuple[int, str, Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Bundle multiple (status, description, example) tuples into the
    `responses=` shape FastAPI expects on the route decorator."""
    return {
        status: {
            "description": description,
            "content": {"application/json": {"example": example}},
        }
        for (status, description, example) in pairs
    }
