"""Pydantic schemas for SLA image attachments."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# MIME types accepted on upload. The form field is "image" so we reject
# anything outside this set with a friendly error before forwarding to
# pmis-file-store.
ALLOWED_IMAGE_MIMES = frozenset({
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
})


class SlaAttachmentResponse(BaseModel):
    """One image attachment row on an SLA template."""

    id: str
    sla_id: str
    # pmis-file-store handle (canonical). Used for refresh-url / delete
    # round-trips back to filestore.
    file_id: str
    # Cached download URL. May expire (typically 1h). Call
    # POST /attachments/{id}/refresh-url to get a fresh one.
    file_url: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    caption: Optional[str] = None
    uploaded_by: Optional[str] = None
    uploaded_at: Optional[datetime] = None


class SlaAttachmentCaptionUpdate(BaseModel):
    """PATCH body for editing a caption."""

    caption: Optional[str] = Field(None, max_length=500)


class SlaAttachmentRefreshResponse(BaseModel):
    """POST /attachments/{id}/refresh-url response."""

    id: str
    file_url: str
    expires_in_seconds: Optional[int] = None
