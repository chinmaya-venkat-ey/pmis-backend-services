"""Routes for the notification_templates catalog (moved here per Q3).

notification-svc reads this catalog cross-schema for dispatch rendering;
masters-svc owns CRUD. Restore is guarded against creating two active
rows for the same (template_kind, channel) — see explanation in PLAN.md §9.6
and the user's confirmation (option A).
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.notification_template_controller import (
    NotificationTemplateController,
)
from app.core.permissions import (
    NOTIFICATION_TEMPLATES_MANAGE,
    NOTIFICATION_TEMPLATES_READ,
)
from app.core.rbac import require_permission
from app.dependencies import get_notification_template_controller
from app.schemas.notification_template import (
    NotificationTemplateCreateRequest,
    NotificationTemplateResponse,
    NotificationTemplateUpdateRequest,
)


router = APIRouter(prefix="/notification_templates", tags=["notification_templates"])


@router.get(
    "",
    response_model=List[NotificationTemplateResponse],
    summary="List notification templates",
    dependencies=[Depends(require_permission(NOTIFICATION_TEMPLATES_READ))],
)
def list_notification_templates(
    include_inactive: bool = Query(False, description="Include deactivated rows"),
    controller: NotificationTemplateController = Depends(
        get_notification_template_controller
    ),
) -> List[NotificationTemplateResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{template_id}",
    response_model=NotificationTemplateResponse,
    summary="Get notification template details",
    dependencies=[Depends(require_permission(NOTIFICATION_TEMPLATES_READ))],
    responses={404: {"description": "NotificationTemplate not found"}},
)
def get_notification_template_details(
    template_id: int,
    controller: NotificationTemplateController = Depends(
        get_notification_template_controller
    ),
) -> NotificationTemplateResponse:
    return controller.get_details(template_id)


@router.post(
    "/create",
    response_model=NotificationTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a notification template",
    description=(
        "Creates a new template for (template_kind, channel). "
        "Conflicts (an active row already exists for the pair) return 409. "
        "`subject` is required when channel=email."
    ),
    dependencies=[Depends(require_permission(NOTIFICATION_TEMPLATES_MANAGE))],
    responses={409: {"description": "Active template for this (kind, channel) already exists"}},
)
def create_notification_template(
    payload: NotificationTemplateCreateRequest,
    controller: NotificationTemplateController = Depends(
        get_notification_template_controller
    ),
) -> NotificationTemplateResponse:
    return controller.create(payload)


@router.patch(
    "/{template_id}",
    response_model=NotificationTemplateResponse,
    summary="Update a notification template",
    description="`template_kind` and `channel` are immutable.",
    dependencies=[Depends(require_permission(NOTIFICATION_TEMPLATES_MANAGE))],
    responses={404: {"description": "NotificationTemplate not found"}},
)
def update_notification_template(
    template_id: int,
    payload: NotificationTemplateUpdateRequest,
    controller: NotificationTemplateController = Depends(
        get_notification_template_controller
    ),
) -> NotificationTemplateResponse:
    return controller.update(template_id, payload)


@router.delete(
    "/{template_id}",
    response_model=NotificationTemplateResponse,
    summary="Delete (deactivate) a notification template",
    dependencies=[Depends(require_permission(NOTIFICATION_TEMPLATES_MANAGE))],
    responses={404: {"description": "NotificationTemplate not found"}},
)
def delete_notification_template(
    template_id: int,
    controller: NotificationTemplateController = Depends(
        get_notification_template_controller
    ),
) -> NotificationTemplateResponse:
    return controller.delete(template_id)


@router.post(
    "/{template_id}/restore",
    response_model=NotificationTemplateResponse,
    summary="Restore (reactivate) a notification template",
    description=(
        "Restore is REJECTED if another row for the same (template_kind, "
        "channel) is currently active. Deactivate the conflicting one first."
    ),
    dependencies=[Depends(require_permission(NOTIFICATION_TEMPLATES_MANAGE))],
    responses={
        404: {"description": "NotificationTemplate not found"},
        409: {"description": "Another active template exists for this (kind, channel)"},
    },
)
def restore_notification_template(
    template_id: int,
    controller: NotificationTemplateController = Depends(
        get_notification_template_controller
    ),
) -> NotificationTemplateResponse:
    return controller.restore(template_id)
