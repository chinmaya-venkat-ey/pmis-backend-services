"""Master-data router (doc 38).

Hosts /api/v3/master/notification_templates/* — the only master slice
this service owns. The monolith's NotificationServiceProxyMiddleware
(doc 38) forwards these paths from port 8000 here.

Same wire shape as user-service used to expose; the move is
ownership-only.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..core.permissions import MASTER_DATA_MANAGE, MASTER_DATA_VIEW
from ..db.models.notification_template import NotificationTemplateModel
from ..db.repositories.notification_template_repository import (
    NotificationTemplateRepository,
)
from ..db.session import get_db
from ..middleware.auth_middleware import require_permission
from ..schemas.notification_template import (
    NotificationTemplateCreateRequest,
    NotificationTemplateUpdateRequest,
    validate_placeholder_set,
)
from ..utilities.timezones import iso_ist


router = APIRouter(
    prefix="/api/v3/master/notification_templates",
    tags=["master_data"],
)


# ---------------------------------------------------------------------------
# Response shapes — match the monolith / user-service envelope so the
# proxy is byte-compatible from the FE perspective.
# ---------------------------------------------------------------------------

def _to_response(row: NotificationTemplateModel) -> Dict[str, Any]:
    return {
        "_type": "NotificationTemplate",
        "id": row.id,
        "templateKind": row.template_kind,
        "channel": row.channel,
        "subject": row.subject,
        "body": row.body,
        "isHtml": bool(row.is_html),
        "isBuiltin": bool(row.is_builtin),
        "active": bool(row.active),
        "description": row.description,
        "createdAt": iso_ist(row.created_at),
        "updatedAt": iso_ist(row.updated_at),
    }


def _ok(data: Any, status_code: int = 200) -> Dict[str, Any]:
    return {"data": data, "message": None, "error": None, "status": status_code}


def _collection(items, self_href: str) -> Dict[str, Any]:
    return {
        "_type": "Collection",
        "_links": {"self": {"href": self_href}},
        "total": len(items),
        "count": len(items),
        "_embedded": {"elements": items},
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "",
    summary="List notification templates",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
)
def list_templates(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    rows = NotificationTemplateRepository(db).list_(include_inactive=include_inactive)
    items = [_to_response(r) for r in rows]
    return _ok(_collection(items, "/api/v3/master/notification_templates"))


@router.get(
    "/{template_id}",
    summary="Get a notification template",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
)
def get_template(
    request: Request,
    template_id: int,
    db: Session = Depends(get_db),
):
    row = NotificationTemplateRepository(db).get_by_id(template_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "errorIdentifier": "NotFoundError",
                "message": f"No notification_template with id {template_id}.",
            },
        )
    return _ok(_to_response(row))


@router.post(
    "/create",
    summary="Create a notification template",
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
)
def create_template(
    request: Request,
    data: NotificationTemplateCreateRequest,
    db: Session = Depends(get_db),
):
    repo = NotificationTemplateRepository(db)
    existing = repo.find_active(template_kind=data.templateKind, channel=data.channel)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "errorIdentifier": "AlreadyExistsError",
                "message": (
                    f"An active notification_template already exists for "
                    f"(kind='{data.templateKind}', channel='{data.channel}') "
                    f"— id={existing.id}."
                ),
            },
        )
    is_html_default = data.channel == "email"
    row = repo.create(
        template_kind=data.templateKind,
        channel=data.channel,
        subject=(data.subject or None),
        body=data.body,
        is_html=is_html_default if data.isHtml is None else bool(data.isHtml),
        is_builtin=False,
        active=bool(data.active),
        description=data.description,
    )
    repo.commit()
    return _ok(_to_response(row), status_code=201)


@router.patch(
    "/{template_id}",
    summary="Update a notification template",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
)
def update_template(
    request: Request,
    template_id: int,
    data: NotificationTemplateUpdateRequest,
    db: Session = Depends(get_db),
):
    repo = NotificationTemplateRepository(db)
    row = repo.get_by_id(template_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "errorIdentifier": "NotFoundError",
                "message": f"No notification_template with id {template_id}.",
            },
        )
    new_subject = row.subject if data.subject is None else (
        (data.subject or "").strip() or None
    )
    new_body = row.body if data.body is None else data.body
    if row.channel == "email" and not (new_subject or "").strip():
        raise HTTPException(
            status_code=422,
            detail={"errorIdentifier": "ValidationError", "message": "subject is required for email templates"},
        )
    if row.channel == "sms" and (new_subject or "").strip():
        raise HTTPException(
            status_code=422,
            detail={"errorIdentifier": "ValidationError", "message": "subject must be omitted for sms templates"},
        )
    try:
        validate_placeholder_set(
            template_kind=row.template_kind,
            channel=row.channel,
            subject=new_subject,
            body=new_body,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"errorIdentifier": "ValidationError", "message": str(e)},
        )
    will_be_active = row.active if data.active is None else bool(data.active)
    if will_be_active and not row.active:
        clash = repo.find_active(template_kind=row.template_kind, channel=row.channel)
        if clash is not None and clash.id != row.id:
            raise HTTPException(
                status_code=409,
                detail={
                    "errorIdentifier": "AlreadyExistsError",
                    "message": (
                        f"Another active notification_template (id={clash.id}) "
                        f"already covers (kind='{row.template_kind}', "
                        f"channel='{row.channel}'). Deactivate it first."
                    ),
                },
            )
    row.subject = new_subject
    row.body = new_body
    if data.isHtml is not None:
        row.is_html = bool(data.isHtml)
    if data.description is not None:
        row.description = data.description
    if data.active is not None:
        row.active = bool(data.active)
    db.flush()
    repo.commit()
    return _ok(_to_response(row))


@router.delete(
    "/{template_id}",
    summary="Soft-deactivate a notification template",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
)
def delete_template(
    request: Request,
    template_id: int,
    db: Session = Depends(get_db),
):
    repo = NotificationTemplateRepository(db)
    row = repo.get_by_id(template_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "errorIdentifier": "NotFoundError",
                "message": f"No notification_template with id {template_id}.",
            },
        )
    row.active = False
    db.flush()
    repo.commit()
    return _ok(_to_response(row))


@router.post(
    "/{template_id}/restore",
    summary="Re-activate a soft-disabled notification template",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
)
def restore_template(
    request: Request,
    template_id: int,
    db: Session = Depends(get_db),
):
    repo = NotificationTemplateRepository(db)
    row = repo.get_by_id(template_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "errorIdentifier": "NotFoundError",
                "message": f"No notification_template with id {template_id}.",
            },
        )
    clash = repo.find_active(template_kind=row.template_kind, channel=row.channel)
    if clash is not None and clash.id != row.id:
        raise HTTPException(
            status_code=409,
            detail={
                "errorIdentifier": "AlreadyExistsError",
                "message": (
                    f"Another active notification_template (id={clash.id}) "
                    f"already covers (kind='{row.template_kind}', "
                    f"channel='{row.channel}'). Deactivate it first."
                ),
            },
        )
    row.active = True
    db.flush()
    repo.commit()
    return _ok(_to_response(row))
