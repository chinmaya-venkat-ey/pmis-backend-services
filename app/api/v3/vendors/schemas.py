"""Vendor request/response schemas."""
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class VendorCreateRequest(BaseModel):
    """Body for POST /vendors/create.

    Contact fields (`email`, `contactPerson`, `phoneNumber`) are
    optional. Email goes through Pydantic's loose RFC 5322 check; phone
    is a free-form string (international formats vary too much for a
    one-size regex).
    """
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    active: bool = Field(True)
    email: Optional[EmailStr] = Field(
        None, description="Vendor primary contact email.",
    )
    contactPerson: Optional[str] = Field(
        None, alias="contact_person", max_length=255,
        description="Person at the vendor org to reach out to.",
    )
    phoneNumber: Optional[str] = Field(
        None, alias="phone_number", max_length=50,
        description=(
            "Free-form phone number. No regex check — international "
            "formats vary; FE may apply its own client-side mask."
        ),
    )
    projectIds: Optional[List[str]] = Field(
        None,
        alias="project_ids",
        description=(
            "Optional list of project UUIDs to attach to this vendor at "
            "creation time. Each id must reference a live project that is "
            "not closed/completed and not soft-deleted. Symmetric with the "
            "project-side `vendorIds` field — same association table is "
            "written either way. Omit / null to create a vendor with no "
            "projects (the typical case)."
        ),
    )


class VendorUpdateRequest(BaseModel):
    """Body for PATCH /vendors/{id}. Same fields as create, all optional.

    `projectIds` semantics on PATCH: ``None`` (omitted) leaves the existing
    vendor-project mappings unchanged; ``[]`` clears them; a non-empty list
    REPLACES the full mapping with exactly those project ids. Mirror of
    the existing project-side ``vendorIds`` semantics.
    """
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    active: Optional[bool] = None
    email: Optional[EmailStr] = None
    contactPerson: Optional[str] = Field(
        None, alias="contact_person", max_length=255,
    )
    phoneNumber: Optional[str] = Field(
        None, alias="phone_number", max_length=50,
    )
    projectIds: Optional[List[str]] = Field(
        None, alias="project_ids",
    )
