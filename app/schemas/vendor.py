"""Pydantic v2 schemas for the vendors catalog.

Wire shape matches the monolith (camelCase aliases, _type discriminator,
embedded projects list). VendorResponse is kept for internal type-checking;
actual HTTP responses are built as plain dicts by the controller so the
Collection wrapper and _type fields are under full control.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas._base import ResponseModel


class VendorCreateRequest(BaseModel):
    """Body of POST /masters/vendors/create — mirrors monolith VendorCreateRequest."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", populate_by_name=True)

    name: Annotated[str, Field(min_length=1, max_length=255,
                               description="Display name (unique)")]
    description: Annotated[Optional[str], Field(default=None, max_length=4096)]
    active: Annotated[Optional[bool], Field(default=True)]
    email: Annotated[Optional[EmailStr], Field(default=None)]
    contact_person: Annotated[Optional[str], Field(
        default=None, max_length=255, alias="contactPerson"
    )]
    # Required on create — matches monolith phoneNumber field.
    phone_number: Annotated[str, Field(min_length=1, max_length=50, alias="phoneNumber")]
    project_ids: Annotated[Optional[List[str]], Field(
        default=None, alias="projectIds"
    )]


class VendorUpdateRequest(BaseModel):
    """Body of PATCH /masters/vendors/{vendor_id} — partial, all fields optional."""

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
    # None = leave existing mappings unchanged; [] = clear all; non-empty = replace.
    project_ids: Annotated[Optional[List[str]], Field(
        default=None, alias="projectIds"
    )]


class VendorResponse(ResponseModel):
    """Internal response model — used for type-checking and IST coercion only.

    HTTP responses are built as dicts by _vendor_dict() in the controller
    so the monolith wire shape (_type, camelCase keys, embedded projects)
    is produced without Pydantic alias gymnastics.
    """

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


def _project_dict(project: Any) -> Dict[str, Any]:
    """Build a single project entry in the monolith wire shape."""
    created_at = getattr(project, "created_at", None)
    return {
        "_type": "Project",
        "id": project.id,
        "projectCode": project.project_code,
        "name": project.name,
        "status": project.status,
        "createdAt": created_at.isoformat() if created_at else None,
    }


def _vendor_dict(vendor: Any, projects: Optional[List[Any]] = None) -> Dict[str, Any]:
    """Build a single vendor entry in the monolith wire shape (camelCase + _type + projects)."""
    from app.utilities.timezones import IST

    def _fmt(dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        if dt.tzinfo is not None:
            dt = dt.astimezone(IST)
        return dt.isoformat()

    return {
        "_type": "Vendor",
        "id": vendor.id,
        "vendorCode": vendor.vendor_code,
        "name": vendor.name,
        "description": vendor.description,
        "active": vendor.active,
        "email": vendor.email,
        "contactPerson": vendor.contact_person,
        "phoneNumber": vendor.phone_number,
        "createdAt": _fmt(vendor.created_at),
        "updatedAt": _fmt(vendor.updated_at),
        "deletedAt": _fmt(vendor.deleted_at),
        "projects": [_project_dict(p) for p in (projects or [])],
    }
