"""Task resource sub-entity (for Resource-type tasks). Ported from monolith.

Note: TaskResource has fewer fields than ActivityResource — no
``type_of_resource_id`` and no ``division`` columns. Tasks don't
classify against the resource_types catalog (only activities do).
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

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
            "onboard_date": self.onboard_date.isoformat() if self.onboard_date else None,
            "actual_onboard_date": self.actual_onboard_date.isoformat() if self.actual_onboard_date else None,
            "offboard_date": self.offboard_date.isoformat() if self.offboard_date else None,
            "actual_offboard_date": self.actual_offboard_date.isoformat() if self.actual_offboard_date else None,
            "position": self.position,
            "designation": self.designation,
            "job_role": self.job_role,
            "qualification": self.qualification,
            "experience_years": float(self.experience_years) if self.experience_years is not None else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            }
