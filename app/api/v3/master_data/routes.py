"""Master-data router — user-mgmt slim slice (doc 37 part 2).

Routes hosted here:
  - /api/v3/master/roles                    (delegates to ../roles handlers)
  - /api/v3/master/permissions              (delegates to ../permissions handlers)
  - /api/v3/master/permissions/by-module    (doc 33 change 2)
  - /api/v3/master/notification_templates   (doc 36)

Roles and permissions delegate to the existing legacy route handlers
in ``app/api/v3/roles/`` and ``app/api/v3/permissions/`` — same
pattern as the monolith — so we don't duplicate the
RBAC-management plumbing. Notification templates are implemented
directly here against the ``notification_templates`` table.

The other monolith master-data slices (divisions, vendors, etc.) live
on the monolith side. When user-mgmt is fronted by the monolith proxy
(USER_SERVICE_PROXY_ENABLED in the monolith), the monolith routes
these specific master paths here; everything else stays on the
monolith.
"""
from collections import defaultdict
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.errors import (
    AlreadyExistsError,
    NotFoundError,
    ValidationError,
)
from ....core.middleware.rbac import require_permission
from ....core.permissions import MASTER_DATA_MANAGE, MASTER_DATA_VIEW
from ....infrastructure.db.repositories.rbac_repository import RbacRepository
from ....infrastructure.db.session import get_db

# Delegates: legacy /roles + /permissions handlers.
from ..roles.routes import (
    create_role as _role_create,
    delete_role as _role_delete,
    get_role as _role_get,
    grant_role_permission as _role_grant_permission,
    list_role_permissions as _role_list_permissions,
    list_roles as _role_list,
    replace_role_permissions as _role_replace_permissions,
    revoke_role_permission as _role_revoke_permission,
    update_role as _role_update,
)
from ..roles.schemas import (
    RoleCreateRequest,
    RolePermissionsReplaceRequest,
    RoleUpdateRequest,
)
from ..permissions.routes import (
    create_permission as _perm_create,
    delete_permission as _perm_delete,
    get_permission as _perm_get,
    list_permissions as _perm_list,
    update_permission as _perm_update,
)
from ..permissions.schemas import (
    PermissionCreateRequest,
    PermissionUpdateRequest,
)

from .schemas import (
    NotificationTemplateCreateRequest,
    NotificationTemplateUpdateRequest,
    _validate_placeholder_set,
)


router = APIRouter(prefix="/master", tags=["master_data"])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _without_deprecation(response: JSONResponse) -> JSONResponse:
    """Strip Deprecation/Link headers stamped by legacy handlers."""
    for h in ("Deprecation", "Link"):
        if h in response.headers:
            del response.headers[h]
    return response


def _collection(items: List[Dict[str, Any]], self_href: str) -> Dict[str, Any]:
    return {
        "_type": "Collection",
        "_links": {"self": {"href": self_href}},
        "total": len(items),
        "count": len(items),
        "_embedded": {"elements": items},
    }


# ---------------------------------------------------------------------------
# Roles — delegate to ../roles/routes.py.
# ---------------------------------------------------------------------------

@router.get(
    "/roles",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="List roles (delegates to GET /api/v3/roles)",
)
def list_master_roles(
    request: Request,
    offset: int = 1,
    pageSize: int = 20,
    db: Session = Depends(get_db),
):
    sql_offset = (offset - 1) * pageSize if offset > 0 else 0
    return _without_deprecation(
        _role_list(
            request=request, offset=sql_offset, pageSize=pageSize, db=db,
        ),
    )


@router.get(
    "/roles/{role_id}",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="Get a role (delegates)",
)
def get_master_role(
    request: Request, role_id: int, db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_get(request=request, role_id=role_id, db=db),
    )


@router.post(
    "/roles/create",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Create a role (delegates)",
    status_code=201,
)
def create_master_role(
    request: Request,
    data: RoleCreateRequest,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_create(request=request, data=data, db=db),
    )


@router.patch(
    "/roles/{role_id}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Update a role (delegates)",
)
def update_master_role(
    request: Request,
    role_id: int,
    data: RoleUpdateRequest,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_update(request=request, role_id=role_id, data=data, db=db),
    )


@router.delete(
    "/roles/{role_id}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Delete a role (admin role protected; delegates)",
)
def delete_master_role(
    request: Request, role_id: int, db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_delete(request=request, role_id=role_id, db=db),
    )


@router.get(
    "/roles/{role_id}/permissions",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="List a role's permissions (delegates)",
)
def list_master_role_permissions(
    request: Request, role_id: int, db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_list_permissions(request=request, role_id=role_id, db=db),
    )


