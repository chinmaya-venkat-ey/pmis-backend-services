"""Activity Approval Inbox routes.

Two read endpoints powering the inbox + review screens that route to
Concerned Divisions and Activity Owners:

  GET /api/v3/approval-inbox
      List of activities currently sitting in the approval workflow
      where the caller is the expected reviewer.

  GET /api/v3/approval-inbox/{business_id}
      Detail for one item: activity details, organization submission
      (from Java's transition history), division status grid, owner
      decision, and a ``my_view`` block describing what the caller
      can do.

  ``business_id`` is the activity UUID (matches Java's businessId).
  This router lives at its own top-level prefix (not under
  ``/activities``) to avoid colliding with the
  ``/activities/{activity_id}`` id-scoped routes.

Both endpoints require authentication only. The service layer applies
the division-based filter (consent divisions for the concerned-division
view; owner_division for the activity-owner view) so unauthorized
callers see an empty list rather than a 403, matching how DIGIT
workflow inboxes behave.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.core.rbac import require_authenticated
from app.controllers.approval_inbox_controller import ApprovalInboxController
from app.dependencies import get_approval_inbox_controller
from app.schemas.approval_inbox import (
    InboxDetailResponse,
    InboxListResponse,
    TransitionRequest,
)


router = APIRouter(prefix="/approval-inbox", tags=["approval-inbox"])


@router.get(
    "",
    response_model=InboxListResponse,
    summary="List approval-inbox items for the caller",
    description=(
        "Returns activities currently awaiting the caller's action.\n\n"
        "Default view: rows where the caller's division is among the "
        "activity's consent divisions AND the workflow is at "
        "``PENDINGATCONCERNEDDIVISION``.\n\n"
        "Pass ``role=activity_owner`` to see rows where the caller's "
        "division is the activity's owner division AND the workflow is "
        "at ``PENDINGATOWNERDIVISION``.\n\n"
        "Admins (super_admin / admin) see all live pending rows."
    ),
    dependencies=[Depends(require_authenticated())],
)
def list_inbox(
    request: Request,
    controller: Annotated[
        ApprovalInboxController, Depends(get_approval_inbox_controller),
    ],
    role: Optional[str] = Query(
        default=None,
        description="concerned_division | activity_owner | admin",
    ),
    status: Optional[str] = Query(
        default=None,
        description="pending | approved | rejected | all (default: pending)",
    ),
    search: Optional[str] = Query(
        default=None,
        description="Free-text search across activity / project / organization",
    ),
):
    return controller.list_inbox(
        request, role=role, status=status, search=search,
    )


@router.get(
    "/{business_id}",
    response_model=InboxDetailResponse,
    summary="Get one approval-inbox item (Review screen)",
    description=(
        "Composes activity details + organization submission + workflow "
        "state for the Review screen. ``business_id`` is the activity "
        "UUID. The caller must be the activity's owner-division user OR "
        "in one of its consent divisions OR an admin."
    ),
    dependencies=[Depends(require_authenticated())],
)
def get_inbox_detail(
    request: Request,
    business_id: str,
    controller: Annotated[
        ApprovalInboxController, Depends(get_approval_inbox_controller),
    ],
):
    return controller.get_detail(request, business_id)


@router.post(
    "/{business_id}/_transition",
    response_model=InboxDetailResponse,
    summary="Move the activity through the approval workflow",
    description=(
        "Proxies a single transition (SUBMIT / APPROVE / REJECT / UPDATE) "
        "to the Activity Workflow Java service and refreshes the local "
        "tracker.\n\n"
        "Authorisation rules:\n"
        "  * SUBMIT: caller is the activity's vendor or has admin / "
        "    project_admin role.\n"
        "  * APPROVE / REJECT at PENDINGATCONCERNEDDIVISION: caller's "
        "    division must be in the activity's consent_divisions.\n"
        "  * APPROVE / REJECT at PENDINGATOWNERDIVISION: caller's "
        "    division must equal the activity's owner_division.\n"
        "  * UPDATE: caller is the activity's vendor (or admin)."
    ),
    dependencies=[Depends(require_authenticated())],
)
def transition_inbox(
    request: Request,
    business_id: str,
    payload: TransitionRequest,
    controller: Annotated[
        ApprovalInboxController, Depends(get_approval_inbox_controller),
    ],
):
    return controller.transition(request, business_id, payload)
