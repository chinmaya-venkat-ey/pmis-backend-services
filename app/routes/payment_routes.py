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

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.controllers.payment_page_controller import PaymentPageController
from app.controllers.project_cost_item_controller import ProjectCostItemController
from app.controllers.project_payment_term_controller import ProjectPaymentTermController
from app.core.permissions import PAYMENT_READ, PROJECTS_UPDATE_FINANCE
from app.core.rbac import require_authenticated, require_permission, require_project_permission
from app.db import get_db
from app.dependencies import (
    get_caller_is_admin,
    get_optional_current_user_id,
    get_payment_page_controller,
    get_project_cost_item_controller,
    get_project_payment_term_controller,
)
from app.schemas.payment import (
    CarryForwardUpdateRequest,
    OneTimeUpdateRequest,
    CcnCapUpdateRequest,
    CostItemCreateRequest,
    CostItemResponse,
    CostItemUpdateRequest,
    CycleCountResponse,
    CycleFrequency,
    PaymentPageResponse,
    PaymentTermActivitiesUpdateRequest,
    PaymentTermResponse,
    PaymentTermUpdateRequest,
    PhaseFrequencyUpdateRequest,
    PhaseSequenceUpdateRequest,
    ProjectFrequencyUpdateRequest,
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
    "/{project_uuid}/cost-items/available-milestones",
    summary="Milestones still available to add to a cost row (excludes ones already bound)",
    description=(
        "Returns the project's live milestones that are NOT yet bound to any "
        "other live cost row — i.e. the set the milestone picker should offer "
        "when adding a cost row. When editing an existing cost row, pass "
        "``excludeCostItemId`` so that row's own milestones stay selectable."
    ),
    dependencies=[Depends(require_project_permission(PAYMENT_READ))],
)
def available_cost_milestones(
    project_uuid: str,
    controller: Annotated[ProjectCostItemController, Depends(get_project_cost_item_controller)],
    exclude_cost_item_id: Annotated[Optional[str], Query(alias="excludeCostItemId")] = None,
):
    return controller.available_milestones(
        project_uuid, exclude_cost_item_id=exclude_cost_item_id,
    )


