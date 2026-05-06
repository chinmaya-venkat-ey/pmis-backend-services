"""Activity domain entity."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple
from ...shared.datetime import iso_utc


# Enum-style constants for type validation.
ACTIVITY_TYPE_STANDARD = "standard"
ACTIVITY_TYPE_RESOURCE = "resource"
ACTIVITY_TYPE_TRANSACTIONAL = "transactional"
ACTIVITY_TYPES = (
    ACTIVITY_TYPE_STANDARD,
    ACTIVITY_TYPE_RESOURCE,
    ACTIVITY_TYPE_TRANSACTIONAL,
)


# Resource-mode vocabulary (used only when type='resource').
RESOURCE_MODE_COUNT = "count"
RESOURCE_MODE_DETAILS = "details"
RESOURCE_MODES = (RESOURCE_MODE_COUNT, RESOURCE_MODE_DETAILS)


# Lifecycle status applicable to ALL activity types (standard, resource,
# transactional). Extensible — add new states by appending to
# ACTIVITY_STATUS_CHOICES. The dependency-completion gate keys on
# ACTIVITY_STATUS_COMPLETED regardless of the activity's type.
ACTIVITY_STATUS_NOT_COMPLETED = "not_completed"
ACTIVITY_STATUS_COMPLETED = "completed"
ACTIVITY_STATUS_CHOICES: Tuple[str, ...] = (
    ACTIVITY_STATUS_NOT_COMPLETED,
    ACTIVITY_STATUS_COMPLETED,
)
ACTIVITY_STATUS_DEFAULT = ACTIVITY_STATUS_NOT_COMPLETED


@dataclass
class Activity:
    """
    Activity domain entity.

    Activities carry a type (standard/resource/transactional) and optional
    actual dates. When type == 'resource', resource_mode tells us HOW the
    resource is expressed:
      * mode = 'count'   -> resource_count is set; NO ActivityResource row
      * mode = 'details' -> resource_count is NULL; one live ActivityResource
                            row (keyed by activity_id) carries the 9 fields
    When type != 'resource', both resource_mode and resource_count are NULL.
    """
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
    # Lifecycle status; applies to all activity types. NULL on legacy rows
    # created before status was extended beyond standard-type activities;
    # new activities default to ACTIVITY_STATUS_DEFAULT on create.
    status: Optional[str] = None
    # List of target activity ids this activity depends on. Populated by the
    # service layer from the activity_dependencies association table; never
    # stored on the activity row itself.
    depends_on: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "milestone_id": self.milestone_id,
            "name": self.name,
            "description": self.description,
            "type": self.type,
            "start_date": iso_utc(self.start_date),
            "end_date": iso_utc(self.end_date),
            "actual_start_date": iso_utc(self.actual_start_date),
            "actual_end_date": iso_utc(self.actual_end_date),
            "position": self.position,
            "resource_mode": self.resource_mode,
            "resource_count": self.resource_count,
            "status": self.status,
            "depends_on": list(self.depends_on or []),
            "created_at": iso_utc(self.created_at),
            "updated_at": iso_utc(self.updated_at),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "deleted_at": iso_utc(self.deleted_at),
        }
