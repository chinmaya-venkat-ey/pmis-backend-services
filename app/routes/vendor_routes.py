"""Vendor management routes for project-svc at /api/v3/vendors/*.

Project-svc mirrors the VM project service (port 8003) which serves vendor
CRUD without the /master/ prefix. The canonical write service is masters-svc;
project-svc exposes these for FE compatibility.

Endpoints:
  GET    /api/v3/vendors
  GET    /api/v3/vendors/{vendor_id}
  POST   /api/v3/vendors/create
  PATCH  /api/v3/vendors/{vendor_id}
  DELETE /api/v3/vendors/{vendor_id}
  POST   /api/v3/vendors/{vendor_id}/restore
  GET    /api/v3/vendors/{vendor_id}/users
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import require_authenticated
from app.db import get_db
from app.dependencies import get_current_user_id
from app.models._cross_schema import Role, User, UserRoleAssignment, Vendor
from app.models.project import Project
from app.models.project_vendor import ProjectVendor
from app.schemas.catalog import (
    UserSummary,
    VendorCreateRequest,
    VendorResponse,
    VendorUpdateRequest,
)
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


def _vendor_user_assignments(db: Session, vendor_id: str) -> List[Dict[str, Any]]:
    project_ids = [
        row[0] for row in db.execute(
            select(ProjectVendor.project_id).where(ProjectVendor.vendor_id == vendor_id)
        ).all()
    ]
    if not project_ids:
        return []

    stmt = (
        select(
            UserRoleAssignment.project_id,
            Role.name,
            UserRoleAssignment.user_id,
            User.login,
            User.first_name,
            User.last_name,
            User.email,
        )
        .join(Role, Role.id == UserRoleAssignment.role_id)
        .join(User, User.id == UserRoleAssignment.user_id)
        .where(UserRoleAssignment.project_id.in_(project_ids))
        .where(Role.name.in_(_PROJECT_TIER_ROLES))
        .where(User.deleted_at.is_(None))
    )

    grouped: Dict[tuple, Dict[str, Any]] = {}
    for pid, role_name, uid, login, first_name, last_name, email in db.execute(stmt).all():
        key = (pid, role_name)
        if key not in grouped:
            grouped[key] = {
                "project_id": pid,
                "role": _NAME_TO_LABEL.get(role_name, role_name),
                "user_ids": [],
                "users": [],
            }
        grouped[key]["user_ids"].append(uid)
        grouped[key]["users"].append({
            "id": uid,
            "login": login,
            "firstName": first_name or "",
            "lastName": last_name or "",
            "email": email or "",
        })

    return list(grouped.values())


def _build_vendor_response(db: Session, row: Vendor) -> VendorResponse:
    return VendorResponse.model_validate({
        "id": row.id,
        "vendor_code": row.vendor_code,
        "name": row.name,
        "description": row.description,
        "active": row.active,
        "email": row.email,
        "contact_person": row.contact_person,
        "phone_number": row.phone_number,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "deleted_at": row.deleted_at,
        "deleted_by": row.deleted_by,
        "projects": _vendor_projects(db, row.id),
        "user_assignments": _vendor_user_assignments(db, row.id),
    })


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
    db: Session, vendor_id: str, assignments: List[Dict[str, Any]], actor_id: Optional[str] = None
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
    response_model=List[VendorResponse],
    response_model_by_alias=True,
    summary="List vendors (organizations)",
    dependencies=[Depends(require_authenticated())],
)
def list_vendors(
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
) -> List[VendorResponse]:
    stmt = select(Vendor)
    if not include_inactive:
        stmt = stmt.where(Vendor.active.is_(True))
    rows = db.execute(stmt).scalars().all()
    return [_build_vendor_response(db, row) for row in rows]


@router.post(
    "/create",
    response_model=VendorResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Create a vendor (organization)",
    dependencies=[Depends(require_authenticated())],
    responses={409: {"description": "Vendor name already exists"}},
)
def create_vendor(
    payload: VendorCreateRequest,
    db: Session = Depends(get_db),
    caller_user_id: str = Depends(get_current_user_id),
) -> VendorResponse:
    existing = db.execute(
        select(Vendor).where(Vendor.name == payload.name)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Vendor name already exists")
    now = datetime.now(timezone.utc)
    row = Vendor(
        id=str(uuid.uuid4()),
        name=payload.name,
        description=payload.description,
        email=payload.email,
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
    return _build_vendor_response(db, row)


@router.get(
    "/{vendor_id}",
    response_model=VendorResponse,
    response_model_by_alias=True,
    summary="Get vendor details",
    dependencies=[Depends(require_authenticated())],
    responses={404: {"description": "Vendor not found"}},
)
def get_vendor(
    vendor_id: str,
    db: Session = Depends(get_db),
) -> VendorResponse:
    row = db.get(Vendor, vendor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return _build_vendor_response(db, row)


@router.patch(
    "/{vendor_id}",
    response_model=VendorResponse,
    response_model_by_alias=True,
    summary="Update a vendor",
    dependencies=[Depends(require_authenticated())],
    responses={404: {"description": "Vendor not found"}},
)
def update_vendor(
    vendor_id: str,
    payload: VendorUpdateRequest,
    db: Session = Depends(get_db),
    caller_user_id: str = Depends(get_current_user_id),
) -> VendorResponse:
    row = db.get(Vendor, vendor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Vendor not found")
    update_data = payload.model_dump(exclude_unset=True, exclude={"project_ids", "user_assignments"})
    for field, value in update_data.items():
        setattr(row, field, value)
    row.updated_at = datetime.now(timezone.utc)

    if payload.project_ids is not None:
        _apply_project_ids(db, vendor_id, payload.project_ids)

    if payload.user_assignments is not None:
        _apply_user_assignments(db, vendor_id, payload.user_assignments, actor_id=caller_user_id)

    db.commit()
    db.refresh(row)
    return _build_vendor_response(db, row)


@router.delete(
    "/{vendor_id}",
    response_model=VendorResponse,
    response_model_by_alias=True,
    summary="Delete (deactivate) a vendor",
    dependencies=[Depends(require_authenticated())],
    responses={404: {"description": "Vendor not found"}},
)
def delete_vendor(
    vendor_id: str,
    db: Session = Depends(get_db),
    caller_user_id: str = Depends(get_current_user_id),
) -> VendorResponse:
    row = db.get(Vendor, vendor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Vendor not found")
    now = datetime.now(timezone.utc)
    row.active = False
    row.deleted_at = now
    row.deleted_by = caller_user_id
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return _build_vendor_response(db, row)


@router.post(
    "/{vendor_id}/restore",
    response_model=VendorResponse,
    response_model_by_alias=True,
    summary="Restore a deleted vendor",
    dependencies=[Depends(require_authenticated())],
    responses={404: {"description": "Vendor not found"}},
)
def restore_vendor(
    vendor_id: str,
    db: Session = Depends(get_db),
) -> VendorResponse:
    row = db.get(Vendor, vendor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Vendor not found")
    row.active = True
    row.deleted_at = None
    row.deleted_by = None
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _build_vendor_response(db, row)


@router.get(
    "/{vendor_id}/users",
    summary="List users mapped to a vendor",
    dependencies=[Depends(require_authenticated())],
    responses={404: {"description": "Vendor not found"}},
)
def list_vendor_users(
    vendor_id: str,
    offset: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if not db.get(Vendor, vendor_id):
        raise HTTPException(status_code=404, detail="Vendor not found")

    stmt_direct = select(User).where(User.vendor_id == vendor_id)
    stmt_org = (
        select(User)
        .join(UserRoleAssignment, UserRoleAssignment.user_id == User.id)
        .where(UserRoleAssignment.organization_id == vendor_id)
    )
    if not include_deleted:
        stmt_direct = stmt_direct.where(User.deleted_at.is_(None))
        stmt_org = stmt_org.where(User.deleted_at.is_(None))

    seen: dict[str, User] = {}
    for u in db.execute(stmt_direct).scalars().all():
        seen[u.id] = u
    for u in db.execute(stmt_org).scalars().all():
        seen[u.id] = u

    rows = sorted(seen.values(), key=lambda u: u.login)
    total = len(rows)
    zero_based = max(0, offset - 1)
    page = rows[zero_based * page_size : zero_based * page_size + page_size]
    return {
        "items": [UserSummary.model_validate(u) for u in page],
        "total": total,
        "offset": offset,
        "pageSize": page_size,
    }
