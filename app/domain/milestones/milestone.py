"""Milestone domain entity. Ported verbatim from the monolith."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional, Tuple

MILESTONE_STATUS_NOT_COMPLETED = "not_completed"
MILESTONE_STATUS_COMPLETED = "completed"
MILESTONE_STATUS_CHOICES: Tuple[str, ...] = (
    MILESTONE_STATUS_NOT_COMPLETED,
    MILESTONE_STATUS_COMPLETED,
    )
MILESTONE_STATUS_DEFAULT = MILESTONE_STATUS_NOT_COMPLETED

@dataclass
class Milestone:
    """Milestone domain entity.

    Milestones have NO type column and NO actual_* dates.
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
    depends: Optional[List[Any]] = None
    vendors: List[Tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "position": self.position,
            "status": self.status,
            "depends": self.depends if self.depends is not None else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "vendors": [{"id": vid, "name": vname} for (vid, vname) in self.vendors],
            }
