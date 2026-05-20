"""Data access for the vendors catalog. Soft-delete via deleted_at/deleted_by."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import Project, ProjectVendor, User
from app.models.vendor import Vendor

_HIDDEN_STATUSES = {"closed", "completed"}


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
        active_only: bool = False,
        vendor_id_filter: Optional[str] = None,
    ) -> List[Vendor]:
        """List vendors ordered by created_at DESC (newest first, matches monolith).

        active_only=False (default): return both active and inactive vendors,
        excluding soft-deleted rows — same as monolith GET /vendors default.
        active_only=True: only active vendors (picker dropdown behaviour).
        Soft-deleted rows are always excluded.
        """
        stmt = select(Vendor).where(Vendor.deleted_at.is_(None))
        if active_only:
            stmt = stmt.where(Vendor.active.is_(True))
        if vendor_id_filter is not None:
            stmt = stmt.where(Vendor.id == vendor_id_filter)
        stmt = stmt.order_by(Vendor.created_at.desc())
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
        """Projects for a single vendor — excludes soft-deleted and closed/completed."""
        stmt = (
            select(Project)
            .join(ProjectVendor, ProjectVendor.project_id == Project.id)
            .where(ProjectVendor.vendor_id == vendor_id)
            .where(Project.deleted_at.is_(None))
            .where(Project.status.notin_(_HIDDEN_STATUSES))
            .order_by(Project.created_at.desc(), Project.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_projects_for_vendors_batch(
        self, vendor_ids: List[str]
    ) -> Dict[str, List[Project]]:
        """Batched project load for multiple vendors — no N+1 on list endpoint."""
        if not vendor_ids:
            return {}
        stmt = (
            select(ProjectVendor.vendor_id, Project)
            .join(Project, Project.id == ProjectVendor.project_id)
            .where(ProjectVendor.vendor_id.in_(vendor_ids))
            .where(Project.deleted_at.is_(None))
            .where(Project.status.notin_(_HIDDEN_STATUSES))
            .order_by(Project.created_at.desc(), Project.id.desc())
        )
        grouped: Dict[str, List[Project]] = {}
        for vid, project in self.db.execute(stmt).all():
            grouped.setdefault(vid, []).append(project)
        return grouped

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
