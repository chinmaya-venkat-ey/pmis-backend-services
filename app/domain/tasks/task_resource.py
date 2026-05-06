"""Task resource sub-entity (for Resource-type tasks)."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional
from ...shared.datetime import iso_utc


@dataclass
class TaskResource:
    """1-to-1 with Task via task_id (live rows only)."""
    id: str
    task_id: str
    project_id: str
    resource_name: str
    onboard_date: Optional[datetime]
    actual_onboard_date: Optional[datetime]
    offboard_date: Optional[datetime]
    actual_offboard_date: Optional[datetime]
    position: Optional[str]
    designation: Optional[str]
    job_role: Optional[str]
    qualification: Optional[str]
    experience_years: Optional[Decimal]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "resource_name": self.resource_name,
            "onboard_date": iso_utc(self.onboard_date),
            "actual_onboard_date": iso_utc(self.actual_onboard_date),
            "offboard_date": iso_utc(self.offboard_date),
            "actual_offboard_date": iso_utc(self.actual_offboard_date),
            "position": self.position,
            "designation": self.designation,
            "job_role": self.job_role,
            "qualification": self.qualification,
            "experience_years": float(self.experience_years) if self.experience_years is not None else None,
            "created_at": iso_utc(self.created_at),
            "updated_at": iso_utc(self.updated_at),
            "deleted_at": iso_utc(self.deleted_at),
        }
