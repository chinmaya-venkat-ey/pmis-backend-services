"""Data access for the vendors catalog. Soft-delete via deleted_at/deleted_by."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import Project, ProjectVendor, User
from app.models.vendor import Vendor


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VendorRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, vendor_id: str) -> Optional[Vendor]:
        return self.db.get(Vendor, vendor_id)

    def get_by_name(self, name: str) -> Optional[Vendor]:
        stmt = select(Vendor).where(Vendor.name == name, Vendor.deleted_at.is_(None))
        return self.db.execute(stmt).scalars().first()

    def get_by_vendor_code(self, vendor_code: str) -> Optional[Vendor]:
        stmt = select(Vendor).where(Vendor.vendor_code == vendor_code)
        return self.db.execute(stmt).scalars().first()

    def list_(
        self,
        *,
        include_inactive: bool = False,
        include_deleted: bool = False,
        vendor_id_filter: Optional[str] = None,
    ) -> List[Vendor]:
        """List vendors. `vendor_id_filter` is an optional row-level scope hook —
        services pass the caller's own vendor_id when the user isn't admin."""
        stmt = select(Vendor)
        if not include_deleted:
            stmt = stmt.where(Vendor.deleted_at.is_(None))
        if not include_inactive:
            stmt = stmt.where(Vendor.active.is_(True))
        if vendor_id_filter is not None:
            stmt = stmt.where(Vendor.id == vendor_id_filter)
        stmt = stmt.order_by(Vendor.name.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> Vendor:
        row = Vendor(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Vendor, **kwargs) -> Vendor:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def soft_delete(self, row: Vendor, *, deleted_by_user_id: str) -> Vendor:
        row.deleted_at = _utcnow()
        row.deleted_by = deleted_by_user_id
        row.active = False
        self.db.flush()
        return row

    def restore(self, row: Vendor) -> Vendor:
        row.deleted_at = None
        row.deleted_by = None
        row.active = True
        self.db.flush()
        return row

    def list_projects_for_vendor(self, vendor_id: str) -> List[Project]:
        """Cross-schema: masters.vendors → project.project_vendors → project.projects.
        Read-only — masters-svc never writes to project.*"""
        stmt = (
            select(Project)
            .join(ProjectVendor, ProjectVendor.project_id == Project.id)
            .where(ProjectVendor.vendor_id == vendor_id)
            .where(Project.deleted_at.is_(None))
            .order_by(Project.name.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_users_for_vendor(self, vendor_id: str) -> List[User]:
        """Cross-schema: users.users where vendor_id = vendor_id.
        Read-only — masters-svc never writes to users.*"""
        stmt = (
            select(User)
            .where(User.vendor_id == vendor_id)
            .where(User.deleted_at.is_(None))
            .order_by(User.login.asc())
        )
        return list(self.db.execute(stmt).scalars().all())
