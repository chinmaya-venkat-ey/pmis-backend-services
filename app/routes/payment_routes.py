"""Payment-module routes — Project-Finance screen (mounted under /api/v3).

Routers (project-scoped create/list + id-scoped CRUD, mirroring milestones):
  - cost_item_project_scoped_router : POST/GET /projects/{uuid}/cost-items
  - cost_item_router                : GET/PATCH/DELETE /cost-items/{id} + restore
  - payment_term_project_scoped_router : POST/GET /projects/{uuid}/payment-terms
  - payment_term_router             : GET/PATCH/DELETE /payment-terms/{id} + restore
  - payment_page_router             : GET /projects/{uuid}/payment-page,
                                      PATCH /projects/{uuid}/ccn-cap,
                                      PUT /projects/{uuid}/phases/{phase}/qrg

RBAC:
  - Reads → ``projects:read`` (project-scoped where a project_uuid is in the
    path; flat for id-scoped routes the project resolver can't walk).
  - Writes → ``projects:update:finance`` (same code v1 finance uses). The
    publish-lock + admin-after-publish bypass is applied in the service layer
    via ``request.state.is_admin``.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Path, Query, status

from app.controllers.payment_page_controller import PaymentPageController
from app.controllers.project_cost_item_controller import ProjectCostItemController
from app.controllers.project_payment_term_controller import ProjectPaymentTermController
from app.core.permissions import PROJECTS_READ, PROJECTS_UPDATE_FINANCE
from app.core.rbac import require_permission, require_project_permission
from app.dependencies import (
    get_caller_is_admin,
    get_optional_current_user_id,
    get_payment_page_controller,
    get_project_cost_item_controller,
    get_project_payment_term_controller,
)
from app.schemas.payment import (
    CcnCapUpdateRequest,
    CostItemCreateRequest,
    CostItemResponse,
    CostItemUpdateRequest,
    PaymentPageResponse,
    PaymentTermResponse,
    PaymentTermUpdateRequest,
    QrgResponse,
    QrgUpdateRequest,
)


# ============================================================ cost items (scoped)
cost_item_project_scoped_router = APIRouter(prefix="/projects", tags=["payment-cost-items"])


@cost_item_project_scoped_router.post(
    "/{project_uuid}/cost-items",
    response_model=CostItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project cost item",
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_FINANCE))],
)
def create_cost_item(
    project_uuid: str,
    payload: CostItemCreateRequest,
    controller: Annotated[ProjectCostItemController, Depends(get_project_cost_item_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.create(
        project_uuid, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@cost_item_project_scoped_router.get(
    "/{project_uuid}/cost-items",
    summary="List a project's cost items",
    dependencies=[Depends(require_project_permission(PROJECTS_READ))],
)
def list_cost_items(
    project_uuid: str,
    controller: Annotated[ProjectCostItemController, Depends(get_project_cost_item_controller)],
    offset: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100, alias="pageSize"),
    include_deleted: bool = Query(False, alias="includeDeleted"),
):
    return controller.list_for_project(
        project_uuid, offset=offset, page_size=page_size, include_deleted=include_deleted,
    )


# ================================================================ cost items (id)
cost_item_router = APIRouter(prefix="/cost-items", tags=["payment-cost-items"])


@cost_item_router.get(
    "/{cost_item_id}",
    response_model=CostItemResponse,
    summary="Get a cost item by id",
    dependencies=[Depends(require_permission(PROJECTS_READ))],
)
def get_cost_item(
    cost_item_id: str,
    controller: Annotated[ProjectCostItemController, Depends(get_project_cost_item_controller)],
):
    return controller.get(cost_item_id)


@cost_item_router.patch(
    "/{cost_item_id}",
    response_model=CostItemResponse,
    summary="Update a cost item",
    dependencies=[Depends(require_permission(PROJECTS_UPDATE_FINANCE))],
)
def update_cost_item(
    cost_item_id: str,
    payload: CostItemUpdateRequest,
    controller: Annotated[ProjectCostItemController, Depends(get_project_cost_item_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.update(
        cost_item_id, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@cost_item_router.delete(
    "/{cost_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a cost item",
    dependencies=[Depends(require_permission(PROJECTS_UPDATE_FINANCE))],
)
def delete_cost_item(
    cost_item_id: str,
    controller: Annotated[ProjectCostItemController, Depends(get_project_cost_item_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    controller.delete(cost_item_id, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin)


@cost_item_router.post(
    "/{cost_item_id}/restore",
    response_model=CostItemResponse,
    summary="Restore a soft-deleted cost item",
    dependencies=[Depends(require_permission(PROJECTS_UPDATE_FINANCE))],
)
def restore_cost_item(
    cost_item_id: str,
    controller: Annotated[ProjectCostItemController, Depends(get_project_cost_item_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.restore(cost_item_id, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin)


# ========================================================= payment terms (scoped)
# Rows are auto-managed from the cost milestone bundles → list + get + patch
# only (no manual create / delete / restore).
payment_term_project_scoped_router = APIRouter(prefix="/projects", tags=["payment-terms"])


@payment_term_project_scoped_router.get(
    "/{project_uuid}/payment-terms",
    summary="List a project's payment terms (auto-managed from cost rows)",
    dependencies=[Depends(require_project_permission(PROJECTS_READ))],
)
def list_payment_terms(
    project_uuid: str,
    controller: Annotated[ProjectPaymentTermController, Depends(get_project_payment_term_controller)],
    offset: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100, alias="pageSize"),
    include_deleted: bool = Query(False, alias="includeDeleted"),
):
    return controller.list_for_project(
        project_uuid, offset=offset, page_size=page_size, include_deleted=include_deleted,
    )


# ============================================================= payment terms (id)
payment_term_router = APIRouter(prefix="/payment-terms", tags=["payment-terms"])


@payment_term_router.get(
    "/{term_id}",
    response_model=PaymentTermResponse,
    summary="Get a payment term by id",
    dependencies=[Depends(require_permission(PROJECTS_READ))],
)
def get_payment_term(
    term_id: str,
    controller: Annotated[ProjectPaymentTermController, Depends(get_project_payment_term_controller)],
):
    return controller.get(term_id)


@payment_term_router.patch(
    "/{term_id}",
    response_model=PaymentTermResponse,
    summary="Set a payment term's schedule (frequency + % of payment)",
    dependencies=[Depends(require_permission(PROJECTS_UPDATE_FINANCE))],
)
def update_payment_term(
    term_id: str,
    payload: PaymentTermUpdateRequest,
    controller: Annotated[ProjectPaymentTermController, Depends(get_project_payment_term_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.update(
        term_id, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


# ============================================================ aggregated page + ccn
payment_page_router = APIRouter(prefix="/projects", tags=["payment-page"])


@payment_page_router.get(
    "/{project_uuid}/payment-page",
    response_model=PaymentPageResponse,
    summary="Full payment page (cost items + totals + phases + qrg + ccn) — read-only",
    dependencies=[Depends(require_project_permission(PROJECTS_READ))],
)
def get_payment_page(
    project_uuid: str,
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
):
    return controller.get_page(project_uuid)


@payment_page_router.patch(
    "/{project_uuid}/ccn-cap",
    response_model=PaymentPageResponse,
    summary="Update the CCN cap percent (returns the recomputed page)",
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_FINANCE))],
)
def update_ccn_cap(
    project_uuid: str,
    payload: CcnCapUpdateRequest,
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.update_ccn_cap(
        project_uuid, payload.ccn_cap_percent,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@payment_page_router.put(
    "/{project_uuid}/phases/{phase}/qrg",
    response_model=QrgResponse,
    summary="Set the per-phase QRG-applied flag",
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_FINANCE))],
)
def set_phase_qrg(
    project_uuid: str,
    payload: QrgUpdateRequest,
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
    phase: int = Path(ge=0),
):
    return controller.set_qrg(
        project_uuid, phase, payload.qrg_applied,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )
