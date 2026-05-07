"""Consolidated master-data router (doc 20).

All catalog CRUD lives here under ``/api/v3/master/*``. Vendors delegate
to the existing vendor route handlers so we don't duplicate the
mapping-validation / soft-delete / restore logic that already lives in
[vendors/routes.py](../vendors/routes.py); the rest write small
projection helpers + thin route wrappers around the corresponding
repository methods.

The legacy endpoints (``/api/v3/divisions``, ``/api/v3/resource_types``,
``/api/v3/project_status_transitions``, ``/api/v3/vendors/*``) keep
working during the FE migration window and stamp ``Deprecation: true``
on every response — see [vendors/routes.py](../vendors/routes.py),
[catalogs/routes.py](../catalogs/routes.py),
[resource_types/routes.py](../resource_types/routes.py).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.errors import (
    AlreadyExistsError,
    AuthorizationError,
    NotFoundError,
    ValidationError,
)
from ....core.middleware.rbac import require_permission
from ....core.rbac import Permission
from ....infrastructure.db.repositories.division_repository import (
    DivisionRepository,
    slugify,
)
from ....infrastructure.db.repositories.project_status_transition_repository import (
    ProjectStatusTransitionRepository,
)
from ....infrastructure.db.repositories.resource_type_repository import (
    ResourceTypeRepository,
)
from ....infrastructure.db.session import get_db

# Vendor delegation — reuse the existing route handlers to avoid
# duplicating the mapping / soft-delete / restore plumbing.
from ..vendors.routes import (
    create_vendor as _vendor_create,
    delete_vendor as _vendor_delete,
    get_vendor as _vendor_get,
    list_vendor_projects as _vendor_list_projects,
    list_vendors as _vendor_list,
    restore_vendor as _vendor_restore,
    update_vendor as _vendor_update,
)
from ..vendors.schemas import VendorCreateRequest, VendorUpdateRequest

# NOTE: roles / permissions / notification_templates handlers are NOT
# surfaced under /api/v3/master/* in pmis-project-service. user-service
# owns the auth + notification template surface; project-service does
# not duplicate it.

from .schemas import (
    ActivityStatusCreateRequest,
    ActivityStatusUpdateRequest,
    ActivityTypeCreateRequest,
    ActivityTypeUpdateRequest,
    DivisionCreateRequest,
    DivisionUpdateRequest,
    MilestoneStatusCreateRequest,
    MilestoneStatusUpdateRequest,
    ProjectCategoryCreateRequest,
    ProjectCategoryUpdateRequest,
    ProjectStatusTransitionCreateRequest,
    ProjectStatusTransitionUpdateRequest,
    ResourceTypeCreateRequest,
    ResourceTypeUpdateRequest,
)


router = APIRouter(prefix="/master", tags=["master_data"])


# Built-in division codes — mirror the init_db seed. Used to gate
# admin DELETE / PATCH attempts that would break the strict-division
# validator.
_BUILTIN_DIVISION_CODES = ("tmd1", "tmd2", "others")


# ---------------------------------------------------------------------------
# Projection helpers (single source of truth for response shapes)
# ---------------------------------------------------------------------------

def _division_to_response(row) -> Dict[str, Any]:
    return {
        "_type": "Division",
        "id": row.id,
        "code": row.code,
        "label": row.label,
        "isBuiltin": bool(row.is_builtin),
        "requiresOther": bool(row.requires_other),
        "active": bool(row.active),
        "email": row.email,
        "phoneNumber": row.phone_number,
    }


def _transition_to_response(row) -> Dict[str, Any]:
    return {
        "_type": "ProjectStatusTransition",
        "id": row.id,
        "fromStatus": row.from_status,
        "toStatus": row.to_status,
        "requiresAdmin": bool(row.requires_admin),
        "active": bool(row.active),
        "description": row.description,
    }


def _resource_type_to_response(rt) -> Dict[str, Any]:
    """Accept either domain entity or raw dict (from to_dict)."""
    d = rt.to_dict() if hasattr(rt, "to_dict") else rt
    return {
        "_type": "ResourceType",
        "id": d["id"],
        "code": d["code"],
        "name": d["name"],
        "active": d.get("active", True),
        "createdAt": d.get("created_at"),
        "updatedAt": d.get("updated_at"),
    }


def _collection(items: List[Dict[str, Any]], self_href: str) -> Dict[str, Any]:
    return {
        "_type": "Collection",
        "_links": {"self": {"href": self_href}},
        "total": len(items),
        "count": len(items),
        "_embedded": {"elements": items},
    }


# ---------------------------------------------------------------------------
# Divisions
# ---------------------------------------------------------------------------

@router.get(
    "/divisions",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="List divisions (admin view shows soft-disabled rows too)",
    description=(
        "Returns the divisions catalog. By default only active rows are "
        "returned (matches the FE picker's filter). Pass "
        "``?include_inactive=true`` to include soft-disabled rows for "
        "admin curation views."
    ),
)
def list_master_divisions(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = DivisionRepository(db)
    rows = repo.list_all() if include_inactive else repo.list_active()
    items = [_division_to_response(r) for r in rows]
    return BaseController.ok(data=_collection(items, "/api/v3/master/divisions"))


@router.post(
    "/divisions/create",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Create a division (admin)",
    status_code=201,
)
def create_master_division(
    request: Request,
    data: DivisionCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = DivisionRepository(db)
    # Derive the wire code now (so the conflict check uses the same value
    # the repo would). Empty after slugify -> 422.
    wire_code = (data.code or "").strip().lower() or slugify(data.label)
    if not wire_code:
        raise ValidationError(
            "Either 'code' or a label that produces a non-empty slug is required.",
        )
    existing = repo.get_by_code_any(wire_code)
    if existing is not None:
        raise AlreadyExistsError(
            f"A division with code '{wire_code}' already exists "
            f"(active={existing.active}).",
        )
    row = repo.create(
        code=wire_code,
        label=data.label,
        requires_other=data.requires_other,
        email=data.email,
        phone_number=data.phoneNumber,
    )
    db.commit()
    return BaseController.created(data=_division_to_response(row))


@router.patch(
    "/divisions/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Update a division (admin)",
    description=(
        "Patch ``label`` / ``requiresOther`` / ``email`` / "
        "``phoneNumber``. ``code`` is NOT patchable — every project's "
        "``owner`` column references it; renaming would break existing "
        "rows. Built-in rows (``tmd1`` / ``tmd2`` / ``others``) accept "
        "``email`` / ``phoneNumber`` updates so admins can attach "
        "contact details to the seeded divisions, but reject "
        "``label`` / ``requiresOther`` changes with 403."
    ),
)
def update_master_division(
    request: Request,
    code: str,
    data: DivisionUpdateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = DivisionRepository(db)
    row = repo.get_by_code_any(code)
    if row is None:
        raise NotFoundError(f"No division with code '{code}'.")
    # Built-ins are open for contact-detail patches but locked down on
    # the structural fields. Allowing label / requires_other on a
    # seeded row would break the strict-division validator that pins
    # the FE picker to the canonical wire codes.
    if row.is_builtin and (
        data.label is not None or data.requires_other is not None
    ):
        raise AuthorizationError(
            f"Built-in division '{row.code}' cannot be renamed or have "
            f"its requiresOther flag changed. Email / phoneNumber may "
            f"still be updated.",
        )
    updated = repo.update(
        code,
        label=data.label,
        requires_other=data.requires_other,
        email=data.email,
        phone_number=data.phoneNumber,
    )
    db.commit()
    return BaseController.ok(data=_division_to_response(updated))


@router.delete(
    "/divisions/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Soft-delete a division (admin) — sets active=false",
    description=(
        "Soft delete: the row stays in the DB so existing projects / "
        "users / activity_resources referencing this code keep "
        "rendering. The picker hides it for new selections. Restore "
        "via PATCH-isn't-quite-right (active isn't on the patch "
        "schema); use POST /divisions/{code}/restore."
    ),
)
def delete_master_division(
    request: Request,
    code: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = DivisionRepository(db)
    row = repo.get_by_code_any(code)
    if row is None:
        raise NotFoundError(f"No division with code '{code}'.")
    if row.is_builtin:
        raise AuthorizationError(
            f"Built-in division '{row.code}' cannot be deleted.",
        )
    updated = repo.set_active(code, active=False)
    db.commit()
    return BaseController.ok(data=_division_to_response(updated))


@router.post(
    "/divisions/{code}/restore",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Restore a soft-disabled division (admin)",
)
def restore_master_division(
    request: Request,
    code: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = DivisionRepository(db)
    row = repo.get_by_code_any(code)
    if row is None:
        raise NotFoundError(f"No division with code '{code}'.")
    updated = repo.set_active(code, active=True)
    db.commit()
    return BaseController.ok(data=_division_to_response(updated))


# ---------------------------------------------------------------------------
# Project status transitions
# ---------------------------------------------------------------------------

@router.get(
    "/project_status_transitions",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="List project status transitions (admin view shows inactive too)",
)
def list_master_transitions(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = ProjectStatusTransitionRepository(db)
    rows = repo.list_all() if include_inactive else repo.list_active()
    items = [_transition_to_response(r) for r in rows]
    return BaseController.ok(data=_collection(
        items, "/api/v3/master/project_status_transitions",
    ))


@router.post(
    "/project_status_transitions/create",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Add a new (from_status, to_status) edge (admin)",
    status_code=201,
)
def create_master_transition(
    request: Request,
    data: ProjectStatusTransitionCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = ProjectStatusTransitionRepository(db)
    existing = repo.find_edge_any(data.from_status, data.to_status)
    if existing is not None:
        raise AlreadyExistsError(
            f"A transition '{existing.from_status} -> {existing.to_status}' "
            f"already exists (id={existing.id}, active={existing.active}). "
            f"PATCH it or POST /restore instead of re-creating.",
        )
    row = repo.create(
        from_status=data.from_status,
        to_status=data.to_status,
        requires_admin=data.requires_admin,
        description=data.description,
    )
    db.commit()
    return BaseController.created(data=_transition_to_response(row))


@router.patch(
    "/project_status_transitions/{row_id}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Update a transition's policy flags / description (admin)",
)
def update_master_transition(
    request: Request,
    row_id: int,
    data: ProjectStatusTransitionUpdateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = ProjectStatusTransitionRepository(db)
    updated = repo.update(
        row_id,
        requires_admin=data.requires_admin,
        description=data.description,
    )
    if updated is None:
        raise NotFoundError(f"No project_status_transition with id {row_id}.")
    db.commit()
    return BaseController.ok(data=_transition_to_response(updated))


@router.delete(
    "/project_status_transitions/{row_id}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Soft-delete a transition (admin) — sets active=false",
)
def delete_master_transition(
    request: Request,
    row_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = ProjectStatusTransitionRepository(db)
    updated = repo.set_active(row_id, active=False)
    if updated is None:
        raise NotFoundError(f"No project_status_transition with id {row_id}.")
    db.commit()
    return BaseController.ok(data=_transition_to_response(updated))


@router.post(
    "/project_status_transitions/{row_id}/restore",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Restore a soft-disabled transition (admin)",
)
def restore_master_transition(
    request: Request,
    row_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = ProjectStatusTransitionRepository(db)
    updated = repo.set_active(row_id, active=True)
    if updated is None:
        raise NotFoundError(f"No project_status_transition with id {row_id}.")
    db.commit()
    return BaseController.ok(data=_transition_to_response(updated))


# ---------------------------------------------------------------------------
# Resource types
# ---------------------------------------------------------------------------

@router.get(
    "/resource_types",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="List resource types (admin view shows inactive too)",
)
def list_master_resource_types(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = ResourceTypeRepository(db)
    rows = repo.list_all() if include_inactive else repo.list_active()
    items = [_resource_type_to_response(rt) for rt in rows]
    return BaseController.ok(data=_collection(items, "/api/v3/master/resource_types"))


@router.post(
    "/resource_types/create",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Create a resource type (admin)",
    status_code=201,
)
def create_master_resource_type(
    request: Request,
    data: ResourceTypeCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = ResourceTypeRepository(db)
    if repo.exists_by_code(data.code):
        raise AlreadyExistsError(
            f"A resource type with code '{data.code.lower()}' already exists.",
        )
    rt = repo.create(code=data.code, name=data.name, active=data.active)
    db.commit()
    return BaseController.created(data=_resource_type_to_response(rt))


@router.patch(
    "/resource_types/{rt_id}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Update a resource type's name (admin)",
)
def update_master_resource_type(
    request: Request,
    rt_id: str,
    data: ResourceTypeUpdateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = ResourceTypeRepository(db)
    updated = repo.update(rt_id, name=data.name)
    if updated is None:
        raise NotFoundError(f"No resource_type with id {rt_id}.")
    db.commit()
    return BaseController.ok(data=_resource_type_to_response(updated))


@router.delete(
    "/resource_types/{rt_id}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Soft-delete a resource type (admin) — sets active=false",
)
def delete_master_resource_type(
    request: Request,
    rt_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = ResourceTypeRepository(db)
    updated = repo.set_active(rt_id, active=False)
    if updated is None:
        raise NotFoundError(f"No resource_type with id {rt_id}.")
    db.commit()
    return BaseController.ok(data=_resource_type_to_response(updated))


@router.post(
    "/resource_types/{rt_id}/restore",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Restore a soft-disabled resource type (admin)",
)
def restore_master_resource_type(
    request: Request,
    rt_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = ResourceTypeRepository(db)
    updated = repo.set_active(rt_id, active=True)
    if updated is None:
        raise NotFoundError(f"No resource_type with id {rt_id}.")
    db.commit()
    return BaseController.ok(data=_resource_type_to_response(updated))


# ---------------------------------------------------------------------------
# Vendors — delegate to the existing handlers in vendors/routes.py.
# Auth on the master surface is gated by MASTER_DATA_*; the legacy
# /api/v3/vendors/* endpoints continue to use the per-catalog
# VENDORS_READ / VENDORS_MANAGE permissions.
# ---------------------------------------------------------------------------

def _without_deprecation(response: JSONResponse) -> JSONResponse:
    """Strip the Deprecation/Link headers stamped by the legacy vendor
    handlers. The master_data router IS the successor — its responses
    must not be marked deprecated. Keeps the delegation lightweight
    without forcing a full impl-extraction refactor on vendors/routes.py.

    Starlette's ``MutableHeaders`` doesn't expose dict-style ``pop``; we
    use ``del`` guarded by a membership check.
    """
    for h in ("Deprecation", "Link"):
        if h in response.headers:
            del response.headers[h]
    return response


@router.get(
    "/vendors",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="List live vendors (delegates to GET /api/v3/vendors)",
)
def list_master_vendors(
    request: Request,
    active_only: bool = Query(
        False,
        description=(
            "When true, return only active vendors (legacy picker "
            "behaviour). Default false so management views see "
            "inactive rows too. Soft-deleted rows are always hidden."
        ),
    ),
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _without_deprecation(
        _vendor_list(request=request, active_only=active_only, db=db),
    )


@router.get(
    "/vendors/{vendor_id}",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="Get vendor detail (delegates to GET /api/v3/vendors/{id})",
)
def get_master_vendor(
    request: Request, vendor_id: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _without_deprecation(
        _vendor_get(request=request, vendor_id=vendor_id, db=db),
    )


@router.post(
    "/vendors/create",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Create a vendor (delegates)",
    status_code=201,
)
def create_master_vendor(
    request: Request,
    data: VendorCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _without_deprecation(
        _vendor_create(request=request, data=data, db=db),
    )


@router.patch(
    "/vendors/{vendor_id}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Update a vendor (delegates)",
)
def update_master_vendor(
    request: Request,
    vendor_id: str,
    data: VendorUpdateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _without_deprecation(
        _vendor_update(request=request, vendor_id=vendor_id, data=data, db=db),
    )


@router.delete(
    "/vendors/{vendor_id}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Soft-delete a vendor (delegates)",
)
def delete_master_vendor(
    request: Request,
    vendor_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _without_deprecation(
        _vendor_delete(request=request, vendor_id=vendor_id, db=db),
    )


@router.post(
    "/vendors/{vendor_id}/restore",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Restore a soft-deleted vendor (delegates)",
)
def restore_master_vendor(
    request: Request,
    vendor_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _without_deprecation(
        _vendor_restore(request=request, vendor_id=vendor_id, db=db),
    )


@router.get(
    "/vendors/{vendor_id}/projects",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="List projects mapped to a vendor (delegates)",
)
def list_master_vendor_projects(
    request: Request,
    vendor_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _without_deprecation(
        _vendor_list_projects(request=request, vendor_id=vendor_id, db=db),
    )


# ---------------------------------------------------------------------------
# Doc 37 part 1 — static-data master endpoints.
#
# Four small catalogs (project_categories, activity_types,
# milestone_statuses, activity_statuses). Each has the same 6-endpoint
# shape: list / get / create / patch / delete (soft) / restore. We
# build them via the helpers below to avoid 24 near-duplicate
# functions. ``code`` is the public identifier (matches the divisions
# precedent — referenced from the main domain tables).
# ---------------------------------------------------------------------------

from ....infrastructure.db.models.activity_status import ActivityStatusModel
from ....infrastructure.db.models.activity_type import ActivityTypeModel
from ....infrastructure.db.models.milestone_status import MilestoneStatusModel
from ....infrastructure.db.models.project_category import ProjectCategoryModel


def _project_category_to_response(row) -> Dict[str, Any]:
    return {
        "_type": "ProjectCategory",
        "id": row.id,
        "code": row.code,
        "label": row.label,
        "isBuiltin": bool(row.is_builtin),
        "requiresOther": bool(row.requires_other),
        "active": bool(row.active),
        "description": row.description,
    }


def _activity_type_to_response(row) -> Dict[str, Any]:
    return {
        "_type": "ActivityType",
        "id": row.id,
        "code": row.code,
        "label": row.label,
        "isBuiltin": bool(row.is_builtin),
        "active": bool(row.active),
        "description": row.description,
    }


def _milestone_status_to_response(row) -> Dict[str, Any]:
    return {
        "_type": "MilestoneStatus",
        "id": row.id,
        "code": row.code,
        "label": row.label,
        "isBuiltin": bool(row.is_builtin),
        "isTerminal": bool(row.is_terminal),
        "active": bool(row.active),
        "description": row.description,
    }


def _activity_status_to_response(row) -> Dict[str, Any]:
    return {
        "_type": "ActivityStatus",
        "id": row.id,
        "code": row.code,
        "label": row.label,
        "isBuiltin": bool(row.is_builtin),
        "isTerminal": bool(row.is_terminal),
        "active": bool(row.active),
        "description": row.description,
    }


def _list_catalog(
    request: Request,
    db: Session,
    *,
    model,
    projector,
    self_href: str,
    include_inactive: bool,
) -> JSONResponse:
    q = db.query(model)
    if not include_inactive:
        q = q.filter(model.active.is_(True))
    rows = q.order_by(
        model.is_builtin.desc(),
        model.id.asc(),
    ).all()
    items = [projector(r) for r in rows]
    return BaseController.ok(data=_collection(items, self_href))


def _get_catalog_by_code(
    db: Session, *, model, projector, code: str, kind: str,
) -> JSONResponse:
    row = db.query(model).filter(model.code == code).first()
    if row is None:
        raise NotFoundError(f"No {kind} with code '{code}'.")
    return BaseController.ok(data=projector(row))


def _create_catalog_row(
    db: Session, *, model, projector, kind: str, payload: Dict[str, Any],
) -> JSONResponse:
    code = (payload.get("code") or "").strip()
    if not code:
        raise ValidationError("'code' is required.")
    existing = db.query(model).filter(model.code == code).first()
    if existing is not None:
        raise AlreadyExistsError(
            f"A {kind} with code '{code}' already exists "
            f"(active={existing.active}).",
        )
    row = model(
        code=code,
        label=(payload.get("label") or "").strip(),
        is_builtin=False,
        active=bool(payload.get("active", True)),
        description=payload.get("description"),
    )
    if hasattr(model, "requires_other"):
        row.requires_other = bool(payload.get("requires_other", False))
    if hasattr(model, "is_terminal"):
        row.is_terminal = bool(payload.get("is_terminal", False))
    db.add(row)
    db.flush()
    db.commit()
    return BaseController.created(data=projector(row))


def _update_catalog_row(
    db: Session,
    *,
    model,
    projector,
    kind: str,
    code: str,
    payload: Dict[str, Any],
) -> JSONResponse:
    row = db.query(model).filter(model.code == code).first()
    if row is None:
        raise NotFoundError(f"No {kind} with code '{code}'.")
    if row.is_builtin:
        if (
            hasattr(model, "requires_other")
            and payload.get("requires_other") is not None
        ):
            raise AuthorizationError(
                f"Built-in {kind} '{row.code}' cannot have its "
                f"requiresOther flag changed.",
            )
        if (
            hasattr(model, "is_terminal")
            and payload.get("is_terminal") is not None
        ):
            raise AuthorizationError(
                f"Built-in {kind} '{row.code}' cannot have its "
                f"isTerminal flag changed.",
            )
    if payload.get("label") is not None:
        row.label = payload["label"].strip()
    if payload.get("description") is not None:
        row.description = payload["description"]
    if payload.get("active") is not None:
        row.active = bool(payload["active"])
    if (
        hasattr(model, "requires_other")
        and payload.get("requires_other") is not None
    ):
        row.requires_other = bool(payload["requires_other"])
    if hasattr(model, "is_terminal") and payload.get("is_terminal") is not None:
        row.is_terminal = bool(payload["is_terminal"])
    db.flush()
    db.commit()
    return BaseController.ok(data=projector(row))


def _set_active_catalog_row(
    db: Session,
    *,
    model,
    projector,
    kind: str,
    code: str,
    active: bool,
    refuse_builtin_delete: bool = True,
) -> JSONResponse:
    row = db.query(model).filter(model.code == code).first()
    if row is None:
        raise NotFoundError(f"No {kind} with code '{code}'.")
    if row.is_builtin and refuse_builtin_delete and not active:
        raise AuthorizationError(
            f"Built-in {kind} '{row.code}' cannot be deactivated.",
        )
    row.active = bool(active)
    db.flush()
    db.commit()
    return BaseController.ok(data=projector(row))


# ---------- project_categories ----------

@router.get(
    "/project_categories",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="List project categories (admin view shows soft-disabled rows too)",
)
def list_master_project_categories(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _list_catalog(
        request, db,
        model=ProjectCategoryModel,
        projector=_project_category_to_response,
        self_href="/api/v3/master/project_categories",
        include_inactive=include_inactive,
    )


@router.get(
    "/project_categories/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="Get a project category by code",
)
def get_master_project_category(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _get_catalog_by_code(
        db, model=ProjectCategoryModel,
        projector=_project_category_to_response,
        code=code, kind="project_category",
    )


@router.post(
    "/project_categories/create",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Create a project category (admin)",
    status_code=201,
)
def create_master_project_category(
    request: Request,
    data: ProjectCategoryCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _create_catalog_row(
        db, model=ProjectCategoryModel,
        projector=_project_category_to_response,
        kind="project_category",
        payload={
            "code": data.code,
            "label": data.label,
            "description": data.description,
            "active": data.active,
            "requires_other": data.requires_other,
        },
    )


@router.patch(
    "/project_categories/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Update a project category (admin)",
)
def update_master_project_category(
    request: Request,
    code: str,
    data: ProjectCategoryUpdateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _update_catalog_row(
        db, model=ProjectCategoryModel,
        projector=_project_category_to_response,
        kind="project_category", code=code,
        payload={
            "label": data.label,
            "description": data.description,
            "active": data.active,
            "requires_other": data.requires_other,
        },
    )


@router.delete(
    "/project_categories/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Soft-deactivate a project category (admin)",
)
def delete_master_project_category(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _set_active_catalog_row(
        db, model=ProjectCategoryModel,
        projector=_project_category_to_response,
        kind="project_category", code=code, active=False,
    )


@router.post(
    "/project_categories/{code}/restore",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Restore a soft-disabled project category (admin)",
)
def restore_master_project_category(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _set_active_catalog_row(
        db, model=ProjectCategoryModel,
        projector=_project_category_to_response,
        kind="project_category", code=code, active=True,
    )


# ---------- activity_types ----------

@router.get(
    "/activity_types",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="List activity types",
)
def list_master_activity_types(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _list_catalog(
        request, db,
        model=ActivityTypeModel,
        projector=_activity_type_to_response,
        self_href="/api/v3/master/activity_types",
        include_inactive=include_inactive,
    )


@router.get(
    "/activity_types/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="Get an activity type by code",
)
def get_master_activity_type(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _get_catalog_by_code(
        db, model=ActivityTypeModel,
        projector=_activity_type_to_response,
        code=code, kind="activity_type",
    )


@router.post(
    "/activity_types/create",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Create an activity type (admin)",
    status_code=201,
)
def create_master_activity_type(
    request: Request,
    data: ActivityTypeCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _create_catalog_row(
        db, model=ActivityTypeModel,
        projector=_activity_type_to_response,
        kind="activity_type",
        payload={
            "code": data.code,
            "label": data.label,
            "description": data.description,
            "active": data.active,
        },
    )


@router.patch(
    "/activity_types/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Update an activity type (admin)",
)
def update_master_activity_type(
    request: Request,
    code: str,
    data: ActivityTypeUpdateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _update_catalog_row(
        db, model=ActivityTypeModel,
        projector=_activity_type_to_response,
        kind="activity_type", code=code,
        payload={
            "label": data.label,
            "description": data.description,
            "active": data.active,
        },
    )


@router.delete(
    "/activity_types/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Soft-deactivate an activity type (admin)",
)
def delete_master_activity_type(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _set_active_catalog_row(
        db, model=ActivityTypeModel,
        projector=_activity_type_to_response,
        kind="activity_type", code=code, active=False,
    )


@router.post(
    "/activity_types/{code}/restore",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Restore a soft-disabled activity type (admin)",
)
def restore_master_activity_type(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _set_active_catalog_row(
        db, model=ActivityTypeModel,
        projector=_activity_type_to_response,
        kind="activity_type", code=code, active=True,
    )


# ---------- milestone_statuses ----------

@router.get(
    "/milestone_statuses",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="List milestone statuses",
)
def list_master_milestone_statuses(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _list_catalog(
        request, db,
        model=MilestoneStatusModel,
        projector=_milestone_status_to_response,
        self_href="/api/v3/master/milestone_statuses",
        include_inactive=include_inactive,
    )


@router.get(
    "/milestone_statuses/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="Get a milestone status by code",
)
def get_master_milestone_status(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _get_catalog_by_code(
        db, model=MilestoneStatusModel,
        projector=_milestone_status_to_response,
        code=code, kind="milestone_status",
    )


@router.post(
    "/milestone_statuses/create",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Create a milestone status (admin)",
    status_code=201,
)
def create_master_milestone_status(
    request: Request,
    data: MilestoneStatusCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _create_catalog_row(
        db, model=MilestoneStatusModel,
        projector=_milestone_status_to_response,
        kind="milestone_status",
        payload={
            "code": data.code,
            "label": data.label,
            "description": data.description,
            "active": data.active,
            "is_terminal": data.is_terminal,
        },
    )


@router.patch(
    "/milestone_statuses/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Update a milestone status (admin)",
)
def update_master_milestone_status(
    request: Request,
    code: str,
    data: MilestoneStatusUpdateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _update_catalog_row(
        db, model=MilestoneStatusModel,
        projector=_milestone_status_to_response,
        kind="milestone_status", code=code,
        payload={
            "label": data.label,
            "description": data.description,
            "active": data.active,
            "is_terminal": data.is_terminal,
        },
    )


@router.delete(
    "/milestone_statuses/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Soft-deactivate a milestone status (admin)",
)
def delete_master_milestone_status(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _set_active_catalog_row(
        db, model=MilestoneStatusModel,
        projector=_milestone_status_to_response,
        kind="milestone_status", code=code, active=False,
    )


@router.post(
    "/milestone_statuses/{code}/restore",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Restore a soft-disabled milestone status (admin)",
)
def restore_master_milestone_status(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _set_active_catalog_row(
        db, model=MilestoneStatusModel,
        projector=_milestone_status_to_response,
        kind="milestone_status", code=code, active=True,
    )


# ---------- activity_statuses ----------

@router.get(
    "/activity_statuses",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="List activity statuses",
)
def list_master_activity_statuses(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _list_catalog(
        request, db,
        model=ActivityStatusModel,
        projector=_activity_status_to_response,
        self_href="/api/v3/master/activity_statuses",
        include_inactive=include_inactive,
    )


@router.get(
    "/activity_statuses/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_VIEW)],
    summary="Get an activity status by code",
)
def get_master_activity_status(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _get_catalog_by_code(
        db, model=ActivityStatusModel,
        projector=_activity_status_to_response,
        code=code, kind="activity_status",
    )


@router.post(
    "/activity_statuses/create",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Create an activity status (admin)",
    status_code=201,
)
def create_master_activity_status(
    request: Request,
    data: ActivityStatusCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _create_catalog_row(
        db, model=ActivityStatusModel,
        projector=_activity_status_to_response,
        kind="activity_status",
        payload={
            "code": data.code,
            "label": data.label,
            "description": data.description,
            "active": data.active,
            "is_terminal": data.is_terminal,
        },
    )


@router.patch(
    "/activity_statuses/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Update an activity status (admin)",
)
def update_master_activity_status(
    request: Request,
    code: str,
    data: ActivityStatusUpdateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _update_catalog_row(
        db, model=ActivityStatusModel,
        projector=_activity_status_to_response,
        kind="activity_status", code=code,
        payload={
            "label": data.label,
            "description": data.description,
            "active": data.active,
            "is_terminal": data.is_terminal,
        },
    )


@router.delete(
    "/activity_statuses/{code}",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Soft-deactivate an activity status (admin)",
)
def delete_master_activity_status(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _set_active_catalog_row(
        db, model=ActivityStatusModel,
        projector=_activity_status_to_response,
        kind="activity_status", code=code, active=False,
    )


@router.post(
    "/activity_statuses/{code}/restore",
    dependencies=[require_permission(Permission.MASTER_DATA_MANAGE)],
    summary="Restore a soft-disabled activity status (admin)",
)
def restore_master_activity_status(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    return _set_active_catalog_row(
        db, model=ActivityStatusModel,
        projector=_activity_status_to_response,
        kind="activity_status", code=code, active=True,
    )
