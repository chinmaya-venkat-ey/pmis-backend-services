"""#323 — schemas for the document access-control management API.

Superadmin/admin use these to see a target's documents (newest-first) and to
set/replace/clear the per-document role rules. Responses are snake_case here;
the global wrap layer camelizes keys on the wire.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas._base import ResponseModel


_REQUEST_CONFIG = ConfigDict(
    populate_by_name=True, alias_generator=to_camel, extra="forbid",
)


class DocumentAccessRuleEntry(BaseModel):
    """One grant: a role, optionally narrowed to an org and/or division. When
    both are omitted the role is matched at the document's own project."""

    model_config = _REQUEST_CONFIG

    role_name: Annotated[str, Field(min_length=1, max_length=64)]
    organization_id: Optional[str] = None
    division: Optional[str] = None


class DocumentAccessUpdateRequest(BaseModel):
    """Replace the document's access rules. An empty list clears every rule →
    the document becomes PUBLIC again."""

    model_config = _REQUEST_CONFIG

    rules: List[DocumentAccessRuleEntry] = Field(default_factory=list)


class DocumentAccessRuleView(ResponseModel):
    role_name: str
    organization_id: Optional[str] = None
    division: Optional[str] = None


class DocumentAccessResponse(ResponseModel):
    """A document's current access state."""

    comment_id: str
    # False = PUBLIC (no live rule); True = restricted to the rules below.
    is_restricted: bool = False
    rules: List[DocumentAccessRuleView] = Field(default_factory=list)


class DocumentAccessListItem(ResponseModel):
    comment_id: str
    filename: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[datetime] = None
    uploaded_by: Optional[str] = None
    is_restricted: bool = False
    rules: List[DocumentAccessRuleView] = Field(default_factory=list)


class DocumentAccessList(ResponseModel):
    """The management menu: a target's documents, newest-first, each with its
    current access state."""

    target_kind: str
    target_id: str
    documents: List[DocumentAccessListItem] = Field(default_factory=list)
