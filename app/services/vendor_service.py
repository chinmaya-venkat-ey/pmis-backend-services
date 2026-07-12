"""Business logic for the vendors catalog."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import CatalogEntryConflictError, CatalogEntryNotFoundError
from app.models._cross_schema import Project, ProjectVendor
from app.models.vendor import Vendor
from app.repositories.vendor_repository import VendorRepository
from app.schemas.vendor import VendorCreateRequest, VendorUpdateRequest
from app.utilities.code_generators import generate_vendor_code


class VendorService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = VendorRepository(db)

    def _apply_project_ids(self, vendor_id: str, project_ids: List[str]) -> None:
        existing = self.db.execute(
            select(ProjectVendor).where(ProjectVendor.vendor_id == vendor_id)
        ).scalars().all()
        for pv in existing:
            self.db.delete(pv)
        self.db.flush()
        seen: set = set()
        now = datetime.now(timezone.utc)
        for pid in project_ids:
            if pid in seen:
                continue
            seen.add(pid)
            self.db.add(ProjectVendor(project_id=pid, vendor_id=vendor_id, created_at=now))

    def list_(
        self,
        *,
        active_only: bool = False,
        caller_vendor_id: Optional[str] = None,
        is_admin: bool = False,
        caller_can_see_all: bool = False,
    ) -> List[Vendor]:
        """§3.1 (2026-06-02 audit) item 7: ``caller_can_see_all`` replaces
        the ``is_admin`` short-circuit (caller passes if they hold
        ``vendors:read`` — admin/super_admin hold it via r005). ``is_admin``
        kept for backwards compatibility with route call sites that pre-
        date the change."""
        if is_admin or caller_can_see_all:
            vendor_id_filter = None
        else:
            vendor_id_filter = caller_vendor_id
        return self.repo.list_(
            active_only=active_only,
            vendor_id_filter=vendor_id_filter,
        )

    def list_projects_for_vendors(self, vendor_ids: List[str]) -> Dict[str, List[Project]]:
        return self.repo.list_projects_for_vendors_batch(vendor_ids)

    def get_by_id(self, vendor_id: str) -> Vendor:
        row = self.repo.get_by_id(vendor_id)
        if row is None:
            raise CatalogEntryNotFoundError(f"Vendor {vendor_id!r} not found")
        return row

    def _get_editable(self, vendor_id: str) -> Vendor:
        """Bug #242: resolve a vendor for EDIT/DELETE. A soft-deleted vendor is
        not editable in place — tell the caller to restore it first, distinct
        from a genuine 'not found'."""
        row = self.repo.get_by_id_any(vendor_id)
        if row is None:
            raise CatalogEntryNotFoundError(f"Vendor {vendor_id!r} not found")
        if row.deleted_at is not None:
            raise CatalogEntryConflictError(
                "This vendor is deleted and cannot be edited. "
                "Restore it first to make changes.",
                details={"vendor_id": vendor_id, "deleted": True},
            )
        return row

    def create(self, payload: VendorCreateRequest) -> Vendor:
        if self.repo.get_by_name(payload.name) is not None:
            raise CatalogEntryConflictError(
                f"Vendor name {payload.name!r} already exists",
                details={"name": payload.name},
            )
        vendor_code = generate_vendor_code(payload.name)
        row = self.repo.create(
            vendor_code=vendor_code,
            name=payload.name,
            description=payload.description,
            email=str(payload.email) if payload.email else None,
            contact_person=payload.contact_person,
            phone_number=payload.phone_number,
            active=payload.active if payload.active is not None else True,
        )
        project_ids = payload.project_ids or []
        if project_ids:
            self._apply_project_ids(row.id, project_ids)
        self.db.commit()
        return row

    def _assert_not_on_active_projects(self, vendor_id: str, action: str) -> None:
        """Bug #139: an organization cannot be deleted or deactivated while it
        is still assigned to active (non-closed/completed, non-deleted) projects.
        Block the action and name the projects so the user can unassign first."""
        projects = self.repo.list_projects_for_vendor(vendor_id)
        if projects:
            names = ", ".join(p.name for p in projects[:10])
            more = "" if len(projects) <= 10 else f" (+{len(projects) - 10} more)"
            raise CatalogEntryConflictError(
                f"Cannot {action} this organization — it is assigned to "
                f"{len(projects)} active project(s): {names}{more}. Remove it "
                f"from these projects first.",
                details={"projects": [{"id": p.id, "name": p.name} for p in projects]},
            )

    def update(self, vendor_id: str, payload: VendorUpdateRequest) -> Vendor:
        row = self._get_editable(vendor_id)
        updates = payload.model_dump(exclude_unset=True, exclude={"project_ids"})
        # Bug #139: block DEACTIVATION (active -> false) while on active projects.
        if updates.get("active") is False and row.active:
            self._assert_not_on_active_projects(vendor_id, "deactivate")
        if updates.get("name") and updates["name"] != row.name:
            clash = self.repo.get_by_name(updates["name"])
            if clash is not None and clash.id != row.id:
                raise CatalogEntryConflictError(
                    f"Vendor name {updates['name']!r} already in use",
                    details={"name": updates["name"]},
                )
        if "email" in updates and updates["email"] is not None:
            updates["email"] = str(updates["email"])
        self.repo.update(row, **updates)
        project_ids = payload.model_dump(exclude_unset=True).get("project_ids")
        if project_ids is not None:
            self._apply_project_ids(vendor_id, project_ids)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise CatalogEntryConflictError(
                f"Vendor name {updates.get('name', row.name)!r} already in use",
                details={"name": updates.get("name", row.name)},
            )
        return row

    def delete(self, vendor_id: str, *, deleted_by_user_id: str) -> Vendor:
        row = self._get_editable(vendor_id)
        # Bug #139: block DELETE while the org is on active projects.
        self._assert_not_on_active_projects(vendor_id, "delete")
        self.repo.soft_delete(row, deleted_by_user_id=deleted_by_user_id)
        self.db.commit()
        return row

    def restore(self, vendor_id: str) -> Vendor:
        # Restore must see the soft-deleted row (the only path that may).
        row = self.repo.get_by_id_any(vendor_id)
        if row is None:
            raise CatalogEntryNotFoundError(f"Vendor {vendor_id!r} not found")
        # Bug #138 (org side): a deleted vendor freed its name/code, so a NEW
        # live vendor may have taken them. In that case it cannot be restored
        # until the conflict is resolved — surface a clean 409, not a raw DB
        # error. (get_by_name is live-only; add a live-only vendor_code check.)
        name_clash = self.repo.get_by_name(row.name)
        if name_clash is not None and name_clash.id != row.id:
            raise CatalogEntryConflictError(
                f"Vendor cannot be restored — the name {row.name!r} is already "
                f"in use by another vendor. Rename or remove that vendor first.",
                details={"name": row.name},
            )
        code_clash = self.repo.get_live_by_vendor_code(row.vendor_code)
        if code_clash is not None and code_clash.id != row.id:
            raise CatalogEntryConflictError(
                f"Vendor cannot be restored — the code {row.vendor_code!r} is "
                f"already in use by another vendor.",
                details={"vendor_code": row.vendor_code},
            )
        try:
            self.repo.restore(row)
            self.db.commit()
        except IntegrityError:  # pragma: no cover - defensive (race with a concurrent create)
            self.db.rollback()
            raise CatalogEntryConflictError(
                f"Vendor cannot be restored — a unique field (name/code) is "
                f"already in use by another vendor.",
                details={"vendor_id": vendor_id},
            )
        return row
