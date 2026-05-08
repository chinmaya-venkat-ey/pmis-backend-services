"""Subtask domain entity."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from ...shared.datetime import iso_ist


SUBTASK_TYPE_STANDARD = "standard"
SUBTASK_TYPE_RESOURCE = "resource"
SUBTASK_TYPE_TRANSACTIONAL = "transactional"
SUBTASK_TYPES = (SUBTASK_TYPE_STANDARD, SUBTASK_TYPE_RESOURCE, SUBTASK_TYPE_TRANSACTIONAL)


RESOURCE_MODE_COUNT = "count"
RESOURCE_MODE_DETAILS = "details"
RESOURCE_MODES = (RESOURCE_MODE_COUNT, RESOURCE_MODE_DETAILS)


@dataclass
class Subtask:
    """Subtask domain entity. Parent is a Task or another Subtask.

    Doc 24: ``parent_subtask_id`` carries the immediate parent for
    nested subtasks (NULL = top-level child of ``task_id``). The
    ``task_id`` field always holds the **root task** id of the subtree.
    See Activity docstring for resource_mode / resource_count rules.
    """
    id: str
    project_id: str
    task_id: str
    name: str
    description: Optional[str]
    type: Optional[str]
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
    # Doc 38: lifecycle status, set via PATCH only.
    status: Optional[str] = None
    parent_subtask_id: Optional[str] = None
    # Target subtask ids this subtask depends on. Populated from
    # subtask_dependencies association table.
    depends_on: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "parent_subtask_id": self.parent_subtask_id,
            "name": self.name,
            "description": self.description,
            "type": self.type,
            "start_date": iso_ist(self.start_date),
            "end_date": iso_ist(self.end_date),
            "actual_start_date": iso_ist(self.actual_start_date),
            "actual_end_date": iso_ist(self.actual_end_date),
            "position": self.position,
            "resource_mode": self.resource_mode,
            "resource_count": self.resource_count,
            "status": self.status,
            "depends_on": list(self.depends_on or []),
            "created_at": iso_ist(self.created_at),
            "updated_at": iso_ist(self.updated_at),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "deleted_at": iso_ist(self.deleted_at),
        }
