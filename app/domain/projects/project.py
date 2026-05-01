"""
Project domain model.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple


@dataclass
class Project:
    """
    Project domain entity.

    Public identity:
      - id (UUID string) — the PK, exposed in URLs and response bodies.
      - project_code     — UIDAI-PRYYMMDDHHMMSS (IST). Human-readable.

    Internal FK references (all UUID strings):
      - parent_id, version_of, baseline_id — self-FKs into projects.id.
    """

    id: str
    project_code: str
    name: str
    description: Optional[str]
    active: bool
    public: bool
    status_explanation: Optional[str]
    created_at: datetime
    updated_at: datetime
    parent_id: Optional[str] = None
    status: str = "new"
    owner: Optional[str] = None
    category: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    is_version: bool = False
    version_of: Optional[str] = None
    baseline_id: Optional[str] = None
    version_no: Optional[int] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[int] = None
    # Present when category == 'others'; otherwise None.
    category_other: Optional[str] = None
    # Reason explaining why category='others' was chosen instead of one of
    # the standard categories. Required when category='others'; None otherwise.
    category_other_reason: Optional[str] = None
    # Free-text owner label captured when ``owner == 'others'``. Required
    # in that case (validated at the service layer); MUST be NULL for any
    # other owner value.
    owner_other: Optional[str] = None
    # List of (vendor_id, vendor_name) pairs associated with this project.
    # Populated by the repository on read (left empty when not eagerly loaded).
    vendors: List[Tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_code": self.project_code,
            "name": self.name,
            "description": self.description,
            "active": self.active,
            "public": self.public,
            "status_explanation": self.status_explanation,
            "status": self.status,
            "owner": self.owner,
            "category": self.category,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "actual_start_date": self.actual_start_date.isoformat() if self.actual_start_date else None,
            "actual_end_date": self.actual_end_date.isoformat() if self.actual_end_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "parent_id": self.parent_id,
            "is_version": self.is_version,
            "version_of": self.version_of,
            "baseline_id": self.baseline_id,
            "version_no": self.version_no,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
            "category_other": self.category_other,
            "category_other_reason": self.category_other_reason,
            "owner_other": self.owner_other,
            "vendors": [{"id": vid, "name": vname} for (vid, vname) in self.vendors],
        }

    def is_active(self) -> bool:
        return self.active

    def is_public(self) -> bool:
        return self.public

    def has_parent(self) -> bool:
        return self.parent_id is not None

    def is_soft_deleted(self) -> bool:
        return self.deleted_at is not None
