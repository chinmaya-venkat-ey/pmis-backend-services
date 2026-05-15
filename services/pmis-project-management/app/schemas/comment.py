"""Comment schemas — Doc-35 "send-event" model.

A comment carries body OR attachments (or both). Service layer enforces
that invariant; this schema enforces a softer rule that prevents both
fields from being absent on the wire.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CommentAttachment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    filename: str
    mime_type: Annotated[Optional[str], Field(default=None, alias="mimeType")]
    size_bytes: Annotated[Optional[int], Field(default=None, alias="sizeBytes")]
    uploaded_at: Annotated[Optional[datetime], Field(default=None, alias="uploadedAt")]


class CommentResponse(BaseModel):
    """Returned by list / create / moderate endpoints.

    For tombstoned rows (round-7 Q8 moderation delete), `body` and
    `attachments` are NULL; `deleted_at` + `deleted_by` +
    `moderation_reason` carry the audit trail; `author_user_id` is
    preserved so the tombstone still names the original author.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    target_kind: str
    target_id: str
    body: Optional[str] = None
    attachments: Optional[List[Any]] = None
    author_user_id: str
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
    moderation_reason: Optional[str] = None


class CommentModerateRequest(BaseModel):
    """Body for DELETE /project/comments/{id}/delete (admin/super_admin only).

    Per round-7 Q8: moderation is a TOMBSTONE — the row stays, body and
    attachments are blanked, and the audit fields (deleted_by, moderation_reason)
    are set. The reason is required to enforce a documented justification.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    moderation_reason: Annotated[str, Field(min_length=1, max_length=2000)]


class CommentCreateRequest(BaseModel):
    """POST /project/<kind>/{id}/comments/create.

    Either `body` or `attachments` must be present. Service-layer raises
    CommentBodyOrAttachmentRequiredError otherwise.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    body: Annotated[Optional[str], Field(default=None, max_length=20000)]
    attachments: Optional[List[CommentAttachment]] = None

    @model_validator(mode="after")
    def _body_or_attachments_required(self):
        if not (self.body and self.body.strip()) and not (self.attachments or []):
            raise ValueError("body or attachments must be present")
        return self
