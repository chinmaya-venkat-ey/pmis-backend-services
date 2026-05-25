"""Project schemas — request / response models for /project/projects/*.

Wire convention (matches monolith):
  * Request bodies accept BOTH camelCase aliases AND snake_case field
    names — ``alias_generator=to_camel`` + ``populate_by_name=True``. So
    ``startDate`` and ``start_date`` are both valid, and the FE can keep
    sending its existing camelCase payloads.
  * Response bodies camelize at the HAL wrapper layer (see
    ``app.core.api_route._camelize``) so every key on the wire ends up
    camelCase regardless of the Pydantic field name.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.schemas._base import ResponseModel
from app.schemas.attachment import AttachmentRow


# Monolith parity: schema-level status validation uses this hardcoded
# 4-value fallback (matches PMIS-OpenProject/.../transitions.py:
# PROJECT_STATUS_CHOICES). Service-level transition validation (uses the
# full ``masters.project_status_transitions`` catalog) only fires on PATCH.
_PROJECT_STATUS_CHOICES = ("new", "draft", "published", "closed")
_ERR_END_BEFORE_START = "end_date cannot be before start_date"


# ---------------------------------------------------------------------------
# Shared config for request bodies — accept camelCase OR snake_case.
# ---------------------------------------------------------------------------

_REQUEST_CONFIG = ConfigDict(
    alias_generator=to_camel,
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class _VendorChip(BaseModel):
    """Slim vendor object embedded on the project response — matches the
    monolith's ``vendors[]`` shape (``{id, name}``) so the FE renders
    organisation chips without a per-id round-trip. Monolith parity: no
    ``active`` field on the chip."""

    model_config = ConfigDict(from_attributes=False)
    id: str
    name: Optional[str] = None


class ProjectResponse(ResponseModel):
    # Field order matches monolith ``format_project_response`` byte-for-byte:
    # id, projectCode, name, description, active, public, isPublic,
    # statusExplanation, status, owner, ownerOther, category,
    # categoryOther, categoryOtherReason, vendors, startDate, endDate,
    # actualStartDate, actualEndDate, parentId, createdBy, updatedBy,
    # createdAt, updatedAt, deletedAt, deletedBy.
    id: str
    project_code: str
    name: str
    description: Optional[str] = None
    active: bool
    public: bool
    is_public: bool = False
    status_explanation: Optional[str] = None

    status: str
    owner: Optional[str] = None
    owner_other: Optional[str] = None
    category: Optional[str] = None
    category_other: Optional[str] = None
    category_other_reason: Optional[str] = None

    vendors: List[_VendorChip] = Field(default_factory=list)

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None

    parent_id: Optional[str] = None

    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None

    # Monolith parity: ``attachments`` is included ONLY on the GET
    # single-project response. Create / update / upsert / save / publish
    # / close responses + every list element OMIT this field entirely.
    # Controller populates it on ``get()``; HAL wrap layer drops the key
    # when its value is None so other endpoints don't leak ``"attachments": null``.
    attachments: Optional[List[AttachmentRow]] = None


# ---------------------------------------------------------------------------
# Create / Update / Upsert / Close
# ---------------------------------------------------------------------------

class ProjectCreateRequest(BaseModel):
    """POST /project/projects/create body — JSON arm of the dual-mode endpoint.

    Accepts both camelCase aliases (``vendorIds``, ``startDate``,
    ``statusExplanation``, ``parentId``, ``ownerOther``) and snake_case
    field names. On the multipart arm the same fields arrive as form
    values; ``vendor_ids`` is JSON-encoded inside multipart so it can
    carry an array.
    """

    model_config = _REQUEST_CONFIG

    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    active: bool = True
    public: bool = False
    status_explanation: Annotated[Optional[str], Field(default=None, max_length=5000)]
    parent_id: Annotated[Optional[str], Field(default=None, max_length=36)]

    # Monolith parity: status defaults to "new" on create/upsert.
    status: Annotated[Optional[str], Field(default="new", max_length=50)]
    owner: Annotated[Optional[str], Field(default=None, max_length=255)]
    owner_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    category: Annotated[Optional[str], Field(default=None, max_length=50)]
    category_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    category_other_reason: Annotated[Optional[str], Field(default=None, max_length=1000)]

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

    vendor_ids: List[str] = Field(default_factory=list)

    # Monolith parity: schema-level status validator with the 4-value
    # fallback. Raw FastAPI ``{"detail": [...]}`` error shape on failure.
    @field_validator("status")
    @classmethod
    def _validate_status(cls, v):
        if v is None:
            return v
        if v not in _PROJECT_STATUS_CHOICES:
            raise ValueError(
                f"Invalid status '{v}'. Allowed: {', '.join(_PROJECT_STATUS_CHOICES)}"
            )
        return v

    # Monolith parity: schema-level end-date check as a FIELD validator
    # (matches monolith ``@field_validator("end_date")``) so the
    # RequestValidationError's ``loc`` is ``["endDate"]`` and ``input``
    # is just the bad value — not the whole request body. Note: no
    # ``_owner_other_requires_value`` here; service-level
    # ``validate_owner_pair`` produces the canonical camelCase message.
    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError(_ERR_END_BEFORE_START)
        return v


class ProjectUpdateRequest(BaseModel):
    """PATCH /project/projects/{uuid} body — partial update.

    Same camelCase / snake_case dual acceptance as Create. ``active``,
    ``status``, and ``parent_id`` are settable here (matches monolith's
    ``ProjectUpdateRequest`` — see PMIS-OpenProject/app/api/v3/projects/
    schemas.py:104).
    """

    model_config = _REQUEST_CONFIG

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    active: Optional[bool] = None
    public: Optional[bool] = None
    status_explanation: Annotated[Optional[str], Field(default=None, max_length=5000)]
    parent_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    # Monolith parity: status defaults to "new" on create/upsert.
    status: Annotated[Optional[str], Field(default="new", max_length=50)]
    owner: Annotated[Optional[str], Field(default=None, max_length=255)]
    owner_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    vendor_ids: Optional[List[str]] = None

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError(_ERR_END_BEFORE_START)
        return v


class ProjectUpsertRequest(BaseModel):
    """PUT /project/projects/{uuid} body — idempotent create-or-update.

    Same camelCase / snake_case dual acceptance. On first submission the
    row is inserted (201); subsequent submissions update it (200) and
    the response body carries ``_created: false`` so the FE can tell.
    The server auto-generates ``project_code`` on insert and preserves
    it on update.
    """

    model_config = _REQUEST_CONFIG

    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    active: bool = True
    public: bool = False
    status_explanation: Annotated[Optional[str], Field(default=None, max_length=5000)]
    parent_id: Annotated[Optional[str], Field(default=None, max_length=36)]

    # Monolith parity: status defaults to "new" on create/upsert.
    status: Annotated[Optional[str], Field(default="new", max_length=50)]
    owner: Annotated[Optional[str], Field(default=None, max_length=255)]
    owner_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    category: Annotated[Optional[str], Field(default=None, max_length=50)]
    category_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    category_other_reason: Annotated[Optional[str], Field(default=None, max_length=1000)]

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    vendor_ids: Optional[List[str]] = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v):
        if v is None:
            return v
        if v not in _PROJECT_STATUS_CHOICES:
            raise ValueError(
                f"Invalid status '{v}'. Allowed: {', '.join(_PROJECT_STATUS_CHOICES)}"
            )
        return v

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError(_ERR_END_BEFORE_START)
        return v


class ProjectCloseRequest(BaseModel):
    """Optional body for POST /project/projects/{uuid}/close."""

    model_config = _REQUEST_CONFIG
    reason: Annotated[Optional[str], Field(default=None, max_length=5000)]
