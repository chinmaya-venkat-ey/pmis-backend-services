"""Vendor catalog routes (LEGACY — superseded by doc 20).

- GET    /api/v3/vendors                   : list live vendors (newest first,
                                             each with its mapped projects)
- POST   /api/v3/vendors/create            : create a vendor (admin)
- PATCH  /api/v3/vendors/{id}              : edit a vendor (admin)
- DELETE /api/v3/vendors/{id}              : soft-delete a vendor (admin)
- POST   /api/v3/vendors/{id}/restore      : undelete a vendor (admin)
- GET    /api/v3/vendors/{id}/projects     : projects mapped to this vendor,
                                             excluding closed/completed

All six endpoints continue to work but each stamps a ``Deprecation: true``
header pointing at the corresponding ``/api/v3/master/vendors/*``
successor. The new master-data router (doc 20) delegates back into the
handlers in this file so behaviour is identical — only the URL surface
and RBAC permission change.
"""
from typing import Any, Dict, Iterable, List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.dependencies import get_current_user_id
from ....core.errors import AlreadyExistsError, NotFoundError
from ....core.middleware.rbac import require_permission
from ....core.rbac import Permission
from ....infrastructure.db.models.project import ProjectModel
from ....infrastructure.db.models.project_vendor import ProjectVendorModel
from ....infrastructure.db.repositories.vendor_repository import VendorRepository
from ....infrastructure.db.session import get_db
from .schemas import VendorCreateRequest, VendorUpdateRequest


router = APIRouter(prefix="/vendors", tags=["vendors"])


# Statuses that mean "this project is no longer interesting on a vendor's
# project list". Mirrors the lifecycle in projects.services.transitions.
# `closed` is the terminal status today; if/when a `completed` status is
# added, append it here.
_HIDDEN_PROJECT_STATUSES = {"closed", "completed"}


