"""Task domain entity. Ported verbatim from the monolith.

Tasks live under activities (parent FK = activity_id) and are
**version-only** per the project_lock rules — only version projects
accept task writes; baselines reject them.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

TASK_TYPE_STANDARD = "standard"
TASK_TYPE_RESOURCE = "resource"
TASK_TYPE_TRANSACTIONAL = "transactional"
TASK_TYPES = (TASK_TYPE_STANDARD, TASK_TYPE_RESOURCE, TASK_TYPE_TRANSACTIONAL)

RESOURCE_MODE_COUNT = "count"
RESOURCE_MODE_DETAILS = "details"
RESOURCE_MODES = (RESOURCE_MODE_COUNT, RESOURCE_MODE_DETAILS)

@dataclass
class Task:
    """Task domain entity. Same semantics as Activity; parent is an Activity."""
    id: str
    project_id: str
    activity_id: str
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
    # Target task ids this task depends on. Populated by the service from
    # the task_dependencies association table.
    depends_on: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "activity_id": self.activity_id,
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
            "depends_on": list(self.depends_on or []),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            }
