"""Pydantic schemas for file objects — request/response shapes."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas._base import ResponseModel


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class FileUploadMetadata(BaseModel):
    """Optional JSON metadata supplied alongside a multipart file upload."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    folder: str = Field(
        ...,
        description=(
            "Logical folder / bucket sub-path. "
            "Example values: project-attachments, profile-photos, milestone-docs"
        ),
    )
    entity_type: Optional[str] = Field(
        None,
        description="Entity kind the file belongs to (project, milestone, activity, task, subtask, user).",
    )
    entity_id: Optional[str] = Field(
        None,
        description="UUID of the owning entity.",
    )
    extra_metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Arbitrary key/value pairs stored alongside the file record.",
    )


class FileSearchRequest(BaseModel):
    """Query-parameter bag for GET /files/."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    folder: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    uploaded_by: Optional[str] = None
    include_deleted: bool = False
    offset: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100, alias="pageSize")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class FileObjectResponse(ResponseModel):
    """Wire shape for a single file record."""

    id: str
    folder: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    original_filename: str
    s3_key: str
    s3_bucket: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    content_hash: Optional[str] = None
    public_url: Optional[str] = None
    extra_metadata: Optional[Dict[str, Any]] = None
    uploaded_by: Optional[str] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FileDownloadResponse(BaseModel):
    """Returned by GET /files/{id}/download — caller uses the URL directly."""
    file_id: str
    original_filename: str
    mime_type: Optional[str]
    size_bytes: Optional[int]
    download_url: str
    expires_in_seconds: Optional[int] = None


class FileUploadResponse(BaseModel):
    """Returned immediately after a successful upload."""
    file_id: str
    original_filename: str
    folder: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    s3_key: str
    s3_bucket: str
    mime_type: Optional[str]
    size_bytes: Optional[int]
    download_url: str
    expires_in_seconds: Optional[int]
    created_at: datetime


class FileDeleteResponse(BaseModel):
    message: str
    file_id: str


class FileRestoreResponse(BaseModel):
    message: str
    file_id: str
