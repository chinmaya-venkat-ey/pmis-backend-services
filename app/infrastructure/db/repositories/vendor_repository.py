"""Vendor + project/milestone-vendor association queries.

Soft-delete: a vendor row stays in the table after DELETE — only ``deleted_at``
and ``active`` are stamped. This preserves the historical project_vendors /
milestone_vendors mapping rows so a later restore can resurrect the vendor
with all its associations intact. List endpoints filter out soft-deleted rows;
picker validation (``existing_active_ids``) does the same.
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models.milestone_vendor import MilestoneVendorModel
from ..models.project_vendor import ProjectVendorModel
from ..models.vendor import VendorModel
from ....domain.vendors.vendor import Vendor
from ....shared.code_generators import (
    build_code,
    generate_unique_code,
    looks_like_vendor_code,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_domain(m: VendorModel) -> Vendor:
    return Vendor(
        id=m.id,
        name=m.name,
        description=m.description,
        active=bool(m.active),
        created_at=m.created_at,
        updated_at=m.updated_at,
        deleted_at=m.deleted_at,
        deleted_by=m.deleted_by,
        email=getattr(m, "email", None),
        contact_person=getattr(m, "contact_person", None),
        phone_number=getattr(m, "phone_number", None),
        vendor_code=getattr(m, "vendor_code", None),
    )


class VendorRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- Vendor CRUD (lightweight) ------------------------------------

    def create(
        self,
        *,
        name: str,
        description: Optional[str] = None,
        active: bool = True,
        email: Optional[str] = None,
        contact_person: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> Vendor:
        # Doc 25: generate the human-readable code BEFORE the insert so
        # both the model row and the returned domain object carry it.
        # Compute ``created_at`` in Python (rather than relying on the
        # column default) so the code's timestamp segment matches the
        # row's stored ``created_at`` exactly.
        now = _utcnow()
        clean_name = name.strip()
        base_code = build_code("VN", clean_name, now)
        code = generate_unique_code(
            self.db.connection(),
            table="vendors", code_column="vendor_code",
            base_code=base_code,
        )
        m = VendorModel(
            name=clean_name,
            description=description,
            active=active,
            email=(email.strip() if email else None),
            contact_person=(contact_person.strip() if contact_person else None),
            phone_number=(phone_number.strip() if phone_number else None),
            vendor_code=code,
            created_at=now,
            updated_at=now,
        )
        self.db.add(m)
        self.db.flush()
        return _to_domain(m)

    def get_by_id(self, vendor_id: str, include_deleted: bool = False) -> Optional[Vendor]:
        q = self.db.query(VendorModel).filter(VendorModel.id == vendor_id)
        if not include_deleted:
            q = q.filter(VendorModel.deleted_at.is_(None))
        m = q.first()
        return _to_domain(m) if m else None

    def get_by_code(self, vendor_code: str, include_deleted: bool = False) -> Optional[Vendor]:
        """Lookup by human-readable ``vendor_code`` (e.g. ``VN-ACME-260502143015``)."""
        q = self.db.query(VendorModel).filter(VendorModel.vendor_code == vendor_code)
        if not include_deleted:
            q = q.filter(VendorModel.deleted_at.is_(None))
        m = q.first()
        return _to_domain(m) if m else None

    def get_by_id_or_code(
        self, identifier: str, include_deleted: bool = False,
    ) -> Optional[Vendor]:
        """Polymorphic lookup: dispatches to ``get_by_code`` if the
        identifier looks like a vendor code, otherwise ``get_by_id``.

        Used by every endpoint whose path param accepts either form,
        and by the create-user / create-project services that accept
        ``vendorId`` as either a UUID or a vendor code on input.
        """
        if looks_like_vendor_code(identifier):
            return self.get_by_code(identifier, include_deleted=include_deleted)
        return self.get_by_id(identifier, include_deleted=include_deleted)

    def get_model_by_id_or_code(
        self, identifier: str, include_deleted: bool = False,
    ) -> Optional[VendorModel]:
        """Polymorphic write-path lookup. Mirrors ``get_by_id_or_code``
        but returns the raw ORM model so callers can mutate it
        (soft-delete, restore, patch)."""
        if looks_like_vendor_code(identifier):
            q = self.db.query(VendorModel).filter(
                VendorModel.vendor_code == identifier,
            )
        else:
            q = self.db.query(VendorModel).filter(VendorModel.id == identifier)
        if not include_deleted:
            q = q.filter(VendorModel.deleted_at.is_(None))
        return q.first()

    def resolve_id(self, identifier: str) -> Optional[str]:
        """Return the canonical UUID for either a UUID or a vendor code.

        Used by upstream services (user create, project create) that
        already work in terms of ``vendor_id`` (UUID) but want to accept
        a code on input. Returns ``None`` if the identifier doesn't
        resolve to any LIVE vendor.
        """
        if looks_like_vendor_code(identifier):
            row = (
                self.db.query(VendorModel.id)
                .filter(VendorModel.vendor_code == identifier)
                .filter(VendorModel.deleted_at.is_(None))
                .first()
            )
            return row[0] if row else None
        return identifier  # assume already a UUID; existence check is downstream

    def get_model_by_id(self, vendor_id: str, include_deleted: bool = False) -> Optional[VendorModel]:
        """Return the raw model for write paths that need to mutate it.

        Used by the soft-delete / restore endpoints — they need the live model
        to stamp the new fields. ``get_by_id`` returns the immutable domain
        Vendor and is unsuitable for that.
        """
        q = self.db.query(VendorModel).filter(VendorModel.id == vendor_id)
        if not include_deleted:
            q = q.filter(VendorModel.deleted_at.is_(None))
        return q.first()

    def get_by_name(self, name: str, include_deleted: bool = False) -> Optional[Vendor]:
        q = self.db.query(VendorModel).filter(VendorModel.name == name)
        if not include_deleted:
            q = q.filter(VendorModel.deleted_at.is_(None))
        m = q.first()
        return _to_domain(m) if m else None

    def list_active(self) -> List[Vendor]:
        """List live (non-soft-deleted, active) vendors, newest first.

        The Search Vendor table reads top-down, so the most recently created
        vendor lands at row 0. Tie-break on id keeps pagination stable when
        two rows share a created_at timestamp.
        """
        rows = (
            self.db.query(VendorModel)
            .filter(VendorModel.active == True)  # noqa: E712
            .filter(VendorModel.deleted_at.is_(None))
            .order_by(VendorModel.created_at.desc(), VendorModel.id.desc())
            .all()
        )
        return [_to_domain(r) for r in rows]

    def list_all(self, include_deleted: bool = False) -> List[Vendor]:
        """List vendors in newest-first order. Soft-deleted excluded by default."""
        q = self.db.query(VendorModel)
        if not include_deleted:
            q = q.filter(VendorModel.deleted_at.is_(None))
        rows = q.order_by(VendorModel.created_at.desc(), VendorModel.id.desc()).all()
        return [_to_domain(r) for r in rows]

    def existing_active_ids(self, ids: List[str]) -> List[str]:
        """Filter ids down to the subset that exists, is active, and is not soft-deleted.

        Picker / association paths use this to reject stale ids before
        attaching them to projects or milestones. A soft-deleted vendor is
        treated as if it doesn't exist for new attachments.
        """
        if not ids:
            return []
        rows = (
            self.db.query(VendorModel.id)
            .filter(VendorModel.id.in_(ids))
            .filter(VendorModel.active == True)  # noqa: E712
            .filter(VendorModel.deleted_at.is_(None))
            .all()
        )
        return [r[0] for r in rows]

    # ---- Soft delete / restore ---------------------------------------

    def soft_delete(self, vendor_id: str, *, actor_id: Optional[str]) -> Optional[Vendor]:
        """Mark a vendor deleted. Idempotent on already-deleted rows.

        Sets ``deleted_at`` + ``deleted_by`` and flips ``active`` to False so
        the vendor disappears from every list / picker. Project + milestone
        mapping rows are intentionally left in place so a later restore can
        resurrect the vendor with its history intact.
        """
        m = self.db.query(VendorModel).filter(VendorModel.id == vendor_id).first()
        if m is None:
            return None
        if m.deleted_at is None:
            m.deleted_at = _utcnow()
            m.deleted_by = actor_id
            m.active = False
            self.db.flush()
        return _to_domain(m)

    def restore(self, vendor_id: str) -> Optional[Vendor]:
        """Undelete a soft-deleted vendor. Sets active=True, clears deleted_at.

        The mapping rows in project_vendors / milestone_vendors were never
        touched, so they re-surface automatically. Callers that show the
        restored vendor's project list should filter out closed/completed
        projects at query time — see the route docstring.
        """
        m = self.db.query(VendorModel).filter(VendorModel.id == vendor_id).first()
        if m is None:
            return None
        if m.deleted_at is not None:
            m.deleted_at = None
            m.deleted_by = None
            m.active = True
            self.db.flush()
        return _to_domain(m)

    # ---- Project-Vendor associations ----------------------------------

    def set_project_vendors(self, project_id: str, vendor_ids: List[str]) -> None:
        """Replace the full vendor set for a project. Does NOT commit."""
        self.db.query(ProjectVendorModel).filter(
            ProjectVendorModel.project_id == project_id
        ).delete(synchronize_session=False)
        for vid in vendor_ids:
            self.db.add(ProjectVendorModel(project_id=project_id, vendor_id=vid))
        self.db.flush()

    def list_project_vendors(self, project_id: str) -> List[Tuple[str, str]]:
        """Return [(vendor_id, vendor_name), ...] for the project."""
        rows = (
            self.db.query(VendorModel.id, VendorModel.name)
            .join(ProjectVendorModel, ProjectVendorModel.vendor_id == VendorModel.id)
            .filter(ProjectVendorModel.project_id == project_id)
            .order_by(VendorModel.name.asc())
            .all()
        )
        return [(r[0], r[1]) for r in rows]

    def project_vendor_ids(self, project_id: str) -> List[str]:
        rows = (
            self.db.query(ProjectVendorModel.vendor_id)
            .filter(ProjectVendorModel.project_id == project_id)
            .all()
        )
        return [r[0] for r in rows]

    # ---- Vendor-side: assign / replace a vendor's project list -------

    def set_vendor_projects(self, vendor_id: str, project_ids: List[str]) -> None:
        """Replace the full project-mapping set for a vendor.

        Symmetric with ``set_project_vendors`` — both write to the same
        ``project_vendors`` association table, just from opposite sides.
        Used by POST /vendors/create + PATCH /vendors/{id} when the
        caller supplies ``projectIds`` (vendor-side assignment, the
        FE flow where you pick a vendor and attach projects to it).
        Does NOT commit.
        """
        self.db.query(ProjectVendorModel).filter(
            ProjectVendorModel.vendor_id == vendor_id
        ).delete(synchronize_session=False)
        for pid in project_ids:
            self.db.add(ProjectVendorModel(project_id=pid, vendor_id=vendor_id))
        self.db.flush()

    # ---- Milestone-Vendor associations --------------------------------

    def set_milestone_vendors(self, milestone_id: str, vendor_ids: List[str]) -> None:
        """Replace the full vendor set for a milestone. Does NOT commit."""
        self.db.query(MilestoneVendorModel).filter(
            MilestoneVendorModel.milestone_id == milestone_id
        ).delete(synchronize_session=False)
        for vid in vendor_ids:
            self.db.add(MilestoneVendorModel(milestone_id=milestone_id, vendor_id=vid))
        self.db.flush()

    def list_milestone_vendors(self, milestone_id: str) -> List[Tuple[str, str]]:
        rows = (
            self.db.query(VendorModel.id, VendorModel.name)
            .join(MilestoneVendorModel, MilestoneVendorModel.vendor_id == VendorModel.id)
            .filter(MilestoneVendorModel.milestone_id == milestone_id)
            .order_by(VendorModel.name.asc())
            .all()
        )
        return [(r[0], r[1]) for r in rows]
