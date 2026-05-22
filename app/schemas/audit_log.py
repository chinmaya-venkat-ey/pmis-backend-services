"""Pydantic schemas for audit logs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas._base import ResponseModel


class AuditLogResponse(ResponseModel):
    """Wire shape for a single audit log entry."""

    id: int
    file_id: Optional[str] = None
    action: str
    actor_user_id: Optional[str] = None
    folder: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    original_filename: Optional[str] = None
    extra_metadata: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: Optional[datetime] = None


class AuditLogSearchRequest(BaseModel):
    """Query parameters for GET /files/audit-logs."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    file_id: Optional[str] = None
    action: Optional[str] = None
    actor_user_id: Optional[str] = None
    folder: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    offset: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100, alias="pageSize")