def _vendor_to_response(v, projects: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    d = v.to_dict()
    return {
        "_type": "Vendor",
        "id": d["id"],
        # Doc 25: human-readable identifier (e.g. ``VN-ACME-260502143015``).
        # Always emitted; ``None`` on legacy rows that pre-date the
        # backfill (none in production after the doc-25 migration).
        "vendorCode": d.get("vendor_code"),
        "name": d["name"],
        "description": d.get("description"),
        "active": d.get("active", True),
        # Contact details (doc 18). NULL on vendors created before this
        # batch — FE renders empty cells in that case.
        "email": d.get("email"),
        "contactPerson": d.get("contact_person"),
        "phoneNumber": d.get("phone_number"),
        "createdAt": d.get("created_at"),
        "updatedAt": d.get("updated_at"),
        "deletedAt": d.get("deleted_at"),
        # Projects this vendor is mapped to. Excludes closed/completed and
        # soft-deleted projects (same rule as GET /vendors/{id}/projects).
        # Empty list when the vendor has no live mappings — never null, so
        # the FE can iterate unconditionally.
        "projects": projects if projects is not None else [],
    }


def _project_entry(*, id, project_code, name, status, created_at) -> Dict[str, Any]:
    """Single source of truth for the per-project shape returned by every
    vendor endpoint. Used by both ``_projects_by_vendor`` (the embedded
    array on /vendors and /vendors/{id}) and the dedicated
    /vendors/{id}/projects endpoint, so all three return identical entries.

    Doc 33: ``isVersion`` / ``versionOf`` were removed from this shape
    along with the versioning feature.
    """
    return {
        "_type": "Project",
        "id": id,
        "projectCode": project_code,
        "name": name,
        "status": status,
        "createdAt": created_at.isoformat() if created_at else None,
    }


def _validate_assignable_project_ids(
    db: Session, project_ids: List[str],
) -> List[str]:
    """De-dupe + validate project ids before mapping them to a vendor.

    A project is assignable when:
      - it exists,
      - it is not soft-deleted,
      - its status is not in ``_HIDDEN_PROJECT_STATUSES`` (closed / completed).

    Raises ``ValidationError`` listing the offending ids on first failure;
    returns the unique, ordered list on success.
    """
    from ....core.errors import ValidationError
    if not project_ids:
        return []
    unique = list(dict.fromkeys(project_ids))
    rows = (
        db.query(ProjectModel.id, ProjectModel.status, ProjectModel.deleted_at)
        .filter(ProjectModel.id.in_(unique))
        .all()
    )
    # Map id → (status, deleted_at). Missing rows fall through to the
    # `missing` check below.
    by_id = {pid: (status, deleted_at) for (pid, status, deleted_at) in rows}

    missing = [pid for pid in unique if pid not in by_id]
    if missing:
        raise ValidationError(
            f"Unknown project(s): {', '.join(missing)}",
        )
    deleted = [pid for pid in unique if by_id[pid][1] is not None]
    if deleted:
        raise ValidationError(
            f"Project(s) are soft-deleted and cannot be assigned to a "
            f"vendor: {', '.join(deleted)}",
        )
    bad_status = [
        pid for pid in unique
        if by_id[pid][0] in _HIDDEN_PROJECT_STATUSES
    ]
    if bad_status:
        raise ValidationError(
            f"Project(s) are closed/completed and cannot be assigned to "
            f"a vendor: {', '.join(bad_status)}",
        )
    return unique


def _projects_by_vendor(
    db: Session, vendor_ids: Iterable[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Return ``{vendor_id: [project_entry, ...]}`` for the given vendors.

    One batched query — no N+1. Filters out closed/completed and
    soft-deleted projects so the response matches the rule used by
    GET /vendors/{id}/projects. Each entry uses ``_project_entry`` so
    the embedded shape matches the dedicated endpoint exactly.
    """
    vendor_ids = list(vendor_ids)
    if not vendor_ids:
        return {}
    rows = (
        db.query(
            ProjectVendorModel.vendor_id,
            ProjectModel.id,
            ProjectModel.project_code,
            ProjectModel.name,
            ProjectModel.status,
            ProjectModel.created_at,
        )
        .join(ProjectModel, ProjectModel.id == ProjectVendorModel.project_id)
        .filter(ProjectVendorModel.vendor_id.in_(vendor_ids))
        .filter(ProjectModel.deleted_at.is_(None))
        .filter(~ProjectModel.status.in_(_HIDDEN_PROJECT_STATUSES))
        .order_by(ProjectModel.created_at.desc(), ProjectModel.id.desc())
        .all()
    )
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for (vendor_id, project_id, project_code, project_name,
         status, created_at) in rows:
        grouped.setdefault(vendor_id, []).append(_project_entry(
            id=project_id,
            project_code=project_code,
            name=project_name,
            status=status,
            created_at=created_at,
        ))
    return grouped


@router.get(
    "",
    dependencies=[require_permission(Permission.VENDORS_READ)],
    summary="List live vendors (newest first)",
    description=(
        "Returns vendors that are not soft-deleted, ordered by createdAt "
        "descending so the latest vendor is row 0 in Search Vendor."
    ),
)
def list_vendors(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    repo = VendorRepository(db)
    vendors = repo.list_active()
    projects_by_vendor = _projects_by_vendor(db, (v.id for v in vendors))
    items = [
        _vendor_to_response(v, projects_by_vendor.get(v.id, []))
        for v in vendors
    ]
    return BaseController.stamp_deprecation(
        BaseController.ok(data={
            "_type": "Collection",
            "total": len(items),
            "count": len(items),
            "_embedded": {"elements": items},
        }),
        successor_path="/api/v3/master/vendors",
    )


@router.get(
    "/{vendor_id}",
    dependencies=[require_permission(Permission.VENDORS_READ)],
    summary="Get vendor detail (with mapped projects)",
    description=(
        "Returns full vendor detail — name, description, email, contact "
        "person, phone number, soft-delete metadata — plus the list of "
        "projects this vendor is mapped to (closed/completed/soft-deleted "
        "projects filtered out, same rule as GET /vendors). 404 on "
        "soft-deleted vendors; admins can see them by hitting "
        "GET /vendors/{id}/projects (which already accepts deleted vendors)."
    ),
)
def get_vendor(
    request: Request,
    vendor_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Path param accepts either a UUID or a vendor code (e.g.
    ``VN-ACME-260502143015``) per doc 25 — the repo dispatches based
    on the literal ``VN-`` prefix."""
    repo = VendorRepository(db)
    vendor = repo.get_by_id_or_code(vendor_id)
    if vendor is None:
        raise NotFoundError("Vendor not found.")
    projects = _projects_by_vendor(db, [vendor.id]).get(vendor.id, [])
    return BaseController.stamp_deprecation(
        BaseController.ok(data=_vendor_to_response(vendor, projects)),
        successor_path=f"/api/v3/master/vendors/{vendor.id}",
    )


@router.post(
    "/create",
    dependencies=[require_permission(Permission.VENDORS_MANAGE)],
    summary="Create a vendor (admin)",
    status_code=201,
)
def create_vendor(
    request: Request,
    data: VendorCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = VendorRepository(db)
    # Name uniqueness check spans soft-deleted rows too — name has a DB-level
    # UNIQUE constraint regardless of deletion state. If a soft-deleted vendor
    # has the same name, restore it instead of creating a duplicate.
    if repo.get_by_name(data.name, include_deleted=True) is not None:
        raise AlreadyExistsError(
            f"A vendor named '{data.name}' already exists "
            "(it may be soft-deleted; restore it via POST /vendors/{id}/restore)."
        )
    # Validate projectIds BEFORE inserting the vendor row so we don't
    # leave a half-committed vendor when an id is bad. ValidationError
    # bubbles up to a 422.
    project_ids = _validate_assignable_project_ids(db, data.projectIds or [])
    vendor = repo.create(
        name=data.name,
        description=data.description,
        active=data.active,
        email=str(data.email) if data.email else None,
        contact_person=data.contactPerson,
        phone_number=data.phoneNumber,
    )
    if project_ids:
        repo.set_vendor_projects(vendor.id, project_ids)
    db.commit()
    projects = _projects_by_vendor(db, [vendor.id]).get(vendor.id, [])
    return BaseController.stamp_deprecation(
        BaseController.created(data=_vendor_to_response(vendor, projects)),
        successor_path="/api/v3/master/vendors/create",
    )


@router.patch(
    "/{vendor_id}",
    dependencies=[require_permission(Permission.VENDORS_MANAGE)],
    summary="Update a vendor (admin)",
)
def update_vendor(
    request: Request,
    vendor_id: str,
    data: VendorUpdateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Path param accepts UUID or ``VN-...`` code (doc 25)."""
    repo = VendorRepository(db)
    m = repo.get_model_by_id_or_code(vendor_id)
    if m is None:
        raise NotFoundError("Vendor not found.")
    # If projectIds is supplied, validate BEFORE applying any field changes
    # so a bad id doesn't leave the row half-updated. None means "leave the
    # mapping unchanged"; [] clears it; non-empty list replaces it.
    will_replace_projects = data.projectIds is not None
    project_ids: List[str] = []
    if will_replace_projects:
        project_ids = _validate_assignable_project_ids(db, data.projectIds or [])

    if data.name is not None:
        m.name = data.name
    if data.description is not None:
        m.description = data.description
    if data.active is not None:
        m.active = data.active
    if data.email is not None:
        m.email = str(data.email)
    if data.contactPerson is not None:
        m.contact_person = data.contactPerson
    if data.phoneNumber is not None:
        m.phone_number = data.phoneNumber
    db.flush()
    if will_replace_projects:
        repo.set_vendor_projects(m.id, project_ids)
    db.commit()
    from ....domain.vendors.vendor import Vendor
    domain = Vendor(
        id=m.id, name=m.name, description=m.description, active=bool(m.active),
        created_at=m.created_at, updated_at=m.updated_at,
        deleted_at=m.deleted_at, deleted_by=m.deleted_by,
        email=m.email, contact_person=m.contact_person,
        phone_number=m.phone_number,
    )
    projects = _projects_by_vendor(db, [domain.id]).get(domain.id, [])
    return BaseController.stamp_deprecation(
        BaseController.ok(data=_vendor_to_response(domain, projects)),
        successor_path=f"/api/v3/master/vendors/{domain.id}",
    )


@router.delete(
    "/{vendor_id}",
    dependencies=[require_permission(Permission.VENDORS_MANAGE)],
    summary="Soft-delete a vendor (admin)",
    description=(
        "Marks the vendor as deleted (stamps deletedAt, flips active=False). "
        "The vendor disappears from GET /vendors and from picker validation, "
        "but its project_vendors / milestone_vendors mapping rows are kept "
        "so a later restore brings the associations back."
    ),
)
def delete_vendor(
    request: Request,
    vendor_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Path param accepts UUID or ``VN-...`` code (doc 25)."""
    repo = VendorRepository(db)
    actor_id = get_current_user_id(request)
    # Use include_deleted=False so a double-delete returns 404 rather than a
    # silent no-op — clearer signal to the FE.
    m = repo.get_model_by_id_or_code(vendor_id)
    if m is None:
        raise NotFoundError("Vendor not found or already deleted.")
    # Always pass the canonical UUID downstream — repo.soft_delete keys
    # on the PK, not on vendor_code.
    repo.soft_delete(m.id, actor_id=actor_id)
    db.commit()
    return BaseController.stamp_deprecation(
        BaseController.no_content(),
        successor_path=f"/api/v3/master/vendors/{m.id}",
    )


@router.post(
    "/{vendor_id}/restore",
    dependencies=[require_permission(Permission.VENDORS_MANAGE)],
    summary="Restore a soft-deleted vendor (admin)",
    description=(
        "Clears deletedAt and flips active=True. All previously-existing "
        "project / milestone associations are preserved on disk and re-surface "
        "automatically. Note: the vendor's projects list (GET "
        "/vendors/{id}/projects) filters out closed/completed projects."
    ),
)
def restore_vendor(
    request: Request,
    vendor_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Path param accepts UUID or ``VN-...`` code (doc 25)."""
    repo = VendorRepository(db)
    m = repo.get_model_by_id_or_code(vendor_id, include_deleted=True)
    if m is None:
        raise NotFoundError("Vendor not found.")
    canonical_id = m.id  # use UUID for downstream repo calls + successor URL
    successor = f"/api/v3/master/vendors/{canonical_id}/restore"
    if m.deleted_at is None:
        # Already live — return the current snapshot so the call is idempotent
        # rather than 409'ing a benign retry.
        live = repo.get_by_id(canonical_id)
        projects = _projects_by_vendor(db, [canonical_id]).get(canonical_id, [])
        return BaseController.stamp_deprecation(
            BaseController.ok(data=_vendor_to_response(live, projects)),
            successor_path=successor,
        )
    restored = repo.restore(canonical_id)
    db.commit()
    projects = _projects_by_vendor(db, [canonical_id]).get(canonical_id, [])
    return BaseController.stamp_deprecation(
        BaseController.ok(data=_vendor_to_response(restored, projects)),
        successor_path=successor,
    )


@router.get(
    "/{vendor_id}/projects",
    dependencies=[require_permission(Permission.VENDORS_READ)],
    summary="List projects mapped to this vendor (excluding closed/completed)",
    description=(
        "Returns the live, non-deleted, non-closed projects associated with "
        "this vendor. Closed/completed projects are filtered out — they're "
        "preserved on disk but no longer presented in the vendor's project "
        "list per product rule."
    ),
)
def list_vendor_projects(
    request: Request,
    vendor_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Path param accepts UUID or ``VN-...`` code (doc 25)."""
    repo = VendorRepository(db)
    vendor = repo.get_by_id_or_code(vendor_id, include_deleted=True)
    if vendor is None:
        raise NotFoundError("Vendor not found.")
    canonical_id = vendor.id
    # Reuse the batched helper so this endpoint and the embedded
    # projects array on /vendors and /vendors/{id} return identical
    # entries (same fields, same filter, same order).
    items = _projects_by_vendor(db, [canonical_id]).get(canonical_id, [])
    return BaseController.stamp_deprecation(
        BaseController.ok(data={
            "_type": "Collection",
            "total": len(items),
            "count": len(items),
            "_embedded": {"elements": items},
        }),
        successor_path="/api/v3/master/vendors",
    )
