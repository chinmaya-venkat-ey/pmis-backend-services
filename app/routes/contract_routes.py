"""Contract and Phase CRUD routes — Phase 2.

Endpoints:
  POST   /api/v3/contracts                                  create contract
  GET    /api/v3/contracts                                  list contracts
  GET    /api/v3/contracts/{contract_id}                    get contract
  PATCH  /api/v3/contracts/{contract_id}                    update contract

  POST   /api/v3/contracts/{contract_id}/phases             create phase
  GET    /api/v3/contracts/{contract_id}/phases             list phases
  GET    /api/v3/contracts/{contract_id}/phases/{phase_id}  get phase
  PATCH  /api/v3/contracts/{contract_id}/phases/{phase_id}  update phase
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.controllers.contract_controller import ContractController
from app.core.response import api_response, hal_collection, hal_resource
from app.db import get_db
from app.dependencies import get_contract_controller, get_current_user_id
from app.schemas.contract import (
    ContractCreateRequest,
    ContractUpdateRequest,
    PhaseCreateRequest,
    PhaseUpdateRequest,
)

router = APIRouter(tags=["Contracts"])


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

@router.post("/contracts", status_code=201, summary="Create contract")
def create_contract(
    payload: ContractCreateRequest,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: ContractController = Depends(get_contract_controller),
):
    result = ctrl.create(payload, caller_user_id=caller_user_id)
    return api_response(
        data=hal_resource(
            "Contract",
            result.model_dump(),
            self_link=f"/api/v3/contracts/{result.id}",
        ),
        message="Contract created successfully",
        status=201,
    )


@router.get("/contracts", summary="List contracts")
def list_contracts(
    offset: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    vendor_name: Optional[str] = Query(None),
    ctrl: ContractController = Depends(get_contract_controller),
):
    result = ctrl.list_(
        offset=offset,
        page_size=page_size,
        status=status,
        vendor_name=vendor_name,
    )
    elements = [
        hal_resource("Contract", item.model_dump(), self_link=f"/api/v3/contracts/{item.id}")
        for item in result["items"]
    ]
    return api_response(
        data=hal_collection(
            elements,
            total=result["total"],
            offset=result["offset"],
            page_size=result["page_size"],
            base_path="/api/v3/contracts",
        ),
        status=200,
    )


@router.get("/contracts/{contract_id}", summary="Get contract")
def get_contract(
    contract_id: str,
    ctrl: ContractController = Depends(get_contract_controller),
):
    result = ctrl.get(contract_id)
    return api_response(
        data=hal_resource(
            "Contract",
            result.model_dump(),
            self_link=f"/api/v3/contracts/{result.id}",
        ),
        status=200,
    )


@router.patch("/contracts/{contract_id}", summary="Update contract")
def update_contract(
    contract_id: str,
    payload: ContractUpdateRequest,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: ContractController = Depends(get_contract_controller),
):
    result = ctrl.update(contract_id, payload, caller_user_id=caller_user_id)
    return api_response(
        data=hal_resource(
            "Contract",
            result.model_dump(),
            self_link=f"/api/v3/contracts/{result.id}",
        ),
        message="Contract updated successfully",
        status=200,
    )


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

@router.post("/contracts/{contract_id}/phases", status_code=201, summary="Create phase")
def create_phase(
    contract_id: str,
    payload: PhaseCreateRequest,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: ContractController = Depends(get_contract_controller),
):
    result = ctrl.create_phase(contract_id, payload)
    return api_response(
        data=hal_resource(
            "ContractPhase",
            result.model_dump(),
            self_link=f"/api/v3/contracts/{contract_id}/phases/{result.id}",
        ),
        message="Phase created successfully",
        status=201,
    )


@router.get("/contracts/{contract_id}/phases", summary="List phases")
def list_phases(
    contract_id: str,
    active_only: bool = Query(False),
    ctrl: ContractController = Depends(get_contract_controller),
):
    phases = ctrl.list_phases(contract_id, active_only=active_only)
    elements = [
        hal_resource(
            "ContractPhase",
            p.model_dump(),
            self_link=f"/api/v3/contracts/{contract_id}/phases/{p.id}",
        )
        for p in phases
    ]
    return api_response(
        data=hal_collection(
            elements,
            total=len(elements),
            page_size=len(elements) or 1,
        ),
        status=200,
    )


@router.get(
    "/contracts/{contract_id}/phases/{phase_id}", summary="Get phase"
)
def get_phase(
    contract_id: str,
    phase_id: str,
    ctrl: ContractController = Depends(get_contract_controller),
):
    result = ctrl.get_phase(contract_id, phase_id)
    return api_response(
        data=hal_resource(
            "ContractPhase",
            result.model_dump(),
            self_link=f"/api/v3/contracts/{contract_id}/phases/{result.id}",
        ),
        status=200,
    )


@router.patch(
    "/contracts/{contract_id}/phases/{phase_id}", summary="Update phase"
)
def update_phase(
    contract_id: str,
    phase_id: str,
    payload: PhaseUpdateRequest,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: ContractController = Depends(get_contract_controller),
):
    result = ctrl.update_phase(contract_id, phase_id, payload)
    return api_response(
        data=hal_resource(
            "ContractPhase",
            result.model_dump(),
            self_link=f"/api/v3/contracts/{contract_id}/phases/{result.id}",
        ),
        message="Phase updated successfully",
        status=200,
    )
