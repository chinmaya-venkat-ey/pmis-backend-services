"""Vendor request/response schemas."""
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from ....shared.phone import validate_phone_number


class UserAssignmentEntry(BaseModel):
    """One row in the vendor's ``user_assignments`` matrix.

    Carries a ``(project_id, role, user_ids[])`` tuple — the set of
    users to hold ``role`` on ``project_id``. The ``role`` string is
    the FE's display label (e.g. ``"Project Admin"``) — the service
    layer maps it to the canonical role name. Duplicate user_ids in
    a single entry are de-duped server-side. ``user_ids: []`` is
    valid and means "no users should hold this (project, role)".
    """
    model_config = ConfigDict(populate_by_name=True)
    project_id: str = Field(..., alias="project_id")
    role: str = Field(..., description="Role display label or canonical name.")
    user_ids: List[str] = Field(
        default_factory=list, alias="user_ids",
        description="UUIDs of users that should hold (project, role).",
    )


class VendorCreateRequest(BaseModel):
    """Body for POST /vendors/create.

    Contact fields:
      * ``email`` and ``contactPerson`` are optional.
      * ``phoneNumber`` is **required** on create (matches the user
        schema so both entities now demand a phone number for new rows).
        Existing vendors with NULL phone numbers stay readable; only
        creates and explicit re-sets are gated.

    Email goes through Pydantic's loose RFC 5322 check; phone is a
    free-form string (international formats vary too much for a
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
    phoneNumber: str = Field(
        ...,
        alias="phone_number",
        min_length=1,
        max_length=50,
        description=(
            "Required on create. Accepts an optional leading ``+`` "
            "country-code prefix; ``[7..15]`` digits total after "
            "stripping spaces / hyphens / parens / dots. Mirrors the "
            "user schema's ``phoneNumber`` field exactly."
        ),
    )

    @field_validator("phoneNumber", mode="before")
    @classmethod
    def _validate_phone(cls, v):
        return validate_phone_number(v)

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

    userAssignments: Optional[List[UserAssignmentEntry]] = Field(
        None,
        alias="user_assignments",
        description=(
            "Doc 44 round 6: per-(project, role) user assignments to "
            "wire up at vendor creation time. Each entry sets the EXACT "
            "set of users holding the role on that project — existing "
            "assignments not in user_ids are revoked, missing ones are "
            "granted. project_id must reference a project owned by this "
            "vendor."
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

    @field_validator("phoneNumber", mode="before")
    @classmethod
    def _validate_phone(cls, v):
        # Optional on PATCH — None / unset means "no change".
        if v is None:
            return v
        return validate_phone_number(v)

    projectIds: Optional[List[str]] = Field(
        None, alias="project_ids",
    )

    userAssignments: Optional[List[UserAssignmentEntry]] = Field(
        None,
        alias="user_assignments",
        description=(
            "Doc 44 round 6: per-(project, role) user assignments. Each "
            "entry sets the EXACT set of users holding the role on that "
            "project — existing assignments not in user_ids are revoked, "
            "missing ones are granted. project_id must reference a "
            "project owned by this vendor."
        ),
    )
