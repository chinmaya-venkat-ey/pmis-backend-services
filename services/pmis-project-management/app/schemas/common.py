"""Shared schemas: pagination + HAL Collection wrapper."""
from __future__ import annotations

from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated envelope used by route handlers that don't emit HAL.

    For HAL Collection envelopes, use app.core.response.hal_collection in the
    handler instead.
    """

    items: List[T]
    total: int
    offset: int = 1
    page_size: int = 20


class DependsListRequest(BaseModel):
    """Used by PUT /.../{id}/dependencies/replace endpoints."""

    model_config = ConfigDict(extra="forbid")
    depends_on: List[str] = Field(
        default_factory=list,
        description="UUIDs of the SAME-KIND parents this item dependsOn (in order)",
    )


class DependsListResponse(BaseModel):
    depends_on: List[str] = Field(default_factory=list)


class VendorIdsListRequest(BaseModel):
    """Used by PUT /projects/{uuid}/vendors/replace and milestone equivalent."""

    model_config = ConfigDict(extra="forbid")
    vendor_ids: List[str] = Field(default_factory=list, description="masters.vendors.id values")


class VendorIdsListResponse(BaseModel):
    vendor_ids: List[str] = Field(default_factory=list)


class ProjectAuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: str
    target_kind: str
    target_id: str
    action: str
    actor_user_id: Optional[str] = None
    changes: dict[str, Any] = Field(default_factory=dict)
    note: Optional[str] = None
    created_at: Any
