"""Master reference data routes.

Endpoints:
  GET   /api/v3/contract-types                                   list contract types
  GET   /api/v3/data-fields                                      list SLA data fields (with optional filter)
  GET   /api/v3/projects/{project_id}/severity-master            list severity levels for a project
  POST  /api/v3/projects/{project_id}/severity-master            replace severity levels
  PATCH /api/v3/projects/{project_id}/severity-master/{level}    update points or label for a level
  GET   /api/v3/projects/{project_id}/ld-bands                   list points->LD% bands for a project
  POST  /api/v3/projects/{project_id}/ld-bands                   replace LD bands
  PATCH /api/v3/projects/{project_id}/ld-bands/{band_id}         update a single LD band
  POST  /api/v3/projects/{project_id}/seed-master-defaults       seed both tables with RFP defaults
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from app.controllers.master_controller import MasterController
from app.core.openapi_examples import (
    RESP_CONTRACT_TYPE_DETAIL,
    RESP_CONTRACT_TYPE_LIST,
    RESP_DATA_FIELD_DETAIL,
    RESP_DATA_FIELD_LIST,
    RESP_FORMULA_LIBRARY,
    RESP_LD_BANDS,
    RESP_NOT_FOUND,
    RESP_SEED_DEFAULTS,
    RESP_SEVERITY_MASTER,
    RESP_SLA_CATEGORIES,
    RESP_SLA_ENUMS,
    RESP_VALIDATION_FAIL,
    with_examples,
)
from app.core.response import api_response, hal_collection, hal_resource
from app.dependencies import get_master_controller
from app.schemas.master import (
    ContractTypeCreateRequest,
    ContractTypeUpdateRequest,
    DataFieldCreateRequest,
    DataFieldUpdateRequest,
    LdBandSetRequest,
    LdBandUpdateRequest,
    SeverityLevelUpdateRequest,
    SeverityMasterSetRequest,
    SLA_ENUMS,
)

router = APIRouter(tags=["Masters"])


# ---------------------------------------------------------------------------
# Contract types — system-wide read-only
# ---------------------------------------------------------------------------

@router.post(
    "/contract-types",
    status_code=201,
    summary="Create a new contract type",
    responses=with_examples(
        (201, "Contract type created.", RESP_CONTRACT_TYPE_DETAIL),
        (422, "Schema validation failed.", RESP_VALIDATION_FAIL),
    ),
)
def create_contract_type(
    payload: ContractTypeCreateRequest,
    ctrl: MasterController = Depends(get_master_controller),
):
    result = ctrl.create_contract_type(payload)
    return api_response(
        data=hal_resource(
            "ContractType", result.model_dump(),
            self_link=f"/api/v3/contract-types/{result.code}",
        ),
        message=f"Contract type '{result.code}' created",
        status=201,
    )


@router.patch(
    "/contract-types/{code}",
    summary="Update display name or description",
    responses=with_examples(
        (200, "Contract type updated.", RESP_CONTRACT_TYPE_DETAIL),
        (404, "Contract type not found.", RESP_NOT_FOUND),
    ),
)
def update_contract_type(
    code: str,
    payload: ContractTypeUpdateRequest,
    ctrl: MasterController = Depends(get_master_controller),
):
    result = ctrl.update_contract_type(code, payload)
    return api_response(
        data=hal_resource(
            "ContractType", result.model_dump(),
            self_link=f"/api/v3/contract-types/{result.code}",
        ),
        message=f"Contract type '{code}' updated",
        status=200,
    )


@router.delete(
    "/contract-types/{code}",
    summary="Soft-delete a contract type (sets is_active=false)",
    responses=with_examples(
        (200, "Contract type deactivated.", RESP_CONTRACT_TYPE_DETAIL),
        (404, "Contract type not found.", RESP_NOT_FOUND),
    ),
)
def delete_contract_type(
    code: str,
    ctrl: MasterController = Depends(get_master_controller),
):
    result = ctrl.delete_contract_type(code)
    return api_response(
        data=hal_resource(
            "ContractType", result.model_dump(),
            self_link=f"/api/v3/contract-types/{result.code}",
        ),
        message=f"Contract type '{code}' deactivated",
        status=200,
    )


@router.get(
    "/contract-types",
    summary="List all contract types",
    responses=with_examples(
        (200, "All contract types (active and soft-deleted).", RESP_CONTRACT_TYPE_LIST),
    ),
)
def list_contract_types(ctrl: MasterController = Depends(get_master_controller)):
    items = ctrl.list_contract_types()
    elements = [
        hal_resource(
            "ContractType", r.model_dump(),
            self_link=f"/api/v3/contract-types/{r.code}",
        )
        for r in items
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


# ---------------------------------------------------------------------------
# SLA enum catalog — all dropdown values for SLA onboarding form
# ---------------------------------------------------------------------------

@router.get(
    "/sla-enums",
    summary="All allowed enum values for SLA onboarding dropdowns",
    responses=with_examples(
        (200, "Dictionary of enum buckets the FE picker uses.", RESP_SLA_ENUMS),
    ),
)
def list_sla_enums():
    return api_response(
        data=hal_resource(
            "SlaEnums",
            SLA_ENUMS,
            self_link="/api/v3/sla-enums",
        ),
        status=200,
    )


# ---------------------------------------------------------------------------
# SLA categories — user-facing labels shown on the onboarding form. Each
# category resolves to a formula_type behind the scenes. Seeded by
# migration 0015 and editable via direct DB writes for now (no admin UI
# yet, but the table follows the same pattern as contract_type_master).
# ---------------------------------------------------------------------------

@router.get(
    "/sla-categories",
    summary="List active SLA categories (FE picker)",
    responses=with_examples(
        (200, "All active categories with display_name and formula_type.",
         RESP_SLA_CATEGORIES),
    ),
)
def list_sla_categories(ctrl: MasterController = Depends(get_master_controller)):
    items = ctrl.list_sla_categories()
    elements = [
        hal_resource(
            "SlaCategory", r.model_dump(),
            self_link=f"/api/v3/sla-categories/{r.code}",
        )
        for r in items
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


# ---------------------------------------------------------------------------
# /sla-input-variables — catalog of measurement keys (metric_keys + data fields)
# used by the onboarding form to populate the "input variable" dropdown
# on each severity-threshold row.
#
# Sources:
#   1. Every primary/secondary metric_key on any non-deleted SLA in
#      contract.sla_definitions (this is the "what we've actually used
#      so far" set — grows as new SLAs onboard).
#   2. contract.data_field_master rows (the curated catalog — extend
#      via PATCH /data-fields/{name} or direct SQL).
#
# Returns a deduped list. The FE shows it as a dropdown plus a free-
# text input for "+ new variable" so unfamiliar measurements can be
# typed directly; they get added to source #1 automatically the next
# time the SLA is onboarded.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# /sla-rfp-fields — catalog of every RFP table row type
#
# Drives the dynamic-row SLA-onboarding page. Each entry describes ONE
# row that can appear in the form (Definition of SLA, Scope of SLA,
# SLA Calculation, Severity threshold table, Linear LD escalation, …)
# plus how the FE should render the value column.
#
# Why hardcoded? The RFP §5.28 row set is contractual — adding a new
# row means code-path support for its data anyway. Promotion to a
# master table can wait for the second contract template.
# ---------------------------------------------------------------------------

_SLA_RFP_FIELDS: List[Dict[str, Any]] = [
    {"key": "sla_ref", "label": "SLA Number", "section": "Identification",
     "input_type": "text", "required": True, "placeholder": "PMU-SLA001",
     "help": "RFP table header. e.g. PMU-SLA001."},
    {"key": "title", "label": "Title", "section": "Identification",
     "input_type": "text", "required": True, "placeholder": "Non-submission of deliverable"},
    {"key": "project_id", "label": "Project (PMC contract)", "section": "Identification",
     "input_type": "project_picker", "required": True,
     "help": "The PMC contract this SLA belongs to."},
    {"key": "category_code", "label": "SLA Category", "section": "Identification",
     "input_type": "category_picker", "required": True,
     "help": "Category picks the calculation engine."},
    {"key": "description", "label": "Definition of SLA", "section": "Definition",
     "input_type": "textarea",
     "help": "RFP \"Definition of SLA\" row."},
    {"key": "scope_text", "label": "Scope of SLA", "section": "Definition",
     "input_type": "textarea",
     "help": "RFP \"Scope of SLA\" row."},
    {"key": "data_source", "label": "Source of Data / Tool used for SLA monitoring",
     "section": "Source & Calculation", "input_type": "text",
     "placeholder": "Manual — UIDAI biometric attendance system"},
    {"key": "calculation_method", "label": "SLA Calculation", "section": "Source & Calculation",
     "input_type": "textarea"},
    {"key": "reports_submitted_to", "label": "Reports submitted to", "section": "Source & Calculation",
     "input_type": "text", "placeholder": "Technology Management Division, UIDAI HO"},
    {"key": "measurement_interval", "label": "Measurement Interval", "section": "Cadence",
     "input_type": "select",
     "options": ["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "ONE_TIME"], "default": "MONTHLY"},
    {"key": "reporting_interval", "label": "Reporting Interval", "section": "Cadence",
     "input_type": "select",
     "options": ["WEEKLY", "MONTHLY", "QUARTERLY", "ANNUAL"], "default": "QUARTERLY"},
    {"key": "ld_computation_base", "label": "Applied On", "section": "Cadence",
     "input_type": "select",
     "options": [
         {"value": "QUARTERLY_PAYMENT", "label": "Planned Quarterly Payment (PQP)"},
         {"value": "ANNUAL_PAYMENT", "label": "Annual Contract Value"},
         {"value": "FIXED_AMOUNT", "label": "Deliverable Cost (set per mapping)"},
     ], "default": "QUARTERLY_PAYMENT"},
    {"key": "effective_from", "label": "Active From", "section": "Cadence",
     "input_type": "date", "required": True, "default": "2024-04-01"},
    {"key": "effective_until", "label": "Active Until", "section": "Cadence",
     "input_type": "date",
     "help": "Leave blank for \"no end date\"."},
    {"key": "measurement", "label": "What is measured (primary)", "section": "Measurement",
     "input_type": "measurement_set", "required": True},
    {"key": "secondary_measurement", "label": "What is measured (secondary)", "section": "Measurement",
     "input_type": "measurement_set",
     "help": "Compound SLAs only (e.g. PMU-SLA007 with BD AND hours)."},
    {"key": "target_rows", "label": "Target / Applied Severity level",
     "section": "Target", "input_type": "severity_table",
     "help": "Copy the RFP \"Target\" sub-table — one row per severity level."},
    {"key": "linear_escalation", "label": "Linear LD escalation",
     "section": "Target", "input_type": "linear_form",
     "help": "For SLAs whose RFP states LD as a per-unit rate (\"0.5% per week\")."},
    {"key": "placeholders", "label": "Mapping inputs (filled at attach time)",
     "section": "Mapping", "input_type": "placeholder_table",
     "help": "Per-attachment variables: deliverable cost, T₀ date, K date, etc."},
    {"key": "attachments", "label": "Image attachments", "section": "Evidence",
     "input_type": "file_picker"},

    # ── Additional rows from the cross-RFP analysis (PMU / MSAP / BSP / MSIP).
    # Present in some but not all contracts, so they're offered as optional
    # dynamic rows rather than promoted to the mandatory static section.
    {"key": "data_capture_process",
     "label": "Process to capture raw data for SLA calculations",
     "section": "Source & Calculation", "input_type": "textarea",
     "help": "Appears in all 4 RFPs (PMU, MSAP, BSP, MSIP). Describes how the "
             "raw measurement is captured before the SLA calculation runs."},
    {"key": "monitoring_tool",
     "label": "Tool used for SLA monitoring",
     "section": "Source & Calculation", "input_type": "text",
     "help": "Appears in MSAP, MSIP. e.g. 'EMS tools', 'biometric attendance system', 'N/A'."},
    {"key": "ld_calculation",
     "label": "LD calculation (separate from SLA calculation)",
     "section": "Source & Calculation", "input_type": "textarea",
     "help": "MSAP separates the SLA-value calculation from the LD-value calculation."},
    {"key": "assumptions",
     "label": "Assumptions / Remarks",
     "section": "Source & Calculation", "input_type": "textarea",
     "help": "MSAP 'Assumptions' / 'Remarks' row — definitions of T, planned dates, etc."},
    {"key": "metric_type",
     "label": "Metric Type",
     "section": "Identification", "input_type": "text",
     "help": "BSP per-metric category — 'Accuracy', 'Throughput', 'Availability'."},
]


@router.get(
    "/sla-rfp-fields",
    summary="Catalog of every RFP row type the dynamic onboarding form can render",
    description=(
        "Returns the master list of fields that the SLA-Onboarding page "
        "renders as picker options on each row. Each entry tells the FE: "
        "what label to show in the row-type dropdown, what input widget "
        "to render in the value cell (text / textarea / date / select / "
        "project_picker / category_picker / measurement_set / "
        "severity_table / linear_form / placeholder_table / file_picker), "
        "and where to surface helper text. The FE doesn't hardcode any "
        "RFP field — adding a new row type means adding an entry here."
    ),
)
def list_sla_rfp_fields():
    elements = [
        hal_resource(
            "SlaRfpField", field,
            self_link=f"/api/v3/sla-rfp-fields/{field['key']}",
        )
        for field in _SLA_RFP_FIELDS
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


@router.get(
    "/sla-input-variables",
    summary="Catalog of input variables (metric_keys) for the SLA onboarding form",
    description=(
        "Returns every distinct measurement key seen across the SLA "
        "catalogue plus every active data-field in the masters table. "
        "The FE renders this as the per-row 'input variable' dropdown "
        "on the SLA-onboarding modal's Target sub-table. New variables "
        "appear automatically as soon as the first SLA using them is "
        "onboarded — no admin step needed."
    ),
)
def list_sla_input_variables(
    ctrl: MasterController = Depends(get_master_controller),
):
    from sqlalchemy import select
    from app.models.sla_definition import SlaDefinition
    from app.models.sla_metric import SlaMetric

    seen: Dict[str, Dict[str, Any]] = {}

    # Source 1 — every metric on every live SLA. Joined to get the
    # SLA's category + sla_ref so the FE can show "Used by: PMU-SLA005,
    # PMU-SLA007" next to each entry.
    metric_rows = ctrl.db.execute(
        select(
            SlaMetric.metric_key, SlaMetric.display_name, SlaMetric.unit,
            SlaMetric.is_primary, SlaDefinition.sla_ref, SlaDefinition.category,
        )
        .join(SlaDefinition, SlaMetric.sla_id == SlaDefinition.id)
        .where(SlaDefinition.status != "DELETED")
        .order_by(SlaMetric.metric_key)
    ).all()
    for mkey, display, unit, primary, sla_ref, category in metric_rows:
        if not mkey:
            continue
        entry = seen.setdefault(mkey, {
            "key": mkey,
            "label": display or mkey,
            "unit": unit or None,
            "source": "sla",
            "used_by": [],
            "categories": [],
        })
        if sla_ref and sla_ref not in entry["used_by"]:
            entry["used_by"].append(sla_ref)
        if category and category not in entry["categories"]:
            entry["categories"].append(category)

    # Source 2 — curated master entries (extends the catalog with
    # variables we haven't onboarded an SLA for yet). The master rows
    # carry the structural metadata (direction, description, data_type,
    # applicable_to) that the FE picker surfaces as a tooltip / hint.
    for df in ctrl.list_data_fields():
        if df.field_name in seen:
            # Live SLA already covers this key — enrich with master metadata.
            seen[df.field_name].update({
                "data_type":   df.data_type,
                "direction":   getattr(df, "direction", None),
                "description": getattr(df, "description", None),
                "applicable_to": df.applicable_to or [],
                "example_value": df.example_value,
            })
            continue
        seen[df.field_name] = {
            "key":           df.field_name,
            "label":         df.display_name or df.field_name,
            "unit":          df.unit or None,
            "data_type":     df.data_type,
            "direction":     getattr(df, "direction", None),
            "description":   getattr(df, "description", None),
            "applicable_to": df.applicable_to or [],
            "example_value": df.example_value,
            "source":        "data_field",
            "used_by":       [],
            "categories":    [],
        }

    # Collapse entries that share the same visible LABEL under different machine
    # KEYS. `seen` is deduped by key (metric_key / field_name), but the FE renders
    # the `label` (display_name) — so the same concept present under a free-text SLA
    # slug AND a curated data_field key (e.g. "weeks_delayed" + "deliverable_delay_weeks",
    # both labelled "Weeks delayed") shows as duplicate rows. Merge same-label entries
    # into one, preferring the curated data_field key as canonical; but KEEP them
    # separate when unit or direction genuinely differ (distinct measurements that
    # merely share a label).
    def _norm_label(lbl: str) -> str:
        return " ".join((lbl or "").split()).lower()

    by_label: Dict[str, list] = {}
    for entry in seen.values():
        by_label.setdefault(_norm_label(entry["label"]), []).append(entry)

    deduped: list = []
    for group in by_label.values():
        if len(group) == 1:
            deduped.append(group[0])
            continue
        units = {g.get("unit") for g in group if g.get("unit")}
        directions = {g.get("direction") for g in group if g.get("direction")}
        if len(units) > 1 or len(directions) > 1:
            deduped.extend(group)  # genuinely different measurements — keep both
            continue
        # Canonical = the curated data_field entry if present, else the first.
        group.sort(key=lambda g: 0 if g.get("source") == "data_field" else 1)
        canon = group[0]
        for other in group[1:]:
            for ref in other.get("used_by", []):
                if ref not in canon["used_by"]:
                    canon["used_by"].append(ref)
            for cat in other.get("categories", []):
                if cat not in canon["categories"]:
                    canon["categories"].append(cat)
            for meta in ("data_type", "direction", "description",
                         "applicable_to", "example_value", "unit"):
                if not canon.get(meta) and other.get(meta):
                    canon[meta] = other[meta]
        deduped.append(canon)

    items = sorted(deduped, key=lambda x: x["label"].lower())
    elements = [
        hal_resource(
            "SlaInputVariable", item,
            self_link=f"/api/v3/sla-input-variables/{item['key']}",
        )
        for item in items
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


# ---------------------------------------------------------------------------
# Formula library — SLA formula catalogue (read-only, seeded at migration)
# ---------------------------------------------------------------------------

@router.get(
    "/formula-library",
    summary="List all SLA formula types with parameter schemas",
    responses=with_examples(
        (200, "All formula types this evaluator can dispatch to.", RESP_FORMULA_LIBRARY),
    ),
)
def list_formula_library(ctrl: MasterController = Depends(get_master_controller)):
    items = ctrl.list_formula_library()
    elements = [
        hal_resource(
            "FormulaLibrary", r.model_dump(),
            self_link=f"/api/v3/formula-library/{r.formula_type}",
        )
        for r in items
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


# ---------------------------------------------------------------------------
# Data fields — observable variable catalog (SLA condition builder)
# ---------------------------------------------------------------------------

@router.post(
    "/data-fields",
    status_code=201,
    summary="Add a new observable data field",
    responses=with_examples(
        (201, "Data field created.", RESP_DATA_FIELD_DETAIL),
        (422, "Schema validation failed.", RESP_VALIDATION_FAIL),
    ),
)
def create_data_field(
    payload: DataFieldCreateRequest,
    ctrl: MasterController = Depends(get_master_controller),
):
    result = ctrl.create_data_field(payload)
    return api_response(
        data=hal_resource(
            "DataField", result.model_dump(),
            self_link=f"/api/v3/data-fields/{result.field_name}",
        ),
        message=f"Data field '{result.field_name}' created",
        status=201,
    )


@router.get(
    "/data-fields",
    summary="List observable data fields for the SLA condition builder",
    responses=with_examples(
        (200, "Active data fields, optionally filtered by contract_type.",
         RESP_DATA_FIELD_LIST),
    ),
)
def list_data_fields(
    contract_type: Optional[str] = Query(
        None,
        description="Filter by contract type code (e.g. MSAP). "
                    "NULL-applicable_to fields are always included.",
    ),
    ctrl: MasterController = Depends(get_master_controller),
):
    items = ctrl.list_data_fields(contract_type=contract_type)
    elements = [
        hal_resource(
            "DataField", r.model_dump(),
            self_link=f"/api/v3/data-fields/{r.field_name}",
        )
        for r in items
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


@router.patch(
    "/data-fields/{field_name}",
    summary="Update a data field",
    responses=with_examples(
        (200, "Data field updated.", RESP_DATA_FIELD_DETAIL),
        (404, "Data field not found.", RESP_NOT_FOUND),
    ),
)
def update_data_field(
    field_name: str,
    payload: DataFieldUpdateRequest,
    ctrl: MasterController = Depends(get_master_controller),
):
    result = ctrl.update_data_field(field_name, payload)
    return api_response(
        data=hal_resource(
            "DataField", result.model_dump(),
            self_link=f"/api/v3/data-fields/{result.field_name}",
        ),
        message=f"Data field '{field_name}' updated",
        status=200,
    )


@router.delete(
    "/data-fields/{field_name}",
    summary="Soft-delete a data field (sets is_active=false)",
    responses=with_examples(
        (200, "Data field deactivated.", RESP_DATA_FIELD_DETAIL),
        (404, "Data field not found.", RESP_NOT_FOUND),
    ),
)
def delete_data_field(
    field_name: str,
    ctrl: MasterController = Depends(get_master_controller),
):
    result = ctrl.delete_data_field(field_name)
    return api_response(
        data=hal_resource(
            "DataField", result.model_dump(),
            self_link=f"/api/v3/data-fields/{result.field_name}",
        ),
        message=f"Data field '{field_name}' deactivated",
        status=200,
    )


# ---------------------------------------------------------------------------
# Severity master — per-project (auto-seeded on project_ld_config creation)
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/severity-master",
    status_code=201,
    summary="Set severity levels for a project (replaces existing)",
    responses=with_examples(
        (201, "Levels saved and returned.", RESP_SEVERITY_MASTER),
        (422, "Schema validation failed.", RESP_VALIDATION_FAIL),
    ),
)
def set_severity_levels(
    project_id: str,
    payload: SeverityMasterSetRequest,
    ctrl: MasterController = Depends(get_master_controller),
):
    """Replace all severity levels for this project. Use to customise points/labels
    away from the MSAP defaults that are auto-seeded when the LD config is created."""
    items = ctrl.set_severity_levels(project_id, payload)
    base = f"/api/v3/projects/{project_id}/severity-master"
    elements = [
        hal_resource("SeverityLevel", r.model_dump(), self_link=f"{base}/{r.level}")
        for r in items
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        message=f"{len(items)} severity level(s) set for project '{project_id}'",
        status=201,
    )


@router.get(
    "/projects/{project_id}/severity-master",
    summary="List severity levels (0-4) for a project",
    responses=with_examples(
        (200, "Project's severity_master rows.", RESP_SEVERITY_MASTER),
    ),
)
def list_severity_levels(
    project_id: str,
    ctrl: MasterController = Depends(get_master_controller),
):
    items = ctrl.list_severity_levels(project_id)
    base = f"/api/v3/projects/{project_id}/severity-master"
    elements = [
        hal_resource("SeverityLevel", r.model_dump(), self_link=f"{base}/{r.level}")
        for r in items
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


@router.patch(
    "/projects/{project_id}/severity-master/{level}",
    summary="Upsert a severity level — updates the row if it exists, otherwise creates it",
    description=(
        "Levels are open-ended (the RFP defines 0-4 but you can extend higher). "
        "If the row already exists, supply only the fields you want to change. "
        "If the row doesn't exist yet, supply BOTH `points` and `label` to "
        "create it — the endpoint refuses to persist a half-populated row."
    ),
    responses=with_examples(
        (200, "Severity level upserted.", RESP_SEVERITY_MASTER),
        (422, "Schema validation failed.", RESP_VALIDATION_FAIL),
    ),
)
def update_severity_level(
    project_id: str,
    level: int,
    payload: SeverityLevelUpdateRequest,
    ctrl: MasterController = Depends(get_master_controller),
):
    result = ctrl.update_severity_level(project_id, level, payload)
    return api_response(
        data=hal_resource(
            "SeverityLevel",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/severity-master/{level}",
        ),
        message=f"Severity level {level} saved",
        status=200,
    )


# ---------------------------------------------------------------------------
# Project LD bands — per-project points -> LD% chart (Phase B companion to
# severity_master). Symmetric API surface. Together they let a project fully
# replace the RFP defaults used by the evaluator.
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/ld-bands",
    status_code=201,
    summary="Set LD bands for a project (replaces existing)",
    responses=with_examples(
        (201, "Bands saved.", RESP_LD_BANDS),
        (422, "Schema validation failed.", RESP_VALIDATION_FAIL),
    ),
)
def set_ld_bands(
    project_id: str,
    payload: LdBandSetRequest,
    ctrl: MasterController = Depends(get_master_controller),
):
    """Replace every points->LD% band for this project. Use to customise the
    LD curve away from the MSAP RFP defaults seeded by seed-master-defaults."""
    items = ctrl.set_ld_bands(project_id, payload)
    base = f"/api/v3/projects/{project_id}/ld-bands"
    elements = [
        hal_resource("LdBand", r.model_dump(), self_link=f"{base}/{r.id}")
        for r in items
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        message=f"{len(items)} LD band(s) set for project '{project_id}'",
        status=201,
    )


@router.get(
    "/projects/{project_id}/ld-bands",
    summary="List LD bands for a project (sorted by points_threshold)",
    responses=with_examples(
        (200, "Project's LD band table, ascending by threshold.", RESP_LD_BANDS),
    ),
)
def list_ld_bands(
    project_id: str,
    ctrl: MasterController = Depends(get_master_controller),
):
    items = ctrl.list_ld_bands(project_id)
    base = f"/api/v3/projects/{project_id}/ld-bands"
    elements = [
        hal_resource("LdBand", r.model_dump(), self_link=f"{base}/{r.id}")
        for r in items
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


@router.patch(
    "/projects/{project_id}/ld-bands/{band_id}",
    summary="Update points_threshold, ld_percent or label for a single LD band",
    responses=with_examples(
        (200, "Band updated.", RESP_LD_BANDS),
        (404, "Band not found.", RESP_NOT_FOUND),
        (422, "Schema validation failed.", RESP_VALIDATION_FAIL),
    ),
)
def update_ld_band(
    project_id: str,
    band_id: str,
    payload: LdBandUpdateRequest,
    ctrl: MasterController = Depends(get_master_controller),
):
    result = ctrl.update_ld_band(project_id, band_id, payload)
    return api_response(
        data=hal_resource(
            "LdBand",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/ld-bands/{band_id}",
        ),
        message=f"LD band '{band_id}' updated",
        status=200,
    )


# ---------------------------------------------------------------------------
# Combined bootstrap — seeds severity_master + project_ld_bands at once with
# the RFP defaults. Idempotent: skips whichever table is already populated.
# Frontend calls this once when a project is first opened in the contract UI.
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/seed-master-defaults",
    status_code=201,
    summary="Seed both severity_master and ld_bands with RFP defaults (idempotent)",
    responses=with_examples(
        (201, "Seed summary across both tables.", RESP_SEED_DEFAULTS),
    ),
)
def seed_master_defaults(
    project_id: str,
    ctrl: MasterController = Depends(get_master_controller),
):
    summary = ctrl.seed_master_defaults(project_id)
    return api_response(
        data=hal_resource(
            "MasterSeed",
            {"project_id": project_id, **summary},
            self_link=f"/api/v3/projects/{project_id}/seed-master-defaults",
        ),
        message=(
            f"Seeded {summary['severity_levels']} severity levels and "
            f"{summary['ld_bands']} LD bands for project '{project_id}'"
        ),
        status=201,
    )
