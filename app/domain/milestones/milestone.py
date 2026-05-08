"""Milestone domain entity."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple
from ...shared.datetime import iso_ist


# Status choices — extensible by editing this tuple. Stored lowercase /
# underscore_separated. Default is 'not_completed'.
MILESTONE_STATUS_NOT_COMPLETED = "not_completed"
MILESTONE_STATUS_COMPLETED = "completed"
MILESTONE_STATUS_CHOICES: Tuple[str, ...] = (
    MILESTONE_STATUS_NOT_COMPLETED,
    MILESTONE_STATUS_COMPLETED,
)
MILESTONE_STATUS_DEFAULT = MILESTONE_STATUS_NOT_COMPLETED


@dataclass
class Milestone:
    """
    Milestone domain entity.

    Milestones have NO type column. ``actual_start_date`` /
    ``actual_end_date`` were added post-Doc-41 so the FE can render
    them on the edit form, matching activity / task / subtask.
    """
    id: str
    project_id: str
    name: str
    description: Optional[str]
    start_date: datetime
    end_date: datetime
    position: int
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    deleted_at: Optional[datetime] = None
    status: str = MILESTONE_STATUS_DEFAULT
    # Tester report: actual dates added — both nullable, set when work
    # actually starts / finishes.
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    # Doc 41 follow-up: priority code from the ``priorities`` catalog.
    # Required on the wire on create; backfill assigns existing rows ``p3``.
    priority: Optional[str] = None
    # Live milestone-dependency target ids (sorted), populated from the
    # milestone_dependencies edge table by the repository on read. The legacy
    # JSON ``depends`` column on the model is no longer surfaced.
    depends_on: List[str] = field(default_factory=list)
    # (vendor_id, vendor_name) pairs attached to this milestone. Populated by
    # the repository on eager-load reads; empty list otherwise.
    vendors: List[Tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "start_date": iso_ist(self.start_date),
            "end_date": iso_ist(self.end_date),
            "actual_start_date": iso_ist(self.actual_start_date),
            "actual_end_date": iso_ist(self.actual_end_date),
            "position": self.position,
            "status": self.status,
            "priority": self.priority,
            "depends_on": list(self.depends_on),
            "created_at": iso_ist(self.created_at),
            "updated_at": iso_ist(self.updated_at),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "deleted_at": iso_ist(self.deleted_at),
            "vendors": [{"id": vid, "name": vname} for (vid, vname) in self.vendors],
        }
