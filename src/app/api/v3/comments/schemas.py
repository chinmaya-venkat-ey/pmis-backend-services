"""Comments + attachments API schemas.

The CREATE endpoints use multipart/form-data (so they can carry files
alongside the text body). FastAPI handles that natively via Form() and
UploadFile parameters declared in the route signature, so this module
only contains the QUERY/LIST schemas plus shared validators.
"""
from typing import Optional

from pydantic import BaseModel, Field


class CommentListQuery(BaseModel):
    """Query parameters for listing comments under a target."""
    offset: int = Field(1, ge=1, description="Page number (1-indexed).")
    pageSize: int = Field(20, ge=1, le=100, description="Items per page.")


class AttachmentListQuery(BaseModel):
    """Query parameters for listing standalone attachments under a target."""
    offset: int = Field(1, ge=1, description="Page number (1-indexed).")
    pageSize: int = Field(20, ge=1, le=100, description="Items per page.")
