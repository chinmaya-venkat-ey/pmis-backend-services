"""Activity domain entity. Ported verbatim from the monolith."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

ACTIVITY_TYPE_STANDARD = "standard"
ACTIVITY_TYPE_RESOURCE = "resource"
ACTIVITY_TYPE_TRANSACTIONAL = "transactional"
ACTIVITY_TYPES = (
    ACTIVITY_TYPE_STANDARD,
    ACTIVITY_TYPE_RESOURCE,
    ACTIVITY_TYPE_TRANSACTIONAL,
    )

RESOURCE_MODE_COUNT = "count"
RESOURCE_MODE_DETAILS = "details"
RESOURCE_MODES = (RESOURCE_MODE_COUNT, RESOURCE_MODE_DETAILS)

ACTIVITY_STATUS_NOT_COMPLETED = "not_completed"
ACTIVITY_STATUS_COMPLETED = "completed"
ACTIVITY_STATUS_CHOICES: Tuple[str, ...] = (
    ACTIVITY_STATUS_NOT_COMPLETED,
    ACTIVITY_STATUS_COMPLETED,
    )
ACTIVITY_STATUS_DEFAULT = ACTIVITY_STATUS_NOT_COMPLETED

@dataclass
class Activity:
    id: str
    project_id: str
    milestone_id: str
    name: str
    description: Optional[str]
    type: str
    start_date: datetime
    end_date: datetime
    actual_start_date: Optional[datetime]
    actual_end_date: Optional[datetime]
    position: int
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    deleted_at: Optional[datetime] = None
    resource_mode: Optional[str] = None
    resource_count: Optional[int] = None
    status: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "milestone_id": self.milestone_id,
            "name": self.name,
            "description": self.description,
            "type": self.type,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "actual_start_date": self.actual_start_date.isoformat() if self.actual_start_date else None,
            "actual_end_date": self.actual_end_date.isoformat() if self.actual_end_date else None,
            "position": self.position,
            "resource_mode": self.resource_mode,
            "resource_count": self.resource_count,
            "status": self.status,
            "depends_on": list(self.depends_on or []),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            }