@cost_item_project_scoped_router.get(
    "/{project_uuid}/cost-items",
    summary="List a project's cost items",
    dependencies=[Depends(require_project_permission(PAYMENT_READ))],
)
def list_cost_items(
    project_uuid: str,
    controller: Annotated[ProjectCostItemController, Depends(get_project_cost_item_controller)],
    offset: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[Optional[int], Query(ge=1, alias="pageSize")] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
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
    dependencies=[Depends(require_permission(PAYMENT_READ))],
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
    dependencies=[Depends(require_project_permission(PAYMENT_READ))],
)
def list_payment_terms(
    project_uuid: str,
    controller: Annotated[ProjectPaymentTermController, Depends(get_project_payment_term_controller)],
    offset: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[Optional[int], Query(ge=1, alias="pageSize")] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
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
    dependencies=[Depends(require_permission(PAYMENT_READ))],
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


@payment_term_router.patch(
    "/{term_id}/activities",
    response_model=PaymentTermResponse,
    summary="Set the per-activity split of a partial-payment milestone's term",
    description=(
        "Distributes the milestone term's percent across its activities. Only "
        "valid for a partial-payment milestone; the allocations must sum to the "
        "term's percentOfPayment (empty list clears the split). Returns the "
        "recomputed payment term."
    ),
    dependencies=[Depends(require_permission(PROJECTS_UPDATE_FINANCE))],
)
def set_payment_term_activities(
    term_id: str,
    payload: PaymentTermActivitiesUpdateRequest,
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    allocations = [
        {"activity_id": a.activity_id, "percent_of_payment": a.percent_of_payment}
        for a in payload.activities
    ]
    return controller.set_payment_term_activities(
        term_id, allocations, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


# ============================================================ aggregated page + ccn
payment_page_router = APIRouter(prefix="/projects", tags=["payment-page"])


@payment_page_router.get(
    "/{project_uuid}/payment-page",
    response_model=PaymentPageResponse,
    summary="Full payment page (cost items + totals + phases + qrg + ccn) — read-only",
    dependencies=[Depends(require_project_permission(PAYMENT_READ))],
)
def get_payment_page(
    project_uuid: str,
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
):
    return controller.get_page(project_uuid)


@payment_page_router.get(
    "/{project_uuid}/payment-page/sla-ld",
    summary="Per-milestone SLA compliance + liquidated-damages overlay for the "
            "cost page (scheduled → LD deduction → net payable).",
    dependencies=[Depends(require_project_permission(PAYMENT_READ))],
)
def get_payment_page_sla_ld(
    project_uuid: str,
    db: Annotated[Session, Depends(get_db)],
):
    from app.services.sla_ld_overlay_service import SlaLdOverlayService
    return SlaLdOverlayService(db).build(project_uuid)


@payment_page_router.get(
    "/{project_uuid}/payment-page/validate",
    summary="Run the finance-page validation checks (admin only). Returns "
            "{checks: [{id, label, pass, reason}], allPass}.",
    dependencies=[Depends(require_project_permission(PAYMENT_READ))],
)
def validate_payment_page(
    project_uuid: str,
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
):
    return controller.validate(project_uuid)


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
        additional_cost_type=payload.additional_cost_type,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@payment_page_router.put(
    "/{project_uuid}/phases/{phase}/carry-forward",
    response_model=PaymentPageResponse,
    summary="Configure carry-forward on a phase (full leftover; returns the recomputed page)",
    description=(
        "Enable/disable carrying a phase's ENTIRE leftover forward, distributed "
        "per the master carry-forward methodCode: '*_evenly' (equal split across "
        "subsequent phases / milestones), '*_custom' (explicit per-recipient "
        "allocations that must fully allocate the leftover; provide allocationMode "
        "+ allocations), or 'time_*' (split across subsequent phases weighted by "
        "each phase's payment-cycle count). Rejected when there are no eligible "
        "subsequent recipients, a custom set does not fully allocate, or a "
        "time method has no payment cycles to weight by."
    ),
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_FINANCE))],
)
def set_phase_carry_forward(
    project_uuid: str,
    payload: CarryForwardUpdateRequest,
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
    phase: Annotated[str, Path(min_length=1, max_length=64)],
):
    return controller.set_carry_forward(
        project_uuid, phase,
        enabled=payload.enabled, method_code=payload.method_code,
        allocation_mode=payload.allocation_mode,
        allocations=([a.model_dump() for a in payload.allocations]
                     if payload.allocations else None),
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@payment_page_router.put(
    "/{project_uuid}/phases/{phase}/one-time",
    response_model=PaymentPageResponse,
    summary="Opt a phase into a share of the project one-time pool (returns the recomputed page)",
    description=(
        "Enable/disable a phase carrying part of the project one-time cost. On "
        "enable, provide mode ('percent' of the one-time total | 'amount' in ₹) "
        "and value. The chronologically LAST phase auto-absorbs the remainder "
        "and cannot be set explicitly; the non-last shares may not exceed the pool."
    ),
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_FINANCE))],
)
def set_phase_one_time(
    project_uuid: str,
    payload: OneTimeUpdateRequest,
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
    phase: Annotated[str, Path(min_length=1, max_length=64)],
):
    return controller.set_one_time_allocation(
        project_uuid, phase,
        enabled=payload.enabled, mode=payload.mode, value=payload.value,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@payment_page_router.put(
    "/{project_uuid}/phases/{phase}/sequence",
    response_model=PaymentPageResponse,
    summary="DEPRECATED — phase order is now derived from milestone dates; this no longer affects ordering",
    deprecated=True,
    description=(
        "Deprecated. Phase order is derived purely from each phase's milestone "
        "date span (earliest start first, shorter span breaks ties). This "
        "endpoint still writes the legacy ``sequence`` column but it no longer "
        "influences the displayed order or carry-forward 'subsequent' scoping."
    ),
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_FINANCE))],
)
def set_phase_sequence(
    project_uuid: str,
    payload: PhaseSequenceUpdateRequest,
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
    phase: Annotated[str, Path(min_length=1, max_length=64)],
):
    return controller.set_phase_sequence(
        project_uuid, phase, payload.sequence,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@payment_page_router.put(
    "/{project_uuid}/frequency",
    response_model=PaymentPageResponse,
    summary="Set the ONE billing frequency for the whole project (drives all cycle counts)",
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_FINANCE))],
)
def set_project_frequency(
    project_uuid: str,
    payload: ProjectFrequencyUpdateRequest,
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.set_project_frequency(
        project_uuid, payload.frequency_code,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@payment_page_router.put(
    "/{project_uuid}/phases/{phase}/frequency",
    response_model=PaymentPageResponse,
    summary="[back-compat] Sets the PROJECT-level frequency (phase is ignored; returns the page)",
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_FINANCE))],
)
def set_phase_frequency(
    project_uuid: str,
    payload: PhaseFrequencyUpdateRequest,
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
    phase: Annotated[str, Path(min_length=1, max_length=64)],
):
    return controller.set_phase_frequency(
        project_uuid, phase, payload.frequency_code,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


# ========================================================= cycle count (utility)
# Stateless date-math helper — no project context, no data exposure. Any
# authenticated caller may use it (lock down to a finance role later if needed).
cycle_count_router = APIRouter(prefix="/payment", tags=["payment-page"])


@cycle_count_router.get(
    "/cycle-count",
    response_model=CycleCountResponse,
    summary="Number of calendar-aligned billing cycles between two dates",
    dependencies=[Depends(require_authenticated())],
)
def get_cycle_count(
    controller: Annotated[PaymentPageController, Depends(get_payment_page_controller)],
    start_date: Annotated[datetime, Query(alias="startDate")],
    end_date: Annotated[datetime, Query(alias="endDate")],
    frequency: Annotated[CycleFrequency, Query()],
):
    return controller.cycle_count(start_date, end_date, frequency.value)
