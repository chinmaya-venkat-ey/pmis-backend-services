"""Catalog / master-data response schemas for project-service catalog lookups.

Project-svc serves read-only catalog lookups at /api/v3/{catalog} (no
/master/ prefix) so the FE can load dropdown data without calling masters-svc
directly. These schemas mirror what masters-svc returns.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas._base import ResponseModel


class DivisionResponse(ResponseModel):
    id: int
    code: str
    label: str
    # Serialized as camelCase to match VM API and FE fromApi expectations.
    is_builtin: bool = Field(serialization_alias="isBuiltin")
    requires_other: bool = Field(serialization_alias="requiresOther")
    active: bool
    email: str
    phone_number: str = Field(serialization_alias="phoneNumber")


class PriorityResponse(ResponseModel):
    id: str
    code: str
    name: str
    description: Optional[str] = None
    position: int
    is_builtin: bool
    active: bool


class ResourceTypeResponse(ResponseModel):
    id: str
    code: str
    name: str
    active: bool
    created_at: datetime
    updated_at: datetime


class ResourceTypeCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    active: bool = True


class ProjectStatusTransitionResponse(ResponseModel):
    id: int
    from_status: Optional[str] = None
    to_status: str
    permission_code: Optional[str] = None
    active: bool


class VendorResponse(ResponseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    vendor_code: Optional[str] = Field(default=None, serialization_alias="vendorCode")
    name: str
    description: Optional[str] = None
    active: bool
    email: Optional[str] = None
    contact_person: Optional[str] = Field(default=None, serialization_alias="contactPerson")
    phone_number: Optional[str] = Field(default=None, serialization_alias="phoneNumber")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    deleted_at: Optional[datetime] = Field(default=None, serialization_alias="deletedAt")
    deleted_by: Optional[str] = None
    # Populated by route handlers from project_vendors + projects tables.
    projects: List[Dict[str, Any]] = Field(default_factory=list)
    # Per-(project, role) user assignments, populated by route handlers.
    user_assignments: List[Dict[str, Any]] = Field(default_factory=list)


class VendorCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", populate_by_name=True)
    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=4096)]
    active: bool = True
    email: Annotated[Optional[EmailStr], Field(default=None)]
    contact_person: Annotated[Optional[str], Field(
        default=None, max_length=255, alias="contactPerson"
    )]
    phone_number: Annotated[str, Field(min_length=1, max_length=50, alias="phoneNumber")]
    project_ids: Annotated[List[str], Field(default_factory=list, alias="projectIds")]


class VendorUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", populate_by_name=True)
    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=4096)]
    active: Annotated[Optional[bool], Field(default=None)]
    email: Annotated[Optional[EmailStr], Field(default=None)]
    contact_person: Annotated[Optional[str], Field(
        default=None, max_length=255, alias="contactPerson"
    )]
    phone_number: Annotated[Optional[str], Field(
        default=None, max_length=50, alias="phoneNumber"
    )]
    project_ids: Annotated[Optional[List[str]], Field(default=None, alias="projectIds")]
    # Bug #9: FE sends the flat assignments list under "assignments" key.
    user_assignments: Optional[List[Dict[str, Any]]] = Field(default=None, alias="assignments")


class UserSummary(ResponseModel):
    id: str
    user_code: Optional[str] = None
    login: str
    email: str
    full_name: Optional[str] = None
    status: str
