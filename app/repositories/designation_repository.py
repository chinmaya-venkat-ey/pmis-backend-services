"""Data access for the designations catalog. Delete via active=False."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.designation import Designation


class DesignationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, designation_id: str) -> Optional[Designation]:
        return self.db.get(Designation, designation_id)

    def get_by_code(self, code: str, vendor_id: Optional[str] = None) -> Optional[Designation]:
        """Org-scoped lookup: a code is unique WITHIN an organization
        (``vendor_id``). ``vendor_id=None`` matches the global/template rows."""
        stmt = select(Designation).where(Designation.code == code)
        if vendor_id is None:
            stmt = stmt.where(Designation.vendor_id.is_(None))
        else:
            stmt = stmt.where(Designation.vendor_id == vendor_id)
        return self.db.execute(stmt).scalars().first()

    def list_(
        self, *, include_inactive: bool = False, vendor_id: Optional[str] = None,
    ) -> List[Designation]:
        stmt = select(Designation)
        if not include_inactive:
            stmt = stmt.where(Designation.active.is_(True))
        if vendor_id is not None:
            stmt = stmt.where(Designation.vendor_id == vendor_id)
        stmt = stmt.order_by(Designation.name.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> Designation:
        row = Designation(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Designation, **kwargs) -> Designation:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: Designation) -> Designation:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: Designation) -> Designation:
        row.active = True
        self.db.flush()
        return row
