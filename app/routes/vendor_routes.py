"""Vendor management routes for project-svc at /api/v3/vendors/*.

Project-svc mirrors the VM project service (port 8003) which serves vendor
CRUD without the /master/ prefix. The canonical write service is masters-svc;
project-svc exposes these for FE compatibility.

Response shapes:
  List / projects  → {_type:"Collection", total, count, _embedded:{elements:[...]}}
  Single vendor    → {_type:"Vendor", id, vendorCode, name, ..., projects:[...]}
  Delete           → null data (no-content equivalent)
  Users            → [{id, login, email, ...}]

All responses are wrapped in the PMIS envelope by HalApiRoute:
  {data: <above>, message: null, error: null, status: 200}
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.permissions import VENDORS_MANAGE, VENDORS_READ
from app.core.rbac import require_permission
from app.core.response import api_response

_VENDOR_NOT_FOUND = "Vendor not found."
from app.db import get_db
from app.dependencies import get_current_user_id
from app.models._cross_schema import Role, User, UserRoleAssignment, Vendor
from app.models.project import Project
from app.models.project_vendor import ProjectVendor
from app.schemas.catalog import VendorCreateRequest, VendorUpdateRequest
from app.utilities.code_generators import generate_vendor_code
from app.utilities.timezones import IST


router = APIRouter(prefix="/vendors", tags=["vendors"])

_PROJECT_TIER_ROLES = ("project_admin", "project_member", "division_member")

_NAME_TO_LABEL: Dict[str, str] = {
    "project_admin": "Project Admin",
    "project_member": "Project Member",
    "division_member": "Division Member",
}
_LABEL_TO_NAME: Dict[str, str] = {
    "project admin": "project_admin",
    "project_admin": "project_admin",
    "project member": "project_member",
    "project_member": "project_member",
    "division member": "division_member",
    "division_member": "division_member",
}


def _iso_ist(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat()


def _vendor_projects(db: Session, vendor_id: str) -> List[Dict[str, Any]]:
    stmt = (
        select(Project.id, Project.project_code, Project.name, Project.status, Project.created_at)
        .join(ProjectVendor, ProjectVendor.project_id == Project.id)
        .where(ProjectVendor.vendor_id == vendor_id)
        .where(Project.deleted_at.is_(None))
        .where(Project.status.not_in(["closed", "completed"]))
        .order_by(Project.created_at.desc(), Project.id.desc())
    )
    return [
        {
            "_type": "Project",
            "id": pid,
            "projectCode": pcode,
            "name": pname,
            "status": pstatus,
            "createdAt": _iso_ist(pcreated),
        }
        for pid, pcode, pname, pstatus, pcreated in db.execute(stmt).all()
    ]


def _vendor_assignments(db: Session, vendor_id: str) -> List[Dict[str, Any]]:
    """Return flat list of {project_id, role, user_ids} for all projects of
    this vendor. Powers the FE's Project Mapping role table seeding (Bug #8).
    Each project always has an entry for project_admin and project_member even
    if the list is empty — so the FE can build its filter correctly."""
    project_ids = [
        row[0] for row in db.execute(
            select(ProjectVendor.project_id).where(ProjectVendor.vendor_id == vendor_id)
        ).all()
    ]
    if not project_ids:
        return []

    rows = db.execute(
        select(UserRoleAssignment.project_id, Role.name, UserRoleAssignment.user_id)
        .join(Role, Role.id == UserRoleAssignment.role_id)
        .where(UserRoleAssignment.project_id.in_(project_ids))
        .where(Role.name.in_(_PROJECT_TIER_ROLES))
    ).all()

    grouped: Dict[tuple, List[str]] = defaultdict(list)
    for pid, role_name, uid in rows:
        grouped[(pid, role_name)].append(uid)

    out = []
    for pid in project_ids:
        for role_name in ("project_admin", "project_member", "division_member"):
            out.append({
                "project_id": pid,
                "role": role_name,
                "user_ids": grouped.get((pid, role_name), []),
            })
    return out


def _vendor_dict(db: Session, row: Vendor) -> Dict[str, Any]:
    """Build a vendor entry in the monolith wire shape (camelCase, _type discriminator)."""
    return {
        "_type": "Vendor",
        "id": row.id,
        "vendorCode": row.vendor_code,
        "name": row.name,
        "description": row.description,
        "active": row.active,
        "email": row.email,
        "contactPerson": row.contact_person,
        "phoneNumber": row.phone_number,
        "createdAt": _iso_ist(row.created_at),
        "updatedAt": _iso_ist(row.updated_at),
        "deletedAt": _iso_ist(row.deleted_at),
        "projects": _vendor_projects(db, row.id),
        "user_assignments": _vendor_assignments(db, row.id),
    }


def _collection(items: List[Any]) -> Dict[str, Any]:
    """Build a PMIS Collection envelope.

    _bare=True signals HalApiRoute to skip HAL resource-wrapping and
    return the dict as-is (after camelizing), matching the monolith shape:
    {_type:"Collection", total, count, _embedded:{elements:[...]}}.
    """
    return {
        "_bare": True,
        "_type": "Collection",
        "total": len(items),
        "count": len(items),
        "_embedded": {"elements": items},
    }


def _apply_project_ids(db: Session, vendor_id: str, project_ids: List[str]) -> None:
    existing = db.execute(
        select(ProjectVendor).where(ProjectVendor.vendor_id == vendor_id)
    ).scalars().all()
    for pv in existing:
        db.delete(pv)
    db.flush()
    seen: set = set()
    now = datetime.now(timezone.utc)
    for pid in project_ids:
        if pid in seen:
            continue
        seen.add(pid)
        db.add(ProjectVendor(project_id=pid, vendor_id=vendor_id, created_at=now))


def _apply_user_assignments(
    db: Session,
    vendor_id: str,
    assignments: List[Dict[str, Any]],
    actor_id: Optional[str] = None,  # NOSONAR(S1172): reserved for future audit-log instrumentation; caller already passes it
) -> None:
    if not assignments:
        return
    project_ids = {
        row[0] for row in db.execute(
            select(ProjectVendor.project_id).where(ProjectVendor.vendor_id == vendor_id)
        ).all()
    }
    for entry in assignments:
        pid = entry.get("project_id") or entry.get("projectId")
        raw_role = entry.get("role", "")
        role_name = _LABEL_TO_NAME.get(str(raw_role).strip().lower(), raw_role)
        desired_user_ids = list(entry.get("user_ids") or entry.get("userIds") or [])

        if pid not in project_ids or role_name not in _PROJECT_TIER_ROLES:
            continue

        role_row = db.execute(select(Role).where(Role.name == role_name)).scalars().first()
        if role_row is None:
            continue

        current = {
            r.user_id: r for r in db.execute(
                select(UserRoleAssignment)
                .where(UserRoleAssignment.project_id == pid)
                .where(UserRoleAssignment.role_id == role_row.id)
            ).scalars().all()
        }
        desired_set = set(desired_user_ids)
        for uid in desired_user_ids:
            if uid not in current:
                db.add(UserRoleAssignment(user_id=uid, role_id=role_row.id, project_id=pid))
        for uid, ra in current.items():
            if uid not in desired_set:
                db.delete(ra)
    db.flush()


@router.get(
    "",
    summary="List vendors (newest first)",
    description=(
        "Returns vendors that are not soft-deleted, ordered by createdAt "
        "descending. Active and inactive vendors are returned by default. "
        "Pass active_only=true (picker dropdowns) to show only active. "
        "Requires vendors:read."
    ),
    dependencies=[Depends(require_permission(VENDORS_READ))],
)
def list_vendors(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    active_only: Annotated[bool, Query(
        description="When true, return only active vendors. Default false shows all (active + inactive).",
    )] = False,
) -> Dict[str, Any]:
    is_admin = getattr(request.state, "is_admin", False)
    caller_vendor_id = getattr(request.state, "user_vendor_id", None)
    # Admins see all vendors; vendor-users see only their own vendor.
    vendor_id_filter = None if is_admin else caller_vendor_id

    stmt = select(Vendor).where(Vendor.deleted_at.is_(None))
    if active_only:
        stmt = stmt.where(Vendor.active.is_(True))
    if vendor_id_filter is not None:
        stmt = stmt.where(Vendor.id == vendor_id_filter)
    stmt = stmt.order_by(Vendor.created_at.desc())
    rows = db.execute(stmt).scalars().all()
    return _collection([_vendor_dict(db, row) for row in rows])


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a vendor",
    description=(
        "Creates a new vendor. name must be unique. phoneNumber is required. "
        "Requires vendors:manage."
    ),
    dependencies=[Depends(require_permission(VENDORS_MANAGE))],
    responses={409: {"description": "Vendor name already exists"}},
)
def create_vendor(
    payload: VendorCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
) -> Dict[str, Any]:
    existing = db.execute(
        select(Vendor).where(Vendor.name == payload.name).where(Vendor.deleted_at.is_(None))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Vendor name already exists")
    now = datetime.now(timezone.utc)
    row = Vendor(
        id=str(uuid.uuid4()),
        vendor_code=generate_vendor_code(payload.name),
        name=payload.name,
        description=payload.description,
        email=str(payload.email) if payload.email else None,
        contact_person=payload.contact_person,
        phone_number=payload.phone_number,
        active=payload.active,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    if payload.project_ids:
        _apply_project_ids(db, row.id, payload.project_ids)
    db.commit()
    db.refresh(row)
    return {"_bare": True, **_vendor_dict(db, row)}


@router.get(
    "/{vendor_id}",
    summary="Get vendor details",
    description="Returns one vendor by UUID with embedded projects. 404 if not found. Requires vendors:read.",
    dependencies=[Depends(require_permission(VENDORS_READ))],
    responses={404: {"description": _VENDOR_NOT_FOUND}},
)
def get_vendor(
    vendor_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Dict[str, Any]:
    row = db.get(Vendor, vendor_id)
    if not row:
        raise HTTPException(status_code=404, detail=_VENDOR_NOT_FOUND)
    return {"_bare": True, **_vendor_dict(db, row)}


@router.patch(
    "/{vendor_id}",
    summary="Update a vendor",
    description=(
        "Partial update. name is unique — collision returns 409. "
        "projectIds: null = leave mappings unchanged, [] = clear all, "
        "non-empty list = replace. Requires vendors:manage."
    ),
    dependencies=[Depends(require_permission(VENDORS_MANAGE))],
    responses={
        404: {"description": _VENDOR_NOT_FOUND},
        409: {"description": "Vendor name already in use"},
    },
)
def update_vendor(
    vendor_id: str,
    payload: VendorUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
) -> Dict[str, Any]:
    row = db.get(Vendor, vendor_id)
    if not row:
        raise HTTPException(status_code=404, detail=_VENDOR_NOT_FOUND)
    update_data = payload.model_dump(exclude_unset=True, exclude={"project_ids", "user_assignments"})
    if "name" in update_data and update_data["name"] != row.name:
        clash = db.execute(
            select(Vendor)
            .where(Vendor.name == update_data["name"])
            .where(Vendor.deleted_at.is_(None))
            .where(Vendor.id != vendor_id)
        ).scalar_one_or_none()
        if clash:
            raise HTTPException(status_code=409, detail="Vendor name already in use")
    if "email" in update_data and update_data["email"] is not None:
        update_data["email"] = str(update_data["email"])
    for field, value in update_data.items():
        setattr(row, field, value)
    row.updated_at = datetime.now(timezone.utc)

    if payload.project_ids is not None:
        _apply_project_ids(db, vendor_id, payload.project_ids)

    if payload.user_assignments is not None:
        _apply_user_assignments(db, vendor_id, payload.user_assignments, actor_id=caller_user_id)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Vendor name already in use")
    db.refresh(row)
    return {"_bare": True, **_vendor_dict(db, row)}


@router.delete(
    "/{vendor_id}",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete a vendor",
    description=(
        "Marks the vendor deleted (stamps deletedAt, flips active=False). "
        "Project mappings are preserved for restore. Requires vendors:manage."
    ),
    dependencies=[Depends(require_permission(VENDORS_MANAGE))],
    responses={404: {"description": _VENDOR_NOT_FOUND}},
)
def delete_vendor(
    vendor_id: str,
    db: Annotated[Session, Depends(get_db)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
) -> None:
    row = db.get(Vendor, vendor_id)
    if not row:
        raise HTTPException(status_code=404, detail=_VENDOR_NOT_FOUND)
    now = datetime.now(timezone.utc)
    row.active = False
    row.deleted_at = now
    row.deleted_by = caller_user_id
    row.updated_at = now
    db.commit()


@router.post(
    "/{vendor_id}/restore",
    summary="Restore a soft-deleted vendor",
    description=(
        "Clears deletedAt + deletedBy and flips active=True. "
        "Requires vendors:manage."
    ),
    dependencies=[Depends(require_permission(VENDORS_MANAGE))],
    responses={404: {"description": _VENDOR_NOT_FOUND}},
)
def restore_vendor(
    vendor_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Dict[str, Any]:
    row = db.get(Vendor, vendor_id)
    if not row:
        raise HTTPException(status_code=404, detail=_VENDOR_NOT_FOUND)
    row.active = True
    row.deleted_at = None
    row.deleted_by = None
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return {"_bare": True, **_vendor_dict(db, row)}


@router.get(
    "/{vendor_id}/users",
    summary="List users belonging to this vendor",
    description=(
        "Returns all active (non-deleted) users whose vendor_id matches the given "
        "vendor UUID or who have an organization_id role assignment for this vendor. "
        "Requires vendors:read."
    ),
    dependencies=[Depends(require_permission(VENDORS_READ))],
    responses={404: {"description": _VENDOR_NOT_FOUND}},
)
def list_vendor_users(
    vendor_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Any:
    if not db.get(Vendor, vendor_id):
        raise HTTPException(status_code=404, detail=_VENDOR_NOT_FOUND)

    stmt_direct = (
        select(User)
        .where(User.vendor_id == vendor_id)
        .where(User.deleted_at.is_(None))
    )
    stmt_org = (
        select(User)
        .join(UserRoleAssignment, UserRoleAssignment.user_id == User.id)
        .where(UserRoleAssignment.organization_id == vendor_id)
        .where(User.deleted_at.is_(None))
    )

    seen: dict[str, User] = {}
    for u in db.execute(stmt_direct).scalars().all():
        seen[u.id] = u
    for u in db.execute(stmt_org).scalars().all():
        seen[u.id] = u

    rows = sorted(seen.values(), key=lambda u: u.login)
    users = [
        {
            "id": u.id,
            "login": u.login,
            "email": u.email,
            "firstName": u.first_name or "",
            "lastName": u.last_name or "",
            "status": u.status,
        }
        for u in rows
    ]
    return api_response(data=users)
