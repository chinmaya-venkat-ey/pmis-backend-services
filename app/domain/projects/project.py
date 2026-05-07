"""
Project domain model.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple
from ...shared.datetime import iso_ist


@dataclass
class Project:
    """
    Project domain entity.

    Public identity:
      - id (UUID string) — the PK, exposed in URLs and response bodies.
      - project_code     — UIDAI-PRYYMMDDHHMMSS (IST). Human-readable.

    A project owns its milestones / activities / tasks / subtasks
    directly — there is no baseline-vs-version split.
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
    # Doc 26: user-id fields are UUID strings (was int pre-doc-26).
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
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
            "start_date": iso_ist(self.start_date),
            "end_date": iso_ist(self.end_date),
            "actual_start_date": iso_ist(self.actual_start_date),
            "actual_end_date": iso_ist(self.actual_end_date),
            "created_at": iso_ist(self.created_at),
            "updated_at": iso_ist(self.updated_at),
            "parent_id": self.parent_id,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "deleted_at": iso_ist(self.deleted_at),
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
