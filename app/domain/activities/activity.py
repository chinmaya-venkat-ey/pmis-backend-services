"""Activity domain entity."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple
from ...shared.datetime import iso_ist


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
    # Lifecycle status; applies to all activity types. NULL on legacy rows
    # created before status was extended beyond standard-type activities;
    # new activities default to ACTIVITY_STATUS_DEFAULT on create.
    status: Optional[str] = None
    # List of target activity ids this activity depends on. Populated by the
    # service layer from the activity_dependencies association table; never
    # stored on the activity row itself.
    depends_on: List[str] = field(default_factory=list)
    # Doc 38 additions — optional ownership / partner / consulted-division.
    owner_division: Optional[str] = None
    concerned_division: Optional[str] = None
    # Doc 39: multi list of division codes; backfilled from the
    # legacy single ``concerned_division`` for existing rows.
    concerned_divisions: Optional[List[str]] = None
    vendor_id: Optional[str] = None
    # Doc 41: priority code from the ``priorities`` catalog. Required on
    # the wire on create; legacy rows backfilled to ``p3``.
    priority: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "milestone_id": self.milestone_id,
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
            "owner_division": self.owner_division,
            "concerned_division": self.concerned_division,
            "concerned_divisions": list(self.concerned_divisions) if self.concerned_divisions else None,
            "vendor_id": self.vendor_id,
            "priority": self.priority,
            "created_at": iso_ist(self.created_at),
            "updated_at": iso_ist(self.updated_at),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "deleted_at": iso_ist(self.deleted_at),
        }