@router.put(
    "/roles/{role_id}/permissions",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Replace a role's permission set (delegates)",
)
def replace_master_role_permissions(
    request: Request,
    role_id: int,
    data: RolePermissionsReplaceRequest,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_replace_permissions(
            request=request, role_id=role_id, data=data, db=db,
        ),
    )


@router.post(
    "/roles/{role_id}/permissions/{code}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Grant a permission to a role (delegates)",
)
def grant_master_role_permission(
    request: Request, role_id: int, code: str,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_grant_permission(
            request=request, role_id=role_id, code=code, db=db,
        ),
    )


@router.delete(
    "/roles/{role_id}/permissions/{code}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Revoke a permission from a role (delegates)",
)
def revoke_master_role_permission(
    request: Request, role_id: int, code: str,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_revoke_permission(
            request=request, role_id=role_id, code=code, db=db,
        ),
    )


# ---------------------------------------------------------------------------
# Permissions — delegate to ../permissions/routes.py.
# ---------------------------------------------------------------------------

@router.get(
    "/permissions",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="List the permission catalog (delegates)",
)
def list_master_permissions(
    request: Request,
    offset: int = 1,
    pageSize: int = 100,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _perm_list(
            request=request, offset=offset, pageSize=pageSize, db=db,
        ),
    )


