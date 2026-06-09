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

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.controllers.master_controller import MasterController
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

@router.post("/contract-types", status_code=201, summary="Create a new contract type")
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


@router.patch("/contract-types/{code}", summary="Update display name or description")
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


@router.delete("/contract-types/{code}", summary="Soft-delete a contract type (sets is_active=false)")
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


@router.get("/contract-types", summary="List all contract types")
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

@router.get("/sla-enums", summary="All allowed enum values for SLA onboarding dropdowns")
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

@router.get("/sla-categories", summary="List active SLA categories (FE picker)")
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
# Formula library — SLA formula catalogue (read-only, seeded at migration)
# ---------------------------------------------------------------------------

@router.get("/formula-library", summary="List all SLA formula types with parameter schemas")
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

@router.post("/data-fields", status_code=201, summary="Add a new observable data field")
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


@router.patch("/data-fields/{field_name}", summary="Update a data field")
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


@router.delete("/data-fields/{field_name}", summary="Soft-delete a data field (sets is_active=false)")
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
