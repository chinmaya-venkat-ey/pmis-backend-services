"""Master reference data routes.

Endpoints:
  GET   /api/v3/contract-types                                   list contract types
  GET   /api/v3/data-fields                                      list SLA data fields (with optional filter)
  GET   /api/v3/projects/{project_id}/severity-master            list severity levels for a project
  PATCH /api/v3/projects/{project_id}/severity-master/{level}    update points or label for a level
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
    SeverityLevelUpdateRequest,
    SeverityMasterSetRequest,
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
    summary="Update points or label for a severity level (0-4)",
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
        message=f"Severity level {level} updated",
        status=200,
    )