@router.get(
    "/permissions/by-module",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="List the permission catalog grouped by module (doc 33 change 2)",
)
def list_master_permissions_by_module(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = RbacRepository(db)
    rows, total = repo.list_permissions(offset=0, limit=10_000)
    buckets: Dict[str, list] = defaultdict(list)
    for r in rows:
        module = r.code.split(":", 1)[0] if ":" in r.code else "_uncategorised"
        buckets[module].append({
            "_type": "Permission",
            "code": r.code,
            "name": r.name,
            "description": r.description,
            "isBuiltin": bool(r.is_builtin),
            "createdAt": r.created_at.isoformat() if r.created_at else None,
            "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
        })
    modules_list = [
        {
            "_type": "PermissionModule",
            "module": module,
            "count": len(perms),
            "permissions": sorted(perms, key=lambda p: p["code"]),
        }
        for module, perms in sorted(buckets.items(), key=lambda kv: kv[0])
    ]
    payload = {
        "_type": "PermissionsByModule",
        "_links": {"self": {"href": "/api/v3/master/permissions/by-module"}},
        "moduleCount": len(modules_list),
        "totalPermissions": total,
        "_embedded": {"modules": modules_list},
    }
    return BaseController.ok(data=payload)


@router.get(
    "/permissions/{code}",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="Get a permission row (delegates)",
)
def get_master_permission(
    request: Request, code: str, db: Session = Depends(get_db),
):
    return _without_deprecation(
        _perm_get(request=request, code=code, db=db),
    )


@router.post(
    "/permissions/create",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Create a custom permission (delegates)",
    status_code=201,
)
def create_master_permission(
    request: Request,
    data: PermissionCreateRequest,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _perm_create(request=request, data=data, db=db),
    )


@router.patch(
    "/permissions/{code}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Edit a permission's name/description (delegates)",
)
def update_master_permission(
    request: Request,
    code: str,
    data: PermissionUpdateRequest,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _perm_update(request=request, code=code, data=data, db=db),
    )


@router.delete(
    "/permissions/{code}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Delete a permission (built-ins protected; delegates)",
)
def delete_master_permission(
    request: Request, code: str, db: Session = Depends(get_db),
):
    return _without_deprecation(
        _perm_delete(request=request, code=code, db=db),
    )


# ---------------------------------------------------------------------------
# Notification templates (doc 36)
# ---------------------------------------------------------------------------

def _notification_template_to_response(row) -> Dict[str, Any]:
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
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _find_active_template(db: Session, *, template_kind: str, channel: str):
    from ....infrastructure.db.models.notification_template import (
        NotificationTemplateModel,
    )
    return (
        db.query(NotificationTemplateModel)
        .filter(NotificationTemplateModel.template_kind == template_kind)
        .filter(NotificationTemplateModel.channel == channel)
        .filter(NotificationTemplateModel.active.is_(True))
        .first()
    )


@router.get(
    "/notification_templates",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="List notification templates (admin view shows soft-disabled too)",
)
def list_master_notification_templates(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from ....infrastructure.db.models.notification_template import (
        NotificationTemplateModel,
    )
    q = db.query(NotificationTemplateModel)
    if not include_inactive:
        q = q.filter(NotificationTemplateModel.active.is_(True))
    rows = q.order_by(
        NotificationTemplateModel.template_kind.asc(),
        NotificationTemplateModel.channel.asc(),
        NotificationTemplateModel.id.asc(),
    ).all()
    items = [_notification_template_to_response(r) for r in rows]
    return BaseController.ok(
        data=_collection(items, "/api/v3/master/notification_templates"),
    )


@router.get(
    "/notification_templates/{template_id}",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="Get a notification template",
)
def get_master_notification_template(
    request: Request,
    template_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from ....infrastructure.db.models.notification_template import (
        NotificationTemplateModel,
    )
    row = db.get(NotificationTemplateModel, template_id)
    if row is None:
        raise NotFoundError(f"No notification_template with id {template_id}.")
    return BaseController.ok(data=_notification_template_to_response(row))


@router.post(
    "/notification_templates/create",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Create a notification template",
    status_code=201,
)
def create_master_notification_template(
    request: Request,
    data: NotificationTemplateCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from ....infrastructure.db.models.notification_template import (
        NotificationTemplateModel,
    )
    existing = _find_active_template(
        db, template_kind=data.templateKind, channel=data.channel,
    )
    if existing is not None:
        raise AlreadyExistsError(
            f"An active notification_template already exists for "
            f"(kind='{data.templateKind}', channel='{data.channel}') "
            f"— id={existing.id}."
        )
    is_html_default = data.channel == "email"
    row = NotificationTemplateModel(
        template_kind=data.templateKind,
        channel=data.channel,
        subject=(data.subject or None),
        body=data.body,
        is_html=is_html_default if data.isHtml is None else bool(data.isHtml),
        is_builtin=False,
        active=bool(data.active),
        description=data.description,
    )
    db.add(row)
    db.flush()
    db.commit()
    return BaseController.created(data=_notification_template_to_response(row))


@router.patch(
    "/notification_templates/{template_id}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Update a notification template",
)
def update_master_notification_template(
    request: Request,
    template_id: int,
    data: NotificationTemplateUpdateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from ....infrastructure.db.models.notification_template import (
        NotificationTemplateModel,
    )
    row = db.get(NotificationTemplateModel, template_id)
    if row is None:
        raise NotFoundError(f"No notification_template with id {template_id}.")
    new_subject = row.subject if data.subject is None else (
        (data.subject or "").strip() or None
    )
    new_body = row.body if data.body is None else data.body
    if row.channel == "email" and not (new_subject or "").strip():
        raise ValidationError("subject is required for email templates")
    if row.channel == "sms" and (new_subject or "").strip():
        raise ValidationError("subject must be omitted for sms templates")
    try:
        _validate_placeholder_set(
            template_kind=row.template_kind,
            channel=row.channel,
            subject=new_subject,
            body=new_body,
        )
    except ValueError as e:
        raise ValidationError(str(e))
    will_be_active = row.active if data.active is None else bool(data.active)
    if will_be_active and not row.active:
        clash = _find_active_template(
            db, template_kind=row.template_kind, channel=row.channel,
        )
        if clash is not None and clash.id != row.id:
            raise AlreadyExistsError(
                f"Another active notification_template (id={clash.id}) "
                f"already covers (kind='{row.template_kind}', "
                f"channel='{row.channel}'). Deactivate it first."
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
    db.commit()
    return BaseController.ok(data=_notification_template_to_response(row))


@router.delete(
    "/notification_templates/{template_id}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Soft-deactivate a notification template",
)
def delete_master_notification_template(
    request: Request,
    template_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from ....infrastructure.db.models.notification_template import (
        NotificationTemplateModel,
    )
    row = db.get(NotificationTemplateModel, template_id)
    if row is None:
        raise NotFoundError(f"No notification_template with id {template_id}.")
    row.active = False
    db.flush()
    db.commit()
    return BaseController.ok(data=_notification_template_to_response(row))


@router.post(
    "/notification_templates/{template_id}/restore",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Re-activate a soft-disabled notification template",
)
def restore_master_notification_template(
    request: Request,
    template_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from ....infrastructure.db.models.notification_template import (
        NotificationTemplateModel,
    )
    row = db.get(NotificationTemplateModel, template_id)
    if row is None:
        raise NotFoundError(f"No notification_template with id {template_id}.")
    clash = _find_active_template(
        db, template_kind=row.template_kind, channel=row.channel,
    )
    if clash is not None and clash.id != row.id:
        raise AlreadyExistsError(
            f"Another active notification_template (id={clash.id}) "
            f"already covers (kind='{row.template_kind}', "
            f"channel='{row.channel}'). Deactivate it first."
        )
    row.active = True
    db.flush()
    db.commit()
    return BaseController.ok(data=_notification_template_to_response(row))
