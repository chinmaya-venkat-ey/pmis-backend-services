"""Project audit-log schemas — wire surface for
``GET /project/projects/{uuid}/audit-logs``.

Mirrors the monolith's audit-log shape: each row carries the actor
metadata snapshotted at write time + the before/after JSON delta so the
log remains meaningful even after source rows mutate.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectAuditLogEntry(BaseModel):
    """One row in the audit log."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: str
    target_kind: str
    target_id: str
    action: str
    actor_user_id: Optional[str] = None
    changes: Dict[str, Any] = Field(default_factory=dict)
    note: Optional[str] = None
    created_at: datetime


class ProjectAuditLogProjectInfo(BaseModel):
    """Project header included alongside the audit-log page."""

    model_config = ConfigDict(from_attributes=False)

    project_id: str
    project_code: Optional[str] = None
    project_name: Optional[str] = None
    project_status: Optional[str] = None
    owner: Optional[str] = None


class ProjectAuditLogListResponse(BaseModel):
    """``GET /project/projects/{uuid}/audit-logs`` payload."""

    model_config = ConfigDict(from_attributes=False)

    project: ProjectAuditLogProjectInfo
    total: int
    offset: int
    page_size: int
    elements: List[ProjectAuditLogEntry] = Field(default_factory=list)
