"""Pydantic v2 schemas for the divisions catalog."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas._base import ResponseModel


class DivisionCreateRequest(BaseModel):
    """Body of POST /masters/divisions/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", populate_by_name=True)

    # Bug #220: the wire `code` is NOT accepted from the client — it is
    # derived server-side from `label` (see DivisionService.create). Any
    # client-supplied `code` is ignored (extra="ignore").
    label: Annotated[str, Field(min_length=1, max_length=255,
                                description="Display label (e.g. 'TMD1', 'Engineering'). "
                                            "Unique; the wire code is generated from it.")]
    # FE sends camelCase `requiresOther`; alias maps it to this field.
    requires_other: bool = Field(default=False, alias="requiresOther",
                                 description="If true, the FE shows a free-text 'specify other' input")
    active: bool = Field(default=True)
    email: Annotated[EmailStr, Field(description="Doc 36: contact email (required)")]
    phone_number: Annotated[str, Field(min_length=1, max_length=50,
                                       description="Doc 36: contact phone (required)")]


class DivisionUpdateRequest(BaseModel):
    """Body of PATCH /masters/divisions/{code}/update — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", populate_by_name=True)

    label: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    # FE sends camelCase `requiresOther`; alias maps it to this field.
    requires_other: Annotated[Optional[bool], Field(default=None, alias="requiresOther")]
    active: Annotated[Optional[bool], Field(default=None)]
    email: Annotated[Optional[EmailStr], Field(default=None)]
    phone_number: Annotated[Optional[str], Field(default=None, min_length=1, max_length=50)]


class DivisionResponse(ResponseModel):
    """Returned by GET /masters/divisions/list and /details."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    code: str
    label: str
    # Serialized as camelCase to match VM API and FE fromApi expectations.
    is_builtin: bool = Field(serialization_alias="isBuiltin")
    requires_other: bool = Field(serialization_alias="requiresOther")
    active: bool
    email: str
    phone_number: str = Field(serialization_alias="phoneNumber")
    created_at: datetime
    updated_at: datetime
