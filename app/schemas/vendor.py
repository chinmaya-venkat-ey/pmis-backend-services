"""Pydantic v2 schemas for the vendors catalog.

Per Q1: wire keeps `vendor_*` field names (FE renders "Organization" label only).
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas._base import ResponseModel


class VendorCreateRequest(BaseModel):
    """Body of POST /masters/vendors/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", populate_by_name=True)

    name: Annotated[str, Field(min_length=1, max_length=255,
                               description="Display name (unique)")]
    description: Annotated[Optional[str], Field(default=None, max_length=4096)]
    active: Annotated[Optional[bool], Field(default=True)]
    email: Annotated[Optional[EmailStr], Field(default=None)]
    contact_person: Annotated[Optional[str], Field(
        default=None, max_length=255, alias="contactPerson"
    )]
    phone_number: Annotated[Optional[str], Field(
        default=None, max_length=50, alias="phoneNumber"
    )]
    project_ids: Annotated[Optional[List[str]], Field(
        default_factory=list, alias="projectIds"
    )]


class VendorUpdateRequest(BaseModel):
    """Body of PATCH /masters/vendors/{vendor_id}/update — partial."""

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


class VendorResponse(ResponseModel):
    """Returned by GET /masters/vendors/list and /details."""

    id: str
    vendor_code: Optional[str] = None
    name: str
    description: Optional[str] = None
    active: bool
    email: Optional[str] = None
    contact_person: Optional[str] = None
    phone_number: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
