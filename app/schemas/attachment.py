"""Attachment-listing wire shapes for the per-target attachment
endpoints.

Attachments are stored on the shared ``project.comments`` table — the
``GET .../{kind}/{id}/attachments`` listing returns the slim per-file
shape (one row per file, carrying its parent comment id so the delete
endpoint can target it).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AttachmentRow(BaseModel):
    """One file in the attachment listing.

    ``id`` is the parent comment row id — pass it to
    ``DELETE /project/attachments/{id}`` (or
    ``DELETE /project/comments/{id}``) to soft-delete the row.
    """

    model_config = ConfigDict(from_attributes=False)

    id: str
    filename: Optional[str] = None
    url: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    uploaded_at: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


class AttachmentListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    total: int
    elements: List[AttachmentRow] = Field(default_factory=list)
