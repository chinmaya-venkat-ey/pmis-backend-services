"""Comment schemas — Doc-35 "send-event" model.

A comment carries body OR attachments (or both). The service layer
enforces the invariant; this schema only describes the wire surface.

Targets supported: ``project`` | ``milestone`` | ``activity`` | ``task``
| ``subtask`` (matches the monolith's polymorphism whitelist).

Deletion: author or admin can soft-delete a comment (matches the monolith).
No moderation reason is required — the deleted_at + deleted_by audit
fields capture the operation. Note the WIRE surface does NOT expose
``deleted_by`` (monolith only emits ``deleted_at`` on the wire); the
column is preserved for audit but not serialized.

Author surface (monolith parity): comment responses embed a nested
``author`` object ``{id, login, fullName, email}`` instead of
a flat ``authorUserId`` string. The controller resolves the user from
the cross-schema mirror at response-build time.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, ClassVar, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.schemas._base import ResponseModel


class CommentAttachment(BaseModel):
    """One entry in a comment row's ``attachments`` JSONB list.

    The FE fetches bytes directly from ``url``. ``mimeType`` /
    ``sizeBytes`` / ``uploadedAt`` use camelCase aliases so the JSON
    written on the row matches what the FE renders without a per-field
    rename.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    url: str
    filename: str
    mime_type: Annotated[Optional[str], Field(default=None, alias="mimeType")]
    size_bytes: Annotated[Optional[int], Field(default=None, alias="sizeBytes")]
    uploaded_at: Annotated[Optional[datetime], Field(default=None, alias="uploadedAt")]


class CommentAuthor(ResponseModel):
    """Embedded author object on a comment response (monolith parity).

    Resolved from ``users.users`` mirror at response-build time.
    Reflects only the public-safe fields the monolith exposes on
    comments: ``id``, ``login``, ``fullName``, ``email``.
    """

    id: str
    login: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None


class CommentResponse(ResponseModel):
    """Returned by list / create endpoints. Soft-deleted rows expose
    ``deleted_at`` but NOT ``deleted_by`` (monolith parity — the latter
    stays on the DB row for audit but never reaches the wire).
    """

    # Monolith parity: ``attachments`` is ALWAYS emitted as a list (``[]``
    # when none); the controller normalises NULL JSONB rows to ``[]``
    # before this schema sees them.
    id: str
    target_kind: str
    target_id: str
    body: Optional[str] = None
    author: Optional[CommentAuthor] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    attachments: List[Any] = Field(default_factory=list)

    @field_validator("attachments", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        # The DB column is JSONB-nullable: rows with no attachments
        # store SQL NULL, which Pydantic sees as ``None``. Monolith
        # parity demands ``attachments: []`` always be present on the
        # wire, so coerce here at the validator boundary (instead of
        # forcing every caller to remember).
        return v if v is not None else []


class CommentDeleteSuccess(ResponseModel):
    """Monolith parity: DELETE /comments/{id} returns a ``Success``
    envelope ``{_type: "Success", message: "Comment <uuid> deleted."}``
    NOT the full Comment row. Wrap layer uses ``_hal_type`` to stamp
    ``_type: "Success"`` on the wire.
    """

    _hal_type: ClassVar[str] = "Success"
    model_config = ConfigDict(extra="forbid")

    message: str


class CommentCreateRequest(BaseModel):
    """POST /project/<kind>/{id}/comments — JSON arm of the create endpoint.

    On the multipart arm ``body`` arrives as a Form field and ``files``
    as UploadFile entries; the route layer reads both and builds the
    attachment envelopes via the file client. Either a non-empty body
    or at least one attachment is required.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="forbid",
    )
    # Matches monolith ``app/api/v3/comments/services/create.py:76-80``
    # which caps body at 5000 characters.
    body: Annotated[Optional[str], Field(default=None, max_length=5000)]
    attachments: Optional[List[CommentAttachment]] = None

    @model_validator(mode="after")
    def _body_or_attachments_required(self):
        if not (self.body and self.body.strip()) and not (self.attachments or []):
            raise ValueError("body or attachments must be present")
        return self
